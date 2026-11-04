"""후보정 패키지(W1~W3·W9·W11·W12·L1 이식) — 원본
src/tools/qa/eval_hard_parse.py(설정 A~F)를 운영 파싱에 반영. 한 기능 = 한 파일(docstring에 원본 함수 이름 적어 추적 가능하게).

PARSE_POST(환경변수) — represent.py가 읽는 후보정 설정:
  없음/"all" = 전부(F와 동급: vlm_page·supsub·charts·figures·context + attachments(W17, 메일 첨부 재귀 파싱) — 스캔 쪽 VLM은 VLM_PAGE_MAX, 그림 VLM은 VLM_FIGURES_MAX(기본 문서당 20)로 상한) · "none" = 꺼짐(이전 동작과 바이트 동일) ·
  콤마 목록("supsub,charts") = 그것만. "context"는 "figures" 없이는 효과 없음(그림 기록이 있어야 캡션·값 확인을 붙임).
"""

from pathlib import Path

from common.core.paths import APP_ROOT  # pipeline.shared.postprocess는 dev root가 이미 sys.path에 있어야만 reachable(상위가 bootstrap 완료)
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)

FEATURES = ("vlm_page", "supsub", "charts", "figures", "context", "attachments")


def raw_root():
    """P0 VLM 캐시 저장소 '루트'(= common.core.artifacts.raw_vlm_path/raw_engine_path의 store 인자 — 그 아래 raw/vlm/... 이 붙는다).
    PARSE_RAW_ROOT 기본 output/parse. 프로토타입 캐시를 가리킬 때는 `output/cache/hard_parse`(그 아래 raw/vlm/...가 이미 있음) — `.../raw`까지
    주는 실수를 하면 raw/vlm이 중첩돼 전부 캐시 미스가 나므로(실측 2026-10-03), 끝이 'raw'면 한 단계 올려 바로잡는다."""
    v = pc.cfg().paths.raw_root  # S7c — 설정 객체
    p = Path(v) if v else (APP_ROOT / "output" / "parse")
    return p.parent if p.name == "raw" else p


def active_features(config=None):
    """PARSE_POST 글자 → 켠 기능 집합(결정적 — 순서 섞이지 않게 set 아닌 frozenset도 괜찮지만 멤버십만 씀)."""
    if config is None:  # S7c — 설정 객체(글자 칸 — 쓴 글자 그대로): 없음 = "all", 빈 글자 = 끔(옛 get(X, "all")과 같음)
        v = pc.cfg().transform.represent.post
        config = "all" if v is None else v
    config = (config or "").strip()
    if config in ("", "none"):
        return frozenset()
    if config == "all":
        return frozenset(FEATURES)
    return frozenset(f.strip() for f in config.split(",") if f.strip())
