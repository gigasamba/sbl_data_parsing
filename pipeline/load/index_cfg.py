"""pipeline 전용 색인 설정 계약(10-14 함수별 분리 — common/core/index_cfg.py에서 이전, 로직 바이트 동일).
AD41 — 색인 설정 1개 → 기본값 채움(normalize)·파일 읽기(load)·index_id·PG 스키마(pg_schema)·bundle.py용
env(env_for)·재빌드 판정 입력 지문(inputs). cli/index.py(빌더)만 쓴다 — 검색(MCP)은 common.core.index_cfg의
check_id·info·bundle_dir·list_ids·input_drift만 읽는다."""

import hashlib
import json
import re
from pathlib import Path

from common.config.settings import cfg  # S7c — common 칸(PG_SCHEMA) · 자식 덮기 파일(S7e2)
from common.config.settings import child_env as settings_env
from common.core.artifacts import _canon  # stack_matrix S층 열쇠와 같은 표준 JSON(sort_keys·구분자)
from common.core.index_cfg import check_id, glossary_fp, roster_fp

DEFAULTS = {
    "chunker": "structure",
    "chunk_size": None,
    "overlap": None,
    "embed": "bge-m3",
    "embed_model": None,
    "dim": None,
    "summary": "auto",
}
EMBEDS = ("bge-m3", "e5-small", "e5-base", "api", "none")
SUMMARIES = ("auto", "lead")  # llm은 op-08에 지움


def normalize(conf):
    """설정 dict → 기본값을 채운 dict. 모르는 칸·잘못된 값은 ValueError(신뢰 경계 — 사람이 쓴 파일)."""
    if not isinstance(conf, dict):
        raise ValueError("색인 설정은 JSON 객체여야 함")
    extra = sorted(set(conf) - set(DEFAULTS))
    if extra:
        raise ValueError(f"색인 설정에 모르는 칸: {extra} (허용: {sorted(DEFAULTS)})")
    c = {**DEFAULTS, **conf}
    if not isinstance(c["chunker"], str) or not re.fullmatch(r"[a-z0-9_]+", c["chunker"]):
        raise ValueError(f"chunker 이름이 잘못됨: {c['chunker']!r}")
    for k in ("chunk_size", "overlap", "dim"):
        v = c[k]
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v <= 0):
            raise ValueError(f"{k}는 양의 정수 또는 null: {v!r}")
    if c["overlap"] is not None and c["overlap"] >= (c["chunk_size"] or 512):
        raise ValueError(f"overlap({c['overlap']})은 chunk_size({c['chunk_size'] or 512})보다 작아야 함")
    if c["embed"] not in EMBEDS:
        raise ValueError(f"embed는 {EMBEDS} 중 하나: {c['embed']!r}")
    if c["embed"] == "api":
        if not isinstance(c["embed_model"], str) or not c["embed_model"].strip():
            raise ValueError("embed=api면 embed_model(서버 임베딩 모델 이름) 필수")
    elif c["embed_model"] not in (None, c["embed"]):
        raise ValueError(f"embed={c['embed']}면 embed_model은 null 또는 {c['embed']!r}")
    else:
        c["embed_model"] = None  # 같은 뜻 두 표기('bge-m3'·null) → 같은 index_id
    if c["embed"] == "none" and c["dim"] is not None:
        raise ValueError("embed=none(키워드·ID만)이면 dim은 null")
    if c["summary"] not in SUMMARIES:
        raise ValueError(f"summary는 {SUMMARIES} 중 하나: {c['summary']!r}")
    return c


def load(path):
    try:
        conf = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"색인 설정 파일을 못 읽음({path}): {e}") from e
    return normalize(conf)


def index_id(conf):
    """정규화한 설정의 표준 JSON → sha256 앞 8자. 코드 지문은 넣지 않음(스키마 이름 = 주소라 코드 변경마다 바뀌면 안 됨)."""
    return hashlib.sha256(_canon(normalize(conf)).encode("utf-8")).hexdigest()[:8]


def pg_schema(iid, base=None):
    """기본 스키마(PG_SCHEMA, 기본 ai — 검증대 ai_test) + '_' + index_id → 운영·검증대 구분이 그대로 유지됨."""
    s = f"{base or cfg().connections.pg.db_schema or 'ai'}_{check_id(iid)}"
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", s):
        raise ValueError(f"PG 스키마 이름이 잘못됨: {s}")
    return s


def env_for(conf, base=None):
    """설정 → bundle.py에 줄 env(청크 크기·겹침·api 모델 — 덮기 파일, S7e2). 설정에 없는 값은 비움(기본값) — 바깥 설정 값이 색인에 섞이면
    같은 id가 다른 색인이 됨."""
    c = normalize(conf)
    names = {ek: None if c[k] is None else str(c[k]) for k, ek in (("chunk_size", "CHUNK_SIZE"), ("overlap", "CHUNK_OVERLAP"))}
    if c["embed"] == "api":
        names["EMBED_MODEL"] = c["embed_model"]
    return settings_env(base, **names)


def inputs(rep_dir, stack_bytes, env=None):
    """재빌드 판정용 입력 지문(index_id와 별개 — id는 설정만, 이건 '같은 설정이라도 다시 지어야 하나'):
    _rep/index.json · 용어 사전 · 고객 명부 · 엔진 구성(stack_bytes = stackcfg.snapshot_bytes — 옛 사본 파일과 같은 바이트라 지문도 같음,
    pl-32) · common 지문 · 구조화 코드 지문(modules/structure)."""
    from common import FINGERPRINT
    from common.core.artifacts import code_fp

    def fp(p):
        p = Path(p)
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else "none"

    out = {
        "rep": fp(Path(rep_dir) / "index.json"),
        "glossary": glossary_fp(env),
        "roster": roster_fp(env),
        "stack": hashlib.sha256(stack_bytes).hexdigest()[:16] if stack_bytes else "none",
        "common": FINGERPRINT,
        "code": code_fp("s"),
    }
    aliases = client_aliases()
    if (
        aliases
    ):  # VS8b R-3 — 고객 별칭은 terms.py가 git 파일에서 읽어 사본(stack)에 안 듦. 지금 파일엔 없어 칸을 안 만든다(지금 색인 지문 그대로)
        out["aliases"] = hashlib.sha256(json.dumps(aliases, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return out


def client_aliases():
    """terms.py(인계 파일)가 읽는 고객 별칭 — git 엔진 구성 파일(resources/config/pipeline_stack.json)의 client_aliases(없으면 빈 사전)."""
    from common.core.paths import RES_ROOT

    p = RES_ROOT / "config" / "pipeline_stack.json"
    try:  # terms._aliases와 같게 — 읽기·형식 오류는 빈 사전(색인 판정이 멈추지 않게, 리뷰 S9)
        v = json.loads(p.read_text(encoding="utf-8")).get("client_aliases") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    return v if isinstance(v, dict) else {}
