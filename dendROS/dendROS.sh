_DENDROS_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
_DENDROS_PIPE="${_DENDROS_DIR}/dendROS_pipe.py"

dendros() {
    case "${1:-}" in
        config)  python3 "${_DENDROS_DIR}/dendros_config.py" ;;
        init)    python3 "${_DENDROS_DIR}/dendros_init.py" "${@:2}" ;;
        dismiss)
            local _pid_file="/tmp/dendros_alert_$$"
            if [[ ! -f "$_pid_file" ]]; then
                echo "[dendROS] no active crash alert session"
                return 1
            fi
            local _alert_pid
            _alert_pid="$(cat "$_pid_file" 2>/dev/null)"
            if [[ -z "$_alert_pid" ]]; then
                echo "[dendROS] alert pid file is empty"
                return 1
            fi
            if kill -SIGUSR1 "$_alert_pid" 2>/dev/null; then
                : # success — pipe toggles the overlay
            else
                echo "[dendROS] alert process not running (pid ${_alert_pid})"
                rm -f "$_pid_file"
                return 1
            fi
            ;;
        *)
            echo "Usage: dendros <command>"
            echo ""
            echo "Commands:"
            echo "  config    Open the interactive config editor"
            echo "  init      Generate a stock dendROS.yaml from the package's launch files"
            echo "            Options: --recursive  also scan included packages"
            echo "  dismiss   Toggle the crash alert overlay (requires crash_alert: on)"
            ;;
    esac
}

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
