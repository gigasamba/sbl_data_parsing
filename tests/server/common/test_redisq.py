"""Redis 작업 전달 계약 — redis-py·외부 서비스 없이 쓰는 명령만 메모리 대역으로 검증."""

import json
from unittest import mock

from common.config import settings
from common.store import redisq


class FakeRedis:
    def __init__(self):
        self.hashes, self.sets, self.lists, self.streams = {}, {}, {}, {}
        self.ttls, self.pending, self.transactions, self.values = {}, {}, [], {}
        self.on_wait = None
        self.sequence = 0
        self.consumers = {}

    def pipeline(self, transaction=True):
        assert transaction
        return FakeTransaction(self)

    def hset(self, name, mapping):
        self.hashes.setdefault(name, {}).update({k: str(v) for k, v in mapping.items()})

    def hgetall(self, name):
        return dict(self.hashes.get(name, {}))

    def sadd(self, name, value):
        self.sets.setdefault(name, set()).add(value)

    def scard(self, name):
        return len(self.sets.get(name, set()))

    def srem(self, name, value):
        self.sets.setdefault(name, set()).discard(value)

    def sismember(self, name, value):
        return value in self.sets.get(name, set())

    def xgroup_create(self, name, group, id, mkstream):
        self.streams.setdefault(name, [])

    def xadd(self, name, fields):
        self.sequence += 1
        mid = f"{self.sequence}-0"
        self.streams.setdefault(name, []).append((mid, fields))
        return mid

    def xreadgroup(self, group, consumer, streams, count, block):
        self.consumers.setdefault(consumer, 0)
        name = next(iter(streams))
        for mid, fields in self.streams.get(name, []):
            if mid not in self.pending:
                self.pending[mid] = {"consumer": consumer, "times_delivered": 1}
                return [(name, [(mid, fields)])]
        return []

    def xautoclaim(self, name, group, consumer, min_idle_time, start_id, count):
        for mid, item in self.pending.items():
            if item.get("dead"):
                item.update(consumer=consumer, times_delivered=item["times_delivered"] + 1, dead=False)
                return ["0-0", [(mid, dict(self.streams[name])[mid])], []]
        return ["0-0", [], []]

    def xpending_range(self, name, group, low, high, count, consumername=None):
        return [
            {"message_id": mid, **item}
            for mid, item in self.pending.items()
            if (low == "-" or mid >= low) and (high == "+" or mid <= high) and (consumername is None or item["consumer"] == consumername)
        ][:count]

    def exists(self, name):
        return int(name in self.hashes or name in self.values)

    def xinfo_consumers(self, name, group):
        return [
            dict(name=c, idle=idle, pending=sum(p["consumer"] == c for p in self.pending.values())) for c, idle in self.consumers.items()
        ]

    def xgroup_delconsumer(self, name, group, consumer):
        del self.consumers[consumer]

    def xclaim(self, name, group, consumer, min_idle_time, message_ids):
        rows = []
        for mid in message_ids:
            item = self.pending[mid]
            if self.consumers[item["consumer"]] >= min_idle_time:
                item.update(consumer=consumer, times_delivered=item["times_delivered"] + 1)
                rows.append((mid, dict(self.streams[name])[mid]))
        return rows

    def xack(self, name, group, message):
        # 완료 메시지는 다시 전달하지 않는다.
        self.pending.pop(message, None)

    def xdel(self, name, message):
        self.streams[name] = [(mid, fields) for mid, fields in self.streams.get(name, []) if mid != message]

    def lpush(self, name, value):
        self.lists.setdefault(name, []).insert(0, value)

    def blpop(self, name, timeout):
        assert timeout > 0  # 0은 무한 대기라 사용 금지
        if self.on_wait:
            self.on_wait()
        values = self.lists.get(name, [])
        return (name, values.pop(0)) if values else None

    def expire(self, name, ttl):
        self.ttls[name] = ttl

    def set(self, name, value, ex):
        self.values[name] = value
        self.ttls[name] = ex

    def scan_iter(self, match):
        import fnmatch

        return iter(k for k in self.values if fnmatch.fnmatch(k, match))

    def delete(self, name):
        self.values.pop(name, None)

    def ping(self):
        return True

    def close(self):
        pass


class FakeTransaction:
    def __init__(self, r):
        self.r, self.commands = r, []
        self.writing = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def watch(self, *_):
        pass

    def multi(self):
        self.writing = True

    def execute(self):
        self.r.transactions.append([name for name, _, _ in self.commands])
        return [getattr(self.r, name)(*args, **kw) for name, args, kw in self.commands]

    def __getattr__(self, name):
        def command(*args, **kw):
            if self.writing:
                self.commands.append((name, args, kw))
                return self
            return getattr(self.r, name)(*args, **kw)

        return command


def test_atomic_queue_and_capacity():
    r = FakeRedis()
    with settings.isolated(REDIS_KEY_PREFIX="test_atomic", MCP_PARSE_RESULT_TTL_SEC=123):
        assert redisq.submit(r, "j1", {"filename": "a.txt", "submitted_at": 1}, 2) == 0
        assert redisq.submit(r, "j2", {"filename": "b.txt", "submitted_at": 2}, 2) == 1
        try:
            redisq.submit(r, "j3", {}, 2)
            raise AssertionError("대기열 상한을 넘음")
        except redisq.QueueFull as exc:
            assert str(exc) == redisq.FULL_MESSAGE
        assert r.transactions == [["hset", "sadd", "xadd"]] * 2
        assert r.scard(redisq.key("active")) == 2 and len(r.streams[redisq.key("queue")]) == 2
        redisq.finish(r, "1-0", "j1", "done", elapsed_ms=1)
        assert r.transactions[-1] == ["hset", "lpush", "expire", "expire", "srem", "xack", "xdel"]
        assert json.loads(r.blpop(redisq.key("done", "j1"), 1)[1]) == {"status": "done", "error": None}
        assert r.ttls[redisq.key("job", "j1")] == r.ttls[redisq.key("done", "j1")] == 123
        assert r.scard(redisq.key("active")) == 1
        assert [mid for mid, _ in r.streams[redisq.key("queue")]] == ["2-0"]
        assert redisq.finish(r, "1-0", "j1", "failed") is False  # 중복 알림 방지


def test_names_and_secrets():
    with settings.isolated(REDIS_KEY_PREFIX="queue", REDIS_PASSWORD="very-secret"):
        assert redisq.key("done", "j") == "queue:done:j"
        assert "very-secret" not in redisq.connection_error(RuntimeError("password very-secret failed"))
    assert redisq.filename("a/b:c\n.txt") == "a_b_c_.txt"


def test_group_creation_errors():
    for text, fails in (("BUSYGROUP Consumer Group name already exists", False), ("connection refused", True)):
        r = mock.Mock()
        r.xgroup_create.side_effect = RuntimeError(text)
        try:
            redisq.ensure_group(r)
            assert not fails
        except RuntimeError:
            assert fails


def test_stale_finisher_is_fenced():
    r = FakeRedis()
    redisq.submit(r, "j", {"filename": "a.txt"}, 1)
    r.hset(redisq.key("job", "j"), mapping={"status": "running", "worker": "rescuer", "attempts": 2})
    assert not redisq.finish(r, "1-0", "j", "done", worker="dead", attempts=1)
    assert not r.lists and r.scard(redisq.key("active")) == 1
    assert redisq.finish(r, "1-0", "j", "done", worker="rescuer", attempts=2)


def test_worker_count_limit_and_default():
    from pydantic import ValidationError

    assert settings.CommonParseQueue().mcp_parse_workers == 2
    for value in (None, ""):
        assert settings.CommonParseQueue(mcp_parse_workers=value).mcp_parse_workers == 2
    for count in (1, 2):
        assert settings.CommonParseQueue(mcp_parse_workers=count).mcp_parse_workers == count
    for count in (0, 3):
        try:
            settings.CommonParseQueue(mcp_parse_workers=count)
        except ValidationError as exc:
            assert exc.errors()[0]["loc"] == ("mcp_parse_workers",)
        else:
            raise AssertionError(f"worker {count}개는 허용 범위 밖")


def test_server_requires_redis_password():
    import pytest

    for run in ("local", "dev", "prd"):
        for password in (None, "   ", "test-secret"):
            with settings.isolated(REDIS_PASSWORD=password), mock.patch.object(redisq, "resolve_run_env", return_value=run):
                if run != "local" and not (password or "").strip():
                    with pytest.raises(RuntimeError, match="common.connections.redis.redis_password"):
                        redisq.client()
                else:
                    redisq.require_password()
