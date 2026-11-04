"""후보정 설정 — 켠 후보정 기능(active_features)과 VLM 원본 캐시 루트(raw_root).

transform.represent.post 설정:
  없음/"all" = 전부(vlm_page·supsub·charts·figures·context·attachments — 스캔 쪽 VLM은 VLM_PAGE_MAX, 그림 VLM은
  VLM_FIGURES_MAX(기본 문서당 20)로 상한) · "none" = 꺼짐 · 콤마 목록("supsub,charts") = 그것만.
  "context"는 "figures" 없이는 효과 없음(그림 기록이 있어야 캡션·값 확인을 붙임).
"""

from pathlib import Path

from common.core.paths import APP_ROOT
from pipeline import config as pc

FEATURES = ("vlm_page", "supsub", "charts", "figures", "context", "attachments")


def raw_root():
    """P0 VLM 캐시 저장소 '루트'(= common.core.artifacts.raw_vlm_path/raw_engine_path의 store 인자 — 그 아래 raw/vlm/... 이 붙는다).
    PARSE_RAW_ROOT 기본 output/parse. 프로토타입 캐시를 가리킬 때는 `output/cache/hard_parse`(그 아래 raw/vlm/...가 이미 있음) — `.../raw`까지
    주는 실수를 하면 raw/vlm이 중첩돼 전부 캐시 미스가 나므로, 끝이 'raw'면 한 단계 올려 바로잡는다."""
    v = pc.cfg().paths.raw_root
    p = Path(v) if v else (APP_ROOT / "output" / "parse")
    return p.parent if p.name == "raw" else p


def active_features(config=None):
    """PARSE_POST 글자 → 켠 기능 집합(결정적 — 순서 섞이지 않게 set 아닌 frozenset도 괜찮지만 멤버십만 씀)."""
    if config is None:  # 없음 = "all", 빈 글자 = 끔
        v = pc.cfg().transform.represent.post
        config = "all" if v is None else v
    config = (config or "").strip()
    if config in ("", "none"):
        return frozenset()
    if config == "all":
        return frozenset(FEATURES)
    return frozenset(f.strip() for f in config.split(",") if f.strip())
