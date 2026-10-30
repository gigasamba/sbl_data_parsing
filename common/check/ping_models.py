"""모델 연결 실호출 시험(서버 첫 단계) — LLM·VLM·EMBED에 최소 요청 1건씩 보내 OK/FAIL·지연·응답 모델·(임베딩 차원) 출력.
services.py가 /models 존재만 보는 것과 달리 실제 /chat/completions·/embeddings를 부른다. 보내는 내용은 "ping"과 코드로 만든 1×1 PNG뿐(회사 데이터 없음).
가드: 접두어마다 guard.require_internal → guard.urlopen(외부 주소·NO_PAID_CALLS 차단 그대로). 키는 출력하지 않는다.
  set -a; . $ENV_FILE; set +a; python cli/ping_models.py        # 실패가 하나라도 있으면 종료 코드 1
  자기 점검은 tests/server/common/test_ping_models.py.
"""

import base64
import json
import struct
import sys
import time
import urllib.request
import zlib

from common.ai import adk as A
from common.ai import guard
from common.config.settings import by_env, cfg, reveal  # S7b — 설정 객체(이름을 글자로 짓는 칸은 by_env)


def png_1x1():
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        + chunk(b"IEND", b"")
    )


def payload(prefix, model):
    if prefix == "EMBED":
        return "/embeddings", {"model": model, "input": ["ping"]}
    content = "ping"
    if prefix == "VLM":
        url = "data:image/png;base64," + base64.b64encode(png_1x1()).decode()
        content = [{"type": "text", "text": "ping"}, {"type": "image_url", "image_url": {"url": url}}]
    return "/chat/completions", {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 1}


_NOT_FOUND_RE = ("404", "not found", "model_not_found")
_NAME_HINTS = ("glm", "qwen", "vl", "embed")  # SI10 — 이름에 이것이 들어 있으면 역할별(LLM·VLM·EMBED) 후보로 추정


def model_not_found(why):
    w = (why or "").lower()
    return any(k in w for k in _NOT_FOUND_RE)


def candidates(prefix, base):
    """FAIL이 '모델 없음'일 때 그 서버의 /v1/models에서 이름 힌트가 든 후보 — [(id, 일치 힌트)] (내부망 가드 경유, 키 출력 없음)."""
    try:
        guard.require_internal(base, prefix)
        req = urllib.request.Request(base.rstrip("/") + "/models")
        key = reveal(by_env(f"{prefix}_API_KEY"))
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        with guard.urlopen(req, cfg().models.transport.ping_timeout, prefix) as r:
            ids = [m.get("id") for m in json.load(r).get("data", []) if m.get("id")]
    except Exception:
        return []
    out = []
    for i in ids:
        hits = [h for h in _NAME_HINTS if h in i.lower()]
        if hits:
            out.append((i, "·".join(hits)))
    return out


def ping(prefix):
    base, model = by_env(f"{prefix}_BASE_URL"), by_env(f"{prefix}_MODEL")
    if not base:
        return None
    if prefix in ("LLM", "VLM"):  # common/adk.py complete() 경유(가드·재시도 공용) — EMBED은 GA6로 adk 역할 없음
        try:
            _, body = payload(prefix, model)
            t = time.perf_counter()
            A.complete(prefix.lower(), body["messages"], max_tokens=1, timeout=cfg().models.transport.ping_timeout)
            return True, int((time.perf_counter() - t) * 1000), model, ""
        except Exception as e:
            return False, 0, model or "", f"{type(e).__name__}: {str(e)[:120]}"
    try:
        guard.require_internal(base, prefix)
        path, body = payload(prefix, model)
        req = urllib.request.Request(base.rstrip("/") + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        key = reveal(by_env(f"{prefix}_API_KEY"))
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        t = time.perf_counter()
        with guard.urlopen(req, cfg().models.transport.ping_timeout, prefix) as r:
            d = json.load(r)
        ms = int((time.perf_counter() - t) * 1000)
        extra = ""
        if prefix == "EMBED":
            dim, want = len(d["data"][0]["embedding"]), cfg().models.embed.dim
            extra = f"dim {dim}" + ("" if dim == want else f" ≠ 기대 {want}")
            if dim != want:
                return False, ms, d.get("model", model), extra
        return True, ms, d.get("model", model), extra
    except Exception as e:  # 오류 본문에 키가 섞일 수 있어 유형·짧은 메시지만
        return False, 0, model or "", f"{type(e).__name__}: {str(e)[:120]}"


def main():
    fail = 0
    print("| 접두어 | 결과 | ms | 응답 모델 | 비고 |", "|---|---|---|---|---|", sep="\n")
    not_found = []
    for p in ("LLM", "VLM", "EMBED"):
        r = ping(p)
        if r is None:
            print(f"| {p} | 미설정 | | | |")
            continue
        ok, ms, m, extra = r
        fail += not ok
        print(f"| {p} | {'OK' if ok else 'FAIL'} | {ms} | {m} | {extra} |")
        if not ok and model_not_found(extra):
            not_found.append(p)
    for p in not_found:  # SI10 — 모델 없음(404 등)이면 그 서버에서 연결 가능한 후보를 재탐색
        base = by_env(f"{p}_BASE_URL")
        cands = candidates(p, base)
        print(f"\n{p}: 모델 없음 — {base}의 /v1/models 후보(이름 힌트 일치, 키는 출력 안 함):")
        if cands:
            print("| 모델 id | 일치 힌트 |", "|---|---|", sep="\n")
            for i, hits in cands:
                print(f"| {i} | {hits} |")
        else:
            print("(후보 없음 — /v1/models 응답 확인 또는 내부망 가드 거부)")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    if sys.argv[
        1:
    ]:  # 인자를 받지 않음 — 옛 `--selftest` 같은 인자가 실호출로 넘어가지 않게(자기 점검은 tests/server/common/test_ping_models.py)
        raise SystemExit("인자 없음 — 인자 없이 부르면 모델 실호출. 자기 점검은 pipeline.cli selftest --only ping_models")
    main()
