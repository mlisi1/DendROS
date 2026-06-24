"""ROS 2 graph queries — shared by dendros_node_info, future dendros_topic_*, etc.

Public API
----------
get_topic_publishers(topics, timeout=2.0)
    {topic: [node_basename, ...]}  — publisher nodes per topic.

get_topic_subscribers(topics, timeout=2.0)
    {topic: [node_basename, ...]}  — subscriber nodes per topic.

get_service_servers(services, timeout=2.0)
    {service: [node_basename, ...]}  — server nodes per service.

get_action_servers(actions, timeout=2.0)
    {action: [node_basename, ...]}  — server nodes per action.

get_input_providers(topics=(), services=(), actions=(), timeout=2.0)
    Unified query for all three in a single rclpy session (most efficient when
    mixing types).  Returns one flat dict covering all requested items.

get_all_providers(topics=(), services=(), actions=(), pub_topics=(), timeout=2.0)
    Like get_input_providers but also queries subscribers for pub_topics.
    pub_topics results are stored under '__sub__<topic>' keys.
    Preferred by dendros_node_info to avoid a second rclpy session.

All functions:
  • Primary path  : rclpy — reads the local DDS graph cache in-process.
  • Fallback       : subprocess / name heuristic (see details below).
  • Never raise; return empty lists per item on any failure.
  • node_basename is the unqualified node name (no slash/namespace), matching
    the keys used in dendROS color_map configs.
"""

import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed


# ── subprocess helpers ────────────────────────────────────────────────────────

def _parse_topic_endpoints(text, endpoint_type):
    """Extract node basenames of a given endpoint type from `ros2 topic info --verbose`."""
    nodes = []
    current_node = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('Node name:'):
            current_node = line.split(':', 1)[1].strip()
        elif line == f'Endpoint type: {endpoint_type}' and current_node:
            nodes.append(current_node)
            current_node = None
        elif not line:
            current_node = None
    return nodes


def _parse_topic_publishers(text):
    return _parse_topic_endpoints(text, 'PUBLISHER')


def _parse_topic_subscribers(text):
    return _parse_topic_endpoints(text, 'SUBSCRIPTION')


def _query_topic_subprocess(topic, timeout):
    ros2 = shutil.which('ros2')
    if not ros2:
        return []
    try:
        r = subprocess.run(
            [ros2, 'topic', 'info', '--verbose', topic],
            capture_output=True, text=True, timeout=timeout,
        )
        return _parse_topic_publishers(r.stdout)
    except Exception:
        return []


def _query_topic_subscribers_subprocess(topic, timeout):
    ros2 = shutil.which('ros2')
    if not ros2:
        return []
    try:
        r = subprocess.run(
            [ros2, 'topic', 'info', '--verbose', topic],
            capture_output=True, text=True, timeout=timeout,
        )
        return _parse_topic_subscribers(r.stdout)
    except Exception:
        return []


def _heuristic_node(name):
    """Fallback: extract likely server node from /<node_name>/... naming convention.

    Returns a list of at most one basename, or [] if the name is flat (no slash).
    E.g. '/path_planner/compute_path' → ['path_planner']
         '/navigate_to_pose'          → []
    """
    parts = name.lstrip('/').split('/')
    return [parts[0]] if len(parts) >= 2 else []


# ── rclpy unified query ───────────────────────────────────────────────────────

# Key prefix for publisher-section subscriber results in the combined dict.
_PUB_SUB_PREFIX = '__sub__'


def _query_all_rclpy(topics, services, actions, pub_topics=()):
    """Single rclpy session covering input providers + optional publisher subscribers."""
    import time   # noqa: PLC0415
    import rclpy  # noqa: PLC0415

    init_called = not rclpy.ok()
    if init_called:
        rclpy.init(args=[])

    probe = rclpy.create_node(f'_dendros_probe_{os.getpid()}')
    # Brief wait for DDS discovery to propagate to the fresh probe node.
    time.sleep(0.1)
    try:
        result = {}

        # ── publisher lookup (Subscribers section) ────────────────────────────
        for topic in topics:
            result[topic] = [i.node_name
                             for i in probe.get_publishers_info_by_topic(topic)]

        # ── subscriber lookup (Publishers section indicators) ─────────────────
        for topic in pub_topics:
            result[_PUB_SUB_PREFIX + topic] = [
                i.node_name for i in probe.get_subscriptions_info_by_topic(topic)
            ]

        # ── services + actions: reverse-scan all nodes ────────────────────────
        if services or actions:
            services = set(services)
            actions  = set(actions)
            for node_name, ns in probe.get_node_names_and_namespaces():
                if services:
                    try:
                        for srv, _ in probe.get_service_names_and_types_by_node(node_name, ns):
                            if srv in services:
                                result.setdefault(srv, []).append(node_name)
                    except Exception:
                        pass
                if actions:
                    try:
                        for act, _ in probe.get_action_server_names_and_types_by_node(node_name, ns):
                            if act in actions:
                                result.setdefault(act, []).append(node_name)
                    except Exception:
                        pass

        return result
    finally:
        probe.destroy_node()
        if init_called:
            try:
                rclpy.try_shutdown()
            except Exception:
                pass


# ── public API ────────────────────────────────────────────────────────────────

def get_all_providers(topics=(), services=(), actions=(), pub_topics=(), timeout=2.0):
    """Single-session query for all node info graph needs.

    Returns a flat dict {key: [node_basename, ...]} where:
      • topic / service / action names map to their provider nodes
      • '__sub__<topic>' keys map to subscriber nodes for pub_topics

    Primary path: single rclpy session.
    Fallbacks per type:
      • Topics        : parallel ros2 topic info --verbose subprocesses
      • pub_topics    : parallel ros2 topic info --verbose subprocesses (subscriber parse)
      • Services      : name heuristic (/node_name/... → node_name)
      • Actions       : name heuristic; applied even after rclpy if result is empty
    """
    topics     = list(topics)
    services   = list(services)
    actions    = list(actions)
    pub_topics = list(pub_topics)

    if not (topics or services or actions or pub_topics):
        return {}

    # ── rclpy primary ─────────────────────────────────────────────────────────
    try:
        result = _query_all_rclpy(topics, services, actions, pub_topics)
        # Per-item heuristic for services/actions not resolved by rclpy.
        # rclpy may silently skip nodes where the method throws; catch those gaps.
        for act in actions:
            if not result.get(act):
                result[act] = _heuristic_node(act)
        for srv in services:
            if not result.get(srv):
                result[srv] = _heuristic_node(srv)
        return result
    except Exception:
        pass

    # ── per-type fallbacks ────────────────────────────────────────────────────
    result = {}
    all_topic_jobs = {}

    with ThreadPoolExecutor(max_workers=min(len(topics) + len(pub_topics), 8) or 1) as ex:
        for t in topics:
            all_topic_jobs[ex.submit(_query_topic_subprocess, t, timeout)] = t
        for t in pub_topics:
            all_topic_jobs[ex.submit(_query_topic_subscribers_subprocess, t, timeout)] = (
                _PUB_SUB_PREFIX + t
            )
        for fut in as_completed(all_topic_jobs):
            result[all_topic_jobs[fut]] = fut.result() or []

    for srv in services:
        result[srv] = _heuristic_node(srv)
    for act in actions:
        result[act] = _heuristic_node(act)

    return result


def get_input_providers(topics=(), services=(), actions=(), timeout=2.0):
    """Query the live ROS 2 graph for publishers/servers of all given items.

    Convenience wrapper around get_all_providers for backward compatibility.
    """
    return get_all_providers(topics=topics, services=services,
                             actions=actions, timeout=timeout)


def get_topic_publishers(topics, timeout=2.0):
    """Return {topic: [node_basename, ...]} for each topic."""
    return get_all_providers(topics=topics, timeout=timeout)


def get_service_servers(services, timeout=2.0):
    """Return {service: [node_basename, ...]} for each service."""
    return get_all_providers(services=services, timeout=timeout)


def get_action_servers(actions, timeout=2.0):
    """Return {action: [node_basename, ...]} for each action."""
    return get_all_providers(actions=actions, timeout=timeout)


def get_topic_subscribers(topics, timeout=2.0):
    """Return {topic: [node_basename, ...]} for subscriber nodes of each topic."""
    topics = list(topics)
    if not topics:
        return {}
    raw = get_all_providers(pub_topics=topics, timeout=timeout)
    return {t: raw.get(_PUB_SUB_PREFIX + t, []) for t in topics}
