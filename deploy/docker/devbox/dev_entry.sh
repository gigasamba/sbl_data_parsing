#!/usr/bin/env bash
# Image ENTRYPOINT (under `tini -s`, so `docker run` without --init also reaps orphans).
#   devbox [cmd]   -> sshd: developer SSH workspace on $SSH_PORT (as rag, key login; as root, also root password login —
#                     server compose compose-dev.yml / compose-prd.yml); with cmd, that app command also runs in the background
#   anything else  -> the image's own entry ($APP_ENTRY: runtime_entry.sh or entrypoint.sh), unchanged
set -eu
if [ "${1:-}" != devbox ]; then
  exec "$APP_ENTRY" "$@"
fi
# The pipeline image sets HOME=/tmp; the workspace uses the passwd home (root: /root — the bench home folder mounted there).
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
# git name/email (option.devbox.git_user_*): read from the mounted settings file inside the container.
# A failure only warns; the workspace still starts.
python /etc/devbox/git_cred.py || echo "[devbox] git name/email setup failed — check option.devbox.git_user_*" >&2
[ -f "$K/ssh_host_ed25519_key" ] || ssh-keygen -q -t ed25519 -N '' -f "$K/ssh_host_ed25519_key"
# root (server compose compose-dev.yml / compose-prd.yml, user "0"): root password from the compose secret /run/secrets/root_pw
# (settings.yaml option.devbox.root_password, passed by host_ctl.sh), else one built into the image; root password login. Servers only (dev, prd). Never via env or the repo.
SSHD_OPTS=()
if [ "$(id -u)" = 0 ]; then
  # run_env as the apps resolve it (env RUN_ENV, else the mounted settings.yaml) — only dev or prd opens root login
  E=$(python -c 'import os; from common.config.settings import resolve_run_env as r; print(r(os.environ) or "")' 2>/dev/null || true)
  case "$E" in dev | prd) ;; *) echo "[devbox] root SSH is for the servers only (dev, prd) — run_env is '${E:-?}' (settings.yaml required.env.run_env)" >&2; exit 2 ;; esac
  P=/run/secrets/root_pw
  W=$( [ -f "$P" ] && head -n1 "$P" | tr -d '\r' || true)
  if [ -n "$W" ]; then
    printf 'root:%s\n' "$W" | chpasswd
  elif [ "$(getent shadow root | cut -d: -f2 | cut -c1)" = '$' ]; then
    echo "[devbox] $P missing or empty — using the root password built into the image" >&2
  else
    echo "[devbox] no root password — fill settings.yaml option.devbox.root_password and run host_ctl.sh up -d --force-recreate" >&2; exit 2
  fi
  unset W
  git config --global --replace-all safe.directory '*'   # code folder is owned by 10001; root git would refuse it
  SSHD_OPTS=(-o PermitRootLogin=yes -o PasswordAuthentication=yes)
fi
# `devbox <command>`: also run that app command in the background (e.g. `devbox mcp` — the MCP server next to sshd).
# Not supervised: if it exits, the container stays up with sshd only (restart the container by hand).
shift
if [ $# -gt 0 ]; then "$APP_ENTRY" "$@" & fi
exec /usr/sbin/sshd -D -e -f /etc/devbox/sshd_config -p "${SSH_PORT:-2222}" \
  -h "$K/ssh_host_ed25519_key" -o PidFile="$K/sshd.pid" ${SSHD_OPTS[@]+"${SSHD_OPTS[@]}"}
