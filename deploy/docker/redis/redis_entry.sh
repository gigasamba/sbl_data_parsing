#!/bin/sh
# Redis image entry (compose-redis.yml — one plain node per server, port $REDIS_PORT default 8010).
# The password comes from the mounted file /run/secrets/redis_pw — never env or command-line arguments.
set -eu
P=/run/secrets/redis_pw
W=$( [ -f "$P" ] && head -n1 "$P" | tr -d '\r' || true)
[ -n "$W" ] || { echo "[redis] $P missing or empty — create <SBL_ROOT>/redis_pw before up (server-guide §6-7)" >&2; exit 2; }
case "$W" in *'"'* | *'\'*) echo "[redis] password must not contain \" or \\" >&2; exit 2 ;; esac
umask 077
printf 'requirepass "%s"\n' "$W" > /tmp/auth.conf
unset W
# ponytail: runs as root (no gosu/su-exec in this image, busybox setpriv cannot switch users) — the container is the boundary
exec redis-server /etc/redis/node.conf --include /tmp/auth.conf --port "${REDIS_PORT:-8010}"
