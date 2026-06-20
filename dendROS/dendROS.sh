_DENDROS_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
_DENDROS_PIPE="${_DENDROS_DIR}/dendROS_pipe.py"

dendros() {
    case "${1:-}" in
        config)  python3 "${_DENDROS_DIR}/dendros_config.py" ;;
        init)    python3 "${_DENDROS_DIR}/dendros_init.py" "${@:2}" ;;
        disable)
            export DENDROS_DISABLE=1
            echo "[dendROS] colorization disabled (DENDROS_DISABLE=1)"
            ;;
        enable)
            unset DENDROS_DISABLE
            echo "[dendROS] colorization enabled"
            ;;
        *)
            echo "Usage: dendros <command>"
            echo ""
            echo "Commands:"
            echo "  config    Open the interactive config editor"
            echo "  init      Generate a stock dendROS.yaml from the package's launch files"
            echo "            Options: --recursive/-r  also scan included packages"
            echo "                     --labels/-l     auto-generate group labels"
            echo "  disable   Disable colorization in this shell (sets DENDROS_DISABLE=1)"
            echo "  enable    Re-enable colorization in this shell (unsets DENDROS_DISABLE)"
            ;;
    esac
}

_dendros_complete() {
    local cur="${COMP_WORDS[COMP_CWORD]}"

    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=($(compgen -W "config init disable enable" -- "$cur"))
        return
    fi

    case "${COMP_WORDS[1]}" in
        init)
            COMPREPLY=($(compgen -W "--recursive --labels -r -l" -- "$cur"))
            ;;
        *)
            COMPREPLY=()
            ;;
    esac
}
complete -F _dendros_complete dendros

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
    elif [[ "$1" == "node" && "$2" == "list" ]]; then
        "$_ROS2_BIN" "$@" | python3 "${_DENDROS_DIR}/dendros_node_list.py"
        return ${PIPESTATUS[0]}
    else
        "$_ROS2_BIN" "$@"
    fi
}
