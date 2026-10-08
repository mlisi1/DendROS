_DENDROS_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
_DENDROS_PIPE="${_DENDROS_DIR}/dendROS_pipe.py"
# Official DendROS brand colors — "[dend" in brand blue, "ROS]" in brand orange.
# Must stay in sync with lib.colors.DENDROS_TAG.
_DENDROS_TAG=$'\033[38;2;0;75;107;1m[dend\033[38;2;224;127;0;1mROS]\033[0m'

dendros() {
    case "${1:-}" in
        config)  python3 "${_DENDROS_DIR}/dendros_config.py" ;;
        init)    python3 "${_DENDROS_DIR}/dendros_init.py" "${@:2}" ;;
        disable)
            export DENDROS_DISABLE=1
            python3 -c "
import sys; sys.path.insert(0, '${_DENDROS_DIR}')
from lib.global_config import set_disable_flag
set_disable_flag(True)
"
            echo "${_DENDROS_TAG} colorization disabled system-wide (all terminals)"
            ;;
        enable)
            unset DENDROS_DISABLE
            python3 -c "
import sys; sys.path.insert(0, '${_DENDROS_DIR}')
from lib.global_config import set_disable_flag
set_disable_flag(False)
"
            echo "${_DENDROS_TAG} colorization enabled system-wide (all terminals)"
            ;;
        focus)
            if [[ -z "${2:-}" ]]; then
                echo "Usage: dendros focus <node_name>"
                return 1
            fi
            python3 -c "
import sys; sys.path.insert(0, '${_DENDROS_DIR}')
from lib.global_config import set_tui_command
set_tui_command('focus ' + sys.argv[1])
" "$2"
            echo "${_DENDROS_TAG} focus command sent"
            ;;
        find)
            if [[ -z "${2:-}" ]]; then
                echo "Usage: dendros find <text>"
                return 1
            fi
            python3 -c "
import sys; sys.path.insert(0, '${_DENDROS_DIR}')
from lib.global_config import set_tui_command
set_tui_command('find ' + sys.argv[1])
" "${*:2}"
            echo "${_DENDROS_TAG} find command sent"
            ;;
        grep)
            # No text = drop the grep filter (keeps any focus), same as a bare `grep` in the console.
            python3 -c "
import sys; sys.path.insert(0, '${_DENDROS_DIR}')
from lib.global_config import set_tui_command
set_tui_command(('grep ' + sys.argv[1]).strip())
" "${*:2}"
            echo "${_DENDROS_TAG} grep command sent"
            ;;
        level)
            # No level = drop the level filter, same as a bare `level` in the console.
            python3 -c "
import sys; sys.path.insert(0, '${_DENDROS_DIR}')
from lib.global_config import set_tui_command
set_tui_command(('level ' + sys.argv[1]).strip())
" "${2:-}"
            echo "${_DENDROS_TAG} level command sent"
            ;;
        mute|unmute)
            if [[ -z "${2:-}" ]]; then
                [[ "$1" == unmute ]] && echo "Usage: dendros unmute <node_name|all>" \
                                     || echo "Usage: dendros mute <node_name>"
                return 1
            fi
            python3 -c "
import sys; sys.path.insert(0, '${_DENDROS_DIR}')
from lib.global_config import set_tui_command
set_tui_command(sys.argv[1] + ' ' + sys.argv[2])
" "$1" "$2"
            echo "${_DENDROS_TAG} $1 command sent"
            ;;
        reopen)  DENDROS_SHELL_PID=$$ python3 "${_DENDROS_DIR}/dendros_reopen.py" ;;
        clear)
            python3 -c "
import sys; sys.path.insert(0, '${_DENDROS_DIR}')
from lib.global_config import set_tui_command
set_tui_command('clear')
"
            echo "${_DENDROS_TAG} clear command sent"
            ;;
        *)
            echo "Usage: dendros <command>"
            echo ""
            echo "Commands:"
            echo "  config    Open the interactive config editor"
            echo "  init      Generate a stock dendROS.yaml from the package's launch files"
            echo "            Options: --recursive/-r  also scan included packages"
            echo "                     --labels/-l     auto-generate group labels"
            echo "  disable   Disable colorization system-wide (all terminals, incl. already-running launches)"
            echo "  enable    Re-enable colorization system-wide (all terminals)"
            echo "  focus     Filter an already-running ros2 launch TUI to one node's output"
            echo "            (same as typing 'focus <node_name>' in the TUI's \\ console)"
            echo "  find      Jump to text in an already-running ros2 launch TUI (Tab/Shift+Tab to step)"
            echo "            (same as typing 'find <text>' in the TUI's \\ console)"
            echo "  grep      Show only lines containing text in an already-running ros2 launch TUI"
            echo "            (combines with focus; no text = drop the grep filter)"
            echo "  level     Show only lines at a severity or worse (debug|info|warn|error|fatal) in a running TUI"
            echo "            (lines without a level, e.g. tracebacks, stay visible; no level = drop the filter)"
            echo "  mute      Hide one node's lines in a running TUI (not a mode: stays until unmute/clear)"
            echo "  unmute    Show a muted node again in a running TUI ('unmute all' for every one)"
            echo "  clear     Restore the full scrollback (drops focus, level, grep, find and mutes) in a running TUI"
            echo "  reopen    Reopen this terminal's last ros2 launch TUI run (read-only scrollback)"
            ;;
    esac
}

_dendros_complete() {
    local cur="${COMP_WORDS[COMP_CWORD]}"

    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=($(compgen -W "config init disable enable focus find grep level mute unmute clear reopen" -- "$cur"))
        return
    fi

    case "${COMP_WORDS[1]}" in
        init)
            COMPREPLY=($(compgen -W "--recursive --labels -r -l" -- "$cur"))
            ;;
        level)
            COMPREPLY=($(compgen -W "debug info warn error fatal" -- "$cur"))
            ;;
        *)
            COMPREPLY=()
            ;;
    esac
}
complete -F _dendros_complete dendros

ros2() {
    # Set DENDROS_DISABLE=1 (local to this shell) or run `dendros disable`
    # (system-wide, all terminals) to bypass colorization and use the real ros2 directly.
    if [[ -n "${DENDROS_DISABLE:-}" && "${DENDROS_DISABLE}" != "0" ]] \
       || [[ -f "$HOME/.config/dendROS/disable.flag" ]]; then
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
        RCUTILS_COLORIZED_OUTPUT=1 PYTHONUNBUFFERED=1 "$_ROS2_BIN" "$@" 2>&1 | DENDROS_SHELL_PID=$$ python3 "$_DENDROS_PIPE" "$@"
        return ${PIPESTATUS[0]}
    elif [[ "$1" == "node" && "$2" == "list" ]]; then
        "$_ROS2_BIN" "$@" | python3 "${_DENDROS_DIR}/dendros_node_list.py"
        return ${PIPESTATUS[0]}
    elif [[ "$1" == "node" && "$2" == "info" ]]; then
        "$_ROS2_BIN" "$@" | python3 "${_DENDROS_DIR}/dendros_node_info.py"
        return ${PIPESTATUS[0]}
    elif [[ "$1" == "service" && "$2" == "list" ]]; then
        "$_ROS2_BIN" "$@" | python3 "${_DENDROS_DIR}/dendros_service_list.py"
        return ${PIPESTATUS[0]}
    elif [[ "$1" == "action" && "$2" == "list" ]]; then
        "$_ROS2_BIN" "$@" | python3 "${_DENDROS_DIR}/dendros_action_list.py"
        return ${PIPESTATUS[0]}
    elif [[ "$1" == "param" && "$2" == "list" ]]; then
        "$_ROS2_BIN" "$@" | python3 "${_DENDROS_DIR}/dendros_param_list.py" "${@:3}"
        return ${PIPESTATUS[0]}
    elif [[ "$1" == "param" && "$2" == "describe" ]]; then
        "$_ROS2_BIN" "$@" | python3 "${_DENDROS_DIR}/dendros_param_describe.py" "${@:3}"
        return ${PIPESTATUS[0]}
    elif [[ "$1" == "topic" && "$2" == "list" ]]; then
        "$_ROS2_BIN" "$@" | python3 "${_DENDROS_DIR}/dendros_topic_list.py"
        return ${PIPESTATUS[0]}
    else
        "$_ROS2_BIN" "$@"
    fi
}
