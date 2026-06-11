_DENDROS_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
_DENDROS_PIPE="${_DENDROS_DIR}/dendROS_pipe.py"

ros2() {
    # Set DENDROS_DISABLE=1 to bypass colorization and use the real ros2 directly
    if [[ -n "${DENDROS_DISABLE:-}" && "${DENDROS_DISABLE}" != "0" ]]; then
        local _BIN
        _BIN="$(type -P ros2 2>/dev/null)"
        [[ -z "$_BIN" && -n "${ROS_DISTRO:-}" ]] && _BIN="/opt/ros/${ROS_DISTRO}/bin/ros2"
        "$_BIN" "$@"
        return
    fi

    local _ROS2_BIN
    _ROS2_BIN="$(type -P ros2 2>/dev/null)"
    if [[ -z "$_ROS2_BIN" && -n "${ROS_DISTRO:-}" ]]; then
        _ROS2_BIN="/opt/ros/${ROS_DISTRO}/bin/ros2"
    fi

    if [[ "$1" == "launch" || "$1" == "run" ]]; then
        RCUTILS_COLORIZED_OUTPUT=1 "$_ROS2_BIN" "$@" 2>&1 | python3 "$_DENDROS_PIPE" "$@"
        return ${PIPESTATUS[0]}
    else
        "$_ROS2_BIN" "$@"
    fi
}
