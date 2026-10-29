"""AD41 — 색인 설정 1개 → index_id(설정 지문) · 결과 폴더 · PG 스키마. 빌더(cli/index.py)와 Data Retrieval Agent(검색 MCP)가 같은 규칙.
설계: docs/architecture.md §8. 설정 없음 = 기본 색인(output/edw/bundle · PG_SCHEMA) — 이 파일을 안 거침.
10-14 함수별 분리(사용자) — pipeline(옛 data_parsing·data_structure)에서만 쓰는 normalize·load·index_id·env_for·inputs·pg_schema는
pipeline/load/index_cfg.py로, 검색 MCP에서만 쓰는 input_drift는 mcp_server/services/search/index_cfg.py로
옮김(로직 바이트 동일) — check_id·root·glossary_fp·roster_fp·bundle_dir·info·list_ids는 두 이미지(+MCP) 모두
그대로 부르므로 여기(공용)에 남는다."""

import hashlib
import json
import re
from pathlib import Path

from common.core.paths import APP_ROOT

DEV = APP_ROOT
ID_RE = re.compile(r"[0-9a-f]{8}")


def check_id(iid):
    if not isinstance(iid, str) or not ID_RE.fullmatch(iid):
        raise ValueError(f"index_id 형식이 아님(소문자 16진 8자): {iid!r}")
    return iid


def root():
    from common.config.settings import cfg  # S7b — 설정 객체(호출 때마다 읽음)

    return Path(cfg().paths.index_root or (DEV / "output" / "index"))


def bundle_dir(iid):
    return root() / check_id(iid) / "bundle"


def _dev_path(p):
    """env 경로 — 상대 경로는 dev/ 기준(build_bundle.py·MCP가 cwd=dev로 돎)."""
    p = Path(p)
    return p if p.is_absolute() else DEV / p


def glossary_fp(env=None):
    """용어 사전(GLOSSARY_DIR) 지문 — *.csv 이름+내용 sha256 8자, 없으면 'none'(stack_matrix.terms_fp와 같은 규칙)."""
    from common.config.settings import cfg  # S7b — 인자 env(사전)를 받으면 호출자가 넘긴 사전을 읽고, 없을 때만 설정 객체

    d = cfg().paths.glossary_dir if env is None else env.get("GLOSSARY_DIR")
    if not d or not _dev_path(d).is_dir():
        return "none"
    h = hashlib.sha256()
    for f in sorted(_dev_path(d).glob("*.csv")):
        h.update(f.name.encode("utf-8") + f.read_bytes())
    return h.hexdigest()[:8]


def roster_fp(env=None):
    """고객 명부(CLIENT_ROSTER 파일) 지문 — 내용 sha256 8자, 없으면 'none'."""
    from common.config.settings import cfg  # S7b — 위와 같음

    f = cfg().paths.client_roster if env is None else env.get("CLIENT_ROSTER")
    if not f or not _dev_path(f).is_file():
        return "none"
    return hashlib.sha256(_dev_path(f).read_bytes()).hexdigest()[:8]


def info(iid):
    """완료된 색인의 index.json(완료 표시) — 없으면 None."""
    p = root() / check_id(iid) / "index.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return d if d.get("index_id") == iid else None


def list_ids():
    r = root()
    return sorted(p.parent.name for p in r.glob("*/index.json") if ID_RE.fullmatch(p.parent.name)) if r.exists() else []
