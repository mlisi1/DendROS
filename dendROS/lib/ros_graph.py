"""ROS 2 graph queries — shared by dendros_node_info, future dendros_topic_*, etc.

Public API
----------
get_topic_publishers(topics, timeout=2.0)
    Return {topic: [node_basename, ...]} by reading the live ROS 2 graph.

    Primary path : rclpy  — reads the DDS graph cache in-process (< 100 ms).
    Fallback     : concurrent `ros2 topic info --verbose` subprocesses.
    Both paths return empty lists per topic on failure; never raise.
"""

import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed


# ── subprocess parser ─────────────────────────────────────────────────────────

def _parse_publishers(text):
    """Extract publisher node basenames from `ros2 topic info --verbose` output."""
    publishers = []
    current_node = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('Node name:'):
            current_node = line.split(':', 1)[1].strip()
        elif line == 'Endpoint type: PUBLISHER' and current_node:
            publishers.append(current_node)
            current_node = None
        elif not line:
            current_node = None
    return publishers


# ── query implementations ─────────────────────────────────────────────────────

def _query_rclpy(topics):
    """Query via rclpy (single DDS graph read — fastest path)."""
    import rclpy  # noqa: PLC0415  (intentional lazy import)

    init_called = not rclpy.ok()
    if init_called:
        rclpy.init(args=[])

    probe = rclpy.create_node(f'_dendros_probe_{os.getpid()}')
    try:
        return {
            topic: [i.node_name for i in probe.get_publishers_info_by_topic(topic)]
            for topic in topics
        }
    finally:
        probe.destroy_node()
        if init_called:
            try:
                rclpy.try_shutdown()
            except Exception:
                pass


def _query_subprocess_one(topic, timeout):
    """Query one topic via `ros2 topic info --verbose`."""
    ros2 = shutil.which('ros2')
    if not ros2:
        return []
    try:
        r = subprocess.run(
            [ros2, 'topic', 'info', '--verbose', topic],
            capture_output=True, text=True, timeout=timeout,
        )
        return _parse_publishers(r.stdout)
    except Exception:
        return []


# ── public API ────────────────────────────────────────────────────────────────

def get_topic_publishers(topics, timeout=2.0):
    """Return {topic: [node_basename, ...]} for each topic.

    node_basename is the unqualified node name (no leading slash / namespace),
    matching the keys used in dendROS color_map configs.

    Tries rclpy first; falls back to parallel subprocess calls.
    Never raises — returns empty lists on any failure.
    """
    if not topics:
        return {}

    try:
        return _query_rclpy(list(topics))
    except Exception:
        pass

    result = {}
    with ThreadPoolExecutor(max_workers=min(len(topics), 8)) as ex:
        fmap = {ex.submit(_query_subprocess_one, t, timeout): t for t in topics}
        for fut in as_completed(fmap):
            result[fmap[fut]] = fut.result() or []
    return result
