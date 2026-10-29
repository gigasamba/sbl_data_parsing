"""임베딩 호출 — 구조화(문서 청크 'passage')와 검색(질문 'query')이 같은 모델·접두·정규화를 써야 함.
폐쇄망 전제: 로컬 모델은 미리 반입한 캐시에서만(HF_HUB_OFFLINE), API는 내부망 주소만."""

import json
import os
from pathlib import Path

import numpy as np

from common.ai.guard import require_internal
from common.ai.guard import settle_tokens as _g_settle_tokens
from common.ai.guard import urlopen_metered as _g_urlopen_metered
from common.ai.llm import profile as _profile
from common.config.settings import by_env, cfg, reveal
from common.core.paths import APP_ROOT

ROOT = APP_ROOT  # output/query_cache.sqlite 기준(옛 dev/)

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # env 남김 — 라이브러리(5-3 H)
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")  # env 남김 — 라이브러리(5-3 H)

ST_MODELS = {"e5-small": "intfloat/multilingual-e5-small", "e5-base": "intfloat/multilingual-e5-base", "bge-m3": "BAAI/bge-m3"}
_ST_CACHE: dict = {}


def _load_st_model(name):
    if name not in _ST_CACHE:
        from sentence_transformers import SentenceTransformer

        try:
            _ST_CACHE[name] = SentenceTransformer(ST_MODELS[name], device="cpu")
        except Exception as e:
            raise RuntimeError(
                f"임베딩 모델 '{name}'({ST_MODELS[name]}) 로드 실패 — 폐쇄망 로컬 캐시에 없음. "
                f"HF_HUB_OFFLINE=1이며 미리 반입된 모델만 쓸 수 있다: {e}"
            ) from e
    return _ST_CACHE[name]


def _embed_api(texts, kind="passage"):
    """OpenAI 호환 /embeddings — 주소·모델 이름은 common/models.py profile("embed")에서(GA6, 호출 방식은 urllib 그대로).
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
    key = reveal(by_env(prof.key_env)) if prof.key_env else None  # key_env는 env 이름 — 값은 설정 객체에서(S7b)
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    r, reserved = _g_urlopen_metered(req, cfg().models.embed.timeout, "EMBED")
    try:
        data = json.load(r)
    finally:
        r.close()
    _g_settle_tokens(reserved, prof.model, data.get("usage"))  # BR45 — 응답에 토큰 수 있으면 실제 비용으로(없으면 flat 유지)
    v = np.asarray([d["embedding"] for d in sorted(data["data"], key=lambda d: d.get("index", 0))], dtype=np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)


def _query_cache():
    """질문 임베딩 재사용 — 같은 질문을 조합·k마다 API로 다시 보내지 않게(10-04 실험이 대부분 이 대기).
    RV1(OP11 교정) — 기본 켬: EMBED_QUERY_CACHE 미설정·빈 값이면 ROOT/output/query_cache.sqlite(EMBED_CACHE의
    output/edw/embed_cache.sqlite 관례와 같은 자리) · EMBED_QUERY_CACHE=0이면 끔.
    (S7b — 빈 값은 옛 코드에서 sqlite3.connect('')=호출마다 임시 DB였음 → 기본 경로로 고침, D-028 ⑩·refactor.md C-27)
    열쇠 = sha256(모델·접두·질문) — 질문 원문은 저장하지 않음(해시만). WAL(동시 읽기·쓰기가 서로 안 막음) +
    timeout(쓰기 잠금이면 기다림, 여러 MCP 워커·동시 질의가 같은 파일을 써도 죽지 않음)."""
    path = cfg().models.embed.query_cache
    if not path:  # None(미설정) 또는 ''(빈 값) → 기본 경로(캐시 켬)
        path = str(ROOT / "output" / "query_cache.sqlite")
    if path == "0":
        return None
    import sqlite3

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)  # 질의 경로 — 오래 기다리느니 캐시 없이 계산(MCP 30초 상한)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS q (k TEXT PRIMARY KEY, v BLOB)")
    except Exception:
        db.close()
        raise
    return db


def _evict_query_cache(db):
    """RV1 — 용량 상한(EMBED_QUERY_CACHE_MAX, 기본 20000행). 넘으면 가장 오래된 것부터 지움(INSERT OR REPLACE는
    rowid를 새로 받으므로 rowid 오름차순 = 오래된 순). =0이면 상한 없음(장기 운영 무한 증가 방지가 목적이라
    기본은 켬)."""
    cap = cfg().models.embed.query_cache_max
    if not cap:
        return
    n = db.execute("SELECT COUNT(*) FROM q").fetchone()[0]
    if n > cap:
        db.execute("DELETE FROM q WHERE rowid IN (SELECT rowid FROM q ORDER BY rowid LIMIT ?)", (n - cap,))
        db.commit()


def query_model_mismatch(meta):
    """AD41 — 색인(묶음 meta)이 api 임베딩이면 이 프로세스의 EMBED_MODEL과 같은지. 다르면 사람이 읽을 이유(문자열), 같거나 로컬 모델이면 None.
    로컬 모델(bge-m3 등)은 meta['embed']를 그대로 질의에 쓰므로 어긋날 수 없음."""
    if meta.get("embed") != "api" or not meta.get("embed_model"):
        return None
    cur = cfg().models.embed.model or ""
    if cur.removeprefix("openai/") == str(meta["embed_model"]).removeprefix("openai/"):
        return None
    return (
        f"질의 임베딩 모델 {cur or '(EMBED_MODEL 없음)'} ≠ 색인 {meta['embed_model']} — "
        "색인과 같은 EMBED_MODEL로 MCP를 띄우거나 그 모델로 만든 색인(index_id)을 고름"
    )


def embed_texts(embed, texts, kind):
    """embed: e5-small·e5-base·bge-m3·api. e5는 query:/passage: 접두 필요."""
    if not texts:
        return np.zeros((0, 1), dtype=np.float32)
    if kind == "query":
        import sqlite3

        try:
            return _embed_query_cached(embed, texts, kind)
        except sqlite3.Error:  # 캐시 잠금·손상 — 질의는 캐시 없이(RV1 기본 켬 뒤 be-qa 지적)
            pass
    return _embed_uncached(embed, texts, kind)


def _embed_query_cached(embed, texts, kind):
    if (db := _query_cache()) is None:
        return _embed_uncached(embed, texts, kind)
    try:
        import hashlib

        e = cfg().models.embed
        mid = f"{embed}|{e.model or ''}|{e.query_prefix or ''}"
        keys = [hashlib.sha256((mid + "\n" + t).encode("utf-8")).hexdigest() for t in texts]
        got = dict(db.execute(f"SELECT k, v FROM q WHERE k IN ({','.join('?' * len(keys))})", keys).fetchall())
        todo = [i for i, k in enumerate(keys) if k not in got]
        if todo:
            new = _embed_uncached(embed, [texts[i] for i in todo], kind)
            for i, v in zip(todo, new):
                got[keys[i]] = np.asarray(v, dtype=np.float32).tobytes()
            db.executemany("INSERT OR REPLACE INTO q VALUES (?, ?)", [(keys[i], got[keys[i]]) for i in todo])
            db.commit()
            _evict_query_cache(db)
        return np.stack([np.frombuffer(got[k], dtype=np.float32) for k in keys])
    finally:
        db.close()


def _embed_uncached(embed, texts, kind):
    if embed == "api":
        return _embed_api(texts, kind)
    model = _load_st_model(embed)
    prefix = f"{kind}: " if embed.startswith("e5") else ""
    vecs = model.encode([prefix + t for t in texts], normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)
