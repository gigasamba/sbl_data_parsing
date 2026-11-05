# Login shells (SSH): restore the container env saved by dev_entry.sh.
[ -f "$HOME/.devbox/env.sh" ] && . "$HOME/.devbox/env.sh"
# Per-user tools (pip install --user) live in the persisted home.
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac
