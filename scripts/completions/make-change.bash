# Source after bash-completion to add the change workflow's variable values.
if ! declare -F _init_completion >/dev/null; then
    return 0
fi
if ! declare -F _make >/dev/null && ! declare -F _comp_cmd_make >/dev/null; then
    _completion_loader make 2>/dev/null
fi

_arkhai_make_change()
{
    local cur prev words cword
    _init_completion -n = || return
    local value name path archived=false
    for name in "${words[@]}"; do
        [[ $name == archive-cleanup ]] && archived=true
    done
    case $cur in
        CHANGE=*)
            value=${cur#CHANGE=}
            COMPREPLY=()
            if $archived; then
                for path in openspec/changes/archive/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*/; do
                    [[ -d $path ]] || continue
                    name=${path%/}
                    name=${name##*/}
                    name=${name:11}
                    [[ $name == "$value"* ]] && COMPREPLY+=("$name")
                done
            else
                for path in openspec/changes/*/; do
                    [[ -d $path && $path != openspec/changes/archive/ ]] || continue
                    name=${path%/}
                    name=${name##*/}
                    [[ $name == "$value"* ]] && COMPREPLY+=("$name")
                done
            fi
            ;;
        KIND=*)
            value=${cur#KIND=}
            COMPREPLY=()
            for name in design implementation pre-closeout closeout; do
                [[ $name == "$value"* ]] && COMPREPLY+=("$name")
            done
            ;;
        *)
            # Installed bash-completion releases expose either make function.
            if declare -F _make >/dev/null; then
                _make "$@"
            elif declare -F _comp_cmd_make >/dev/null; then
                _comp_cmd_make "$@"
            fi
            ;;
    esac
}

complete -F _arkhai_make_change make
