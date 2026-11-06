#!/usr/bin/env bash
# Image ENTRYPOINT (under `tini -s`, so `docker run` without --init also reaps orphans).
#   devbox         -> sshd as the container user (rag, UID 10001 — not root): developer SSH workspace on $SSH_PORT
#   anything else  -> the image's own entry ($APP_ENTRY: runtime_entry.sh or entrypoint.sh), unchanged
set -eu
if [ "${1:-}" != devbox ]; then
  exec "$APP_ENTRY" "$@"
fi
# The pipeline image sets HOME=/tmp; the workspace uses the passwd home (/home/rag — the persisted home volume).
HOME=$(getent passwd "$(id -u)" | cut -d: -f6)
export HOME
K=$HOME/.devbox
mkdir -p "$K"
# SSH sessions do not inherit the container env (PYTHONPATH, RUN_ENV, SETTINGS_FILE, ...): save it for login shells (profile.sh).
# The container env holds no secrets — settings come only from the mounted settings file.
env | grep -vE '^(HOME|PWD|SHLVL|_|HOSTNAME)=' | while IFS= read -r l; do printf 'export %q\n' "$l"; done > "$K/env.sh"
# First start: opencode config template (internal model only) — the developer fills in the model address.
O=$HOME/.config/opencode/opencode.json
[ -f "$O" ] || { mkdir -p "$(dirname "$O")"; cp /etc/devbox/opencode.json "$O"; }
# git account (option.devbox.gitea_* / git_user_*): read from the mounted settings file inside the container — the token
# never goes through env. A failure only warns; the workspace still starts.
python /etc/devbox/git_cred.py || echo "[devbox] git account setup failed — check option.devbox.gitea_*" >&2
[ -f "$K/ssh_host_ed25519_key" ] || ssh-keygen -q -t ed25519 -N '' -f "$K/ssh_host_ed25519_key"
exec /usr/sbin/sshd -D -e -f /etc/devbox/sshd_config -p "${SSH_PORT:-2222}" \
  -h "$K/ssh_host_ed25519_key" -o PidFile="$K/sshd.pid"
