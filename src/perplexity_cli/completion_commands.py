"""Click command definitions for shell completion."""

from __future__ import annotations

import click

# _ensure_ctx_obj inlined — see below

# ---------------------------------------------------------------------------
# Shell completion scripts
# ---------------------------------------------------------------------------

_BASH_COMPLETION = """\
_pxcli_completion() {
    local IFS=$'\\n'
    COMPREPLY=( $( env COMP_WORDS="${COMP_WORDS[*]}" \\
                   COMP_CWORD=$COMP_CWORD \\
                   _PXCLI_COMPLETE=bash_complete pxcli ) )
    return 0
}
complete -o default -F _pxcli_completion pxcli
"""

_ZSH_COMPLETION = """\
#compdef pxcli

_pxcli() {
    local -a completions
    local -a completions_with_descriptions
    local -a response
    (( ! $+commands[pxcli] )) && return 1
    response=("${(@f)$(env COMP_WORDS="${words[*]}" COMP_CWORD=$((CURRENT-1)) \\
        _PXCLI_COMPLETE=zsh_complete pxcli)}")
    for key descr in ${(kv)response}; do
        if [[ "$descr" == "_" ]]; then
            completions+=("$key")
        else
            completions_with_descriptions+=("$key":"$descr")
        fi
    done
    if [ -n "$completions_with_descriptions" ]; then
        _describe -V unsorted completions_with_descriptions -U
    fi
    if [ -n "$completions" ]; then
        compadd -U -V unsorted -a completions
    fi
}
if [[ $zsh_eval_context[-1] == loadautofun ]]; then
    _pxcli "$@"
else
    compdef _pxcli pxcli
fi
"""

_FISH_COMPLETION = """\
function __fish_pxcli_complete
    set -lx COMP_WORDS (commandline -cp)
    set -lx COMP_CWORD (math (count (commandline -oc)) - 1)
    set -lx _PXCLI_COMPLETE fish_complete
    set -lx _PXCLI_PROG_NAME pxcli
    pxcli
end
complete -c pxcli -f -a "(__fish_pxcli_complete)"
"""

_AUTH_LOGIN_HELP_REF = "pxcli auth login"
_AUTH_STATUS_HELP_REF = "pxcli auth status"
_STYLE_SET_HELP_REF = "pxcli style set"
# ---------------------------------------------------------------------------
# Completion group
# ---------------------------------------------------------------------------


@click.group(
    "completion",
    help=(
        "Generate shell completion scripts.\n\n"
        "Outputs a shell-specific completion script that enables tab-completion "
        "for pxcli commands, subcommands, and options.  Supports Bash, Zsh, and "
        "Fish shells.\n\n"
        "The generated script should be evaluated by your shell at startup.  "
        "See the subcommand help for shell-specific installation instructions.\n\n"
        "Subcommands:\n\n"
        "  bash  - Generate Bash completion script\n\n"
        "  zsh   - Generate Zsh completion script\n\n"
        "  fish  - Generate Fish completion script\n\n"
        "Quick start:\n\n"
        '  eval "$(pxcli completion bash)"   # Bash\n\n'
        '  eval "$(pxcli completion zsh)"    # Zsh\n\n'
        "  pxcli completion fish | source    # Fish"
    ),
)
@click.pass_context
def completion_group(ctx: click.Context) -> None:
    """Generate shell completion scripts."""
    if ctx.obj is None:
        ctx.obj = {}


@click.command(name="bash")
def completion_bash() -> None:
    """Generate Bash completion script.

    Outputs a Bash completion function that provides tab-completion for all
    pxcli commands, subcommands, options, and arguments.  The script uses
    the COMP_WORDS and COMP_CWORD environment variables to communicate with
    Click's built-in completion machinery.

    \b
    Installation:
      Add the following line to your ~/.bashrc (or ~/.bash_profile on macOS):
        eval "$(pxcli completion bash)"
      Then restart your shell or run:
        source ~/.bashrc

    \b
    Examples:
        pxcli completion bash                     # Print to stdout
        pxcli completion bash >> ~/.bashrc        # Append to bashrc
        pxcli completion bash > /etc/bash_completion.d/pxcli  # System-wide

    \b
    After installation, tab-completion works for:
        pxcli <TAB>              # Lists commands
        pxcli auth <TAB>         # Lists auth subcommands
        pxcli query --<TAB>      # Lists query options
    """
    click.echo(_BASH_COMPLETION)


@click.command(name="zsh")
def completion_zsh() -> None:
    """Generate Zsh completion script.

    Outputs a Zsh completion function (_pxcli) that provides tab-completion
    for all pxcli commands, subcommands, options, and arguments.  The script
    registers itself with Zsh's compdef system.

    \b
    Installation:
      Add the following line to your ~/.zshrc:
        eval "$(pxcli completion zsh)"
      Then restart your shell or run:
        source ~/.zshrc

    \b
    Alternative (site-functions):
      pxcli completion zsh > ~/.zsh/completions/_pxcli
      # Ensure ~/.zsh/completions is in your fpath

    \b
    Examples:
        pxcli completion zsh                       # Print to stdout
        pxcli completion zsh >> ~/.zshrc            # Append to zshrc
        pxcli completion zsh > ~/.zsh/completions/_pxcli  # Site function

    \b
    After installation, tab-completion works for:
        pxcli <TAB>              # Lists commands
        pxcli auth <TAB>         # Lists auth subcommands
        pxcli query --<TAB>      # Lists query options
    """
    click.echo(_ZSH_COMPLETION)


@click.command(name="fish")
def completion_fish() -> None:
    """Generate Fish completion script.

    Outputs a Fish shell completion function that provides tab-completion
    for all pxcli commands, subcommands, options, and arguments.

    \b
    Installation:
      Run the following command (persists across sessions):
        pxcli completion fish > ~/.config/fish/completions/pxcli.fish

    \b
    Temporary (current session only):
        pxcli completion fish | source

    \b
    Examples:
        pxcli completion fish                                     # Print to stdout
        pxcli completion fish > ~/.config/fish/completions/pxcli.fish  # Persist
        pxcli completion fish | source                            # Current session

    \b
    After installation, tab-completion works for:
        pxcli <TAB>              # Lists commands
        pxcli auth <TAB>         # Lists auth subcommands
        pxcli query --<TAB>      # Lists query options
    """
    click.echo(_FISH_COMPLETION)


completion_group.add_command(completion_bash)
completion_group.add_command(completion_zsh)
completion_group.add_command(completion_fish)
