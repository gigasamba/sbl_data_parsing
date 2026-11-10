#!/bin/sh
# Redis cluster image entry (compose-redis.yml):
#   node  -> redis-server on $REDIS_PORT, announcing $REDIS_IP (the server address clients and other nodes use)
#   init  -> create the cluster from $REDIS_NODES (ip:port list) once; skip if it already exists
# The password comes from the mounted file /run/secrets/redis_pw — never env or command-line arguments.
set -eu
P=/run/secrets/redis_pw
W=$( [ -f "$P" ] && head -n1 "$P" | tr -d '\r' || true)
[ -n "$W" ] || { echo "[redis] $P missing or empty — create <SBL_ROOT>/redis_pw before up (server-guide §6-7)" >&2; exit 2; }
case "$W" in *'"'* | *'\'*) echo "[redis] password must not contain \" or \\" >&2; exit 2 ;; esac
case "${1:-node}" in
  node)
    umask 077
    printf 'requirepass "%s"\nmasterauth "%s"\n' "$W" "$W" > /tmp/auth.conf
    unset W
    # ponytail: runs as root (no gosu/su-exec in this image, busybox setpriv cannot switch users) — the container is the boundary
    exec redis-server /etc/redis/node.conf --include /tmp/auth.conf \
      --port "${REDIS_PORT:?REDIS_PORT}" --cluster-announce-ip "${REDIS_IP:?REDIS_IP — server address}" \
      --cluster-announce-port "$REDIS_PORT" --cluster-announce-bus-port "$((REDIS_PORT + 10000))"
    ;;
  init)
    export REDISCLI_AUTH="$W"
    unset W
    first=${REDIS_NODES%% *}
    for n in ${REDIS_NODES:?REDIS_NODES}; do   # wait until every node answers
      i=0
      until redis-cli -h "${n%:*}" -p "${n##*:}" ping 2>/dev/null | grep -q PONG; do
        i=$((i + 1)); [ "$i" -lt 60 ] || { echo "[redis] $n not answering" >&2; exit 1; }; sleep 1
      done
    done
    if redis-cli -h "${first%:*}" -p "${first##*:}" cluster info | grep -q '^cluster_state:ok'; then
      echo "[redis] cluster already exists — skip"
      exit 0
    fi
    # shellcheck disable=SC2086 — REDIS_NODES is a word list
    redis-cli --cluster create $REDIS_NODES --cluster-replicas "${REDIS_REPLICAS:-1}" --cluster-yes
    ;;
  *) exec "$@" ;;
esac
