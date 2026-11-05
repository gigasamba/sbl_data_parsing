"""P0 원본 층 캐시 경로 — 저장소 루트(raw_root)·엔진 결과·VLM 응답 경로·지시문 id."""

from pathlib import Path

from common.core.artifacts import sha8
from common.core.paths import APP_ROOT
from pipeline import config as pc


def raw_root():
    """P0 VLM 캐시 저장소 '루트'(= common.core.artifacts.raw_vlm_path/raw_engine_path의 store 인자 — 그 아래 raw/vlm/... 이 붙는다).
    PARSE_RAW_ROOT 기본 output/parse. 프로토타입 캐시를 가리킬 때는 `output/cache/hard_parse`(그 아래 raw/vlm/...가 이미 있음) — `.../raw`까지
    주는 실수를 하면 raw/vlm이 중첩돼 전부 캐시 미스가 나므로, 끝이 'raw'면 한 단계 올려 바로잡는다."""
    v = pc.cfg().paths.raw_root
    p = Path(v) if v else (APP_ROOT / "output" / "parse")
    return p.parent if p.name == "raw" else p


def prompt_id(name, version, text):
    """지시문 id = name-version-sha8(지시문 글자) — 코드 이름이 같아도 버전·글자가 바뀌면 다른 id."""
    return f"{name}-{version}-{sha8(text)}"


def raw_engine_path(store, engine, version, content_sha):
    """P0 엔진 결과 경로 — raw/<engine>@<version>/<sha12>.json (src/tools/qa/eval_hard_parse.py RAW 패턴과 동일)."""
    return Path(store) / "raw" / f"{engine}@{version}" / f"{content_sha[:12]}.json"


def raw_vlm_path(store, model, name, version, prompt_text, image_sha):
    """P0 VLM 쪽 결과 경로 — raw/vlm/<model>/<prompt_id>/<image_sha12>.json."""
    return Path(store) / "raw" / "vlm" / model / prompt_id(name, version, prompt_text) / f"{image_sha[:12]}.json"
