"""임베딩 호출 — 구조화(문서 청크 'passage')와 검색(질문 'query')이 같은 모델·접두·정규화를 써야 함.
API(OpenAI 호환 /embeddings, 내부망 주소만)만 쓴다."""

import functools
import json
import time

import numpy as np

from common.ai.guard import require_internal
from common.ai.guard import settle_tokens as _g_settle_tokens
from common.ai.guard import urlopen_metered as _g_urlopen_metered
from common.ai.llm import profile as _profile
from common.config.settings import by_env, cfg, reveal
from common.core import span as _span


def _embed_api(texts, kind="passage", timeout=None):
    """OpenAI 호환 /embeddings — 주소·모델 이름은 common/models.py profile("embed")에서(호출은 urllib).
    모델은 주소·이름만 바꿔 끼움. 내부망만(DONT 13). 질의에는 EMBED_QUERY_PREFIX를 앞에 붙임(Qwen3 임베딩 계열 권장:
    'Instruct: <과업>\\nQuery: ' — \\n은 줄바꿈으로). 결과는 L2 정규화."""
    import urllib.request

    prof = _profile("embed")
    if prof is None:
        raise RuntimeError("embed=api 는 EMBED_BASE_URL·EMBED_MODEL 환경변수가 필요합니다")
    require_internal(prof.base_url, "EMBED")
    pre = cfg().models.embed.query_prefix
    if kind == "query" and pre:
        if len(pre) >= 2 and pre[0] == pre[-1] and pre[0] in "\"'":  # docker run --env-file은 따옴표를 값에 남김(compose는 벗김) — 같게
            pre = pre[1:-1]
        texts = [pre.replace("\\n", "\n") + t for t in texts]
    req = urllib.request.Request(
        prof.base_url.rstrip("/") + "/embeddings",
        data=json.dumps({"model": prof.model.removeprefix("openai/"), "input": texts}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    key = reveal(by_env(prof.key_env)) if prof.key_env else None  # key_env는 env 이름 — 값은 설정 객체에서
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    r, reserved = _g_urlopen_metered(req, timeout or cfg().models.embed.timeout, "EMBED")  # timeout: 부르는 쪽이 덮음(검색 MCP 25초)
    try:
        data = json.load(r)
    finally:
        r.close()
    _span.add_current(embed_tokens=(data.get("usage") or {}).get("total_tokens") or 0)  # 열린 span이 없으면(MCP 검색) no-op
    _g_settle_tokens(reserved, prof.model, data.get("usage"))  # 응답에 토큰 수 있으면 실제 비용으로(없으면 flat 유지)
    v = np.asarray([d["embedding"] for d in sorted(data["data"], key=lambda d: d.get("index", 0))], dtype=np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)


def model_key(name):
    """비교용 모델 이름 — `openai/` 앞붙이를 뗀 것(같은 모델의 두 표기를 같게 봄)."""
    return str(name).removeprefix("openai/")


def query_model_mismatch(meta):
    """색인(묶음 meta)이 api 임베딩이면 이 프로세스의 EMBED_MODEL과 같은지. 다르면 사람이 읽을 이유(문자열), 같거나 api가 아니면 None."""
    if meta.get("embed") != "api" or not meta.get("embed_model"):
        return None
    cur = cfg().models.embed.model or ""
    if model_key(cur) == model_key(meta["embed_model"]):
        return None
    return (
        f"질의 임베딩 모델 {cur or '(EMBED_MODEL 없음)'} ≠ 색인 {meta['embed_model']} — "
        "색인과 같은 EMBED_MODEL로 MCP를 띄우거나 그 모델로 만든 색인(index_id)을 고름"
    )


def embed_texts(embed, texts, kind, timeout=None):
    """embed: api만. kind = query·passage. timeout(초) = 호출 하나 제한(없으면 common.models.embed.timeout).
    질문('query')은 프로세스 안 LRU로 다시 씀 — 같은 질문을 조합·k마다 API로 다시 보내지 않게(질문 원문은 메모리에만)."""
    if not texts:
        return np.zeros((0, 1), dtype=np.float32)
    if kind == "query":
        e = cfg().models.embed
        return np.stack([_query_vec(embed, e.model or "", e.query_prefix or "", t, timeout) for t in texts])
    return _embed_uncached(embed, texts, kind, timeout)


@functools.lru_cache(maxsize=2048)  # ponytail: 프로세스마다 따로·재시작하면 비움 — 여러 프로세스가 나눠 써야 하면 공용 캐시로
def _query_vec(embed, model, prefix, text, timeout):
    """질문 하나의 벡터. model·prefix는 캐시 열쇠로만 받음(설정이 바뀌면 다른 열쇠)."""
    v = _embed_uncached(embed, [text], "query", timeout)[0]
    v.setflags(write=False)  # 캐시가 든 배열을 부르는 쪽이 고치지 않게
    return v


def _embed_uncached(embed, texts, kind, timeout=None):
    if embed != "api":
        raise ValueError(f"임베딩 방식 {embed!r}는 지원하지 않음 — api만(로컬 모델 길은 0.2.0에 지움, pl-46)")
    sp = _span.current()  # 열린 span(구조화 임베딩)이 있을 때만 호출 수·지연을 쌓음. 없으면 이 한 줄만 비용
    t0 = time.monotonic() if sp is not None else 0.0
    out = _embed_api(texts, kind, timeout)
    if sp is not None:
        ms = (time.monotonic() - t0) * 1000
        sp.add(embed_calls=1).observe("embed_call_ms", ms).ext_call(ms)
    return out
