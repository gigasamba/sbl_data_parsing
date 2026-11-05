#!/usr/bin/env python3
"""실험 저장소 공통 계약 — 층별 코드 지문·열쇠·`_manifest.json`·낡음 판정.
parse·structure·load·search 코드는 import하지 않는다(계약 코드는 모듈 경계 밖 — 파이프라인 쪽이 이 함수들만 가져다 씀).
"같은 입력 + 같은 코드 지문 = 같은 열쇠" — 층 코드가 바뀌면 지문이 바뀌어 저장본이 자동으로 낡음이 된다.
여기는 2개 이상 이미지가 쓰는 계약만 둔다(파싱 전용 함수는 pipeline/shared·pipeline/transform/parse).
"""

import hashlib
import json
import subprocess
import time
from pathlib import Path

from common.core.paths import DEPLOY_ROOT

DEV = DEPLOY_ROOT  # 층 글롭의 기준 — 패키지들이 놓인 폴더
# 층 코드는 형제 패키지에 있다(기준을 이 파일 폴더로 두면 글롭이 빈 집합 = 늘 같은 빈 해시)

# 층별 소스 파일(deploy/ 기준). common은 층 파일이 실제로 import하는 모듈만 더한다(_common_deps).
# 층 파일이 import하는 pipeline 파일은 그 층 목록에 적는다(엔진 코드는 p0 — tests/server/common/test_code_fp.py가 확인).
LAYER_CODE = {
    # 엔진 폴더 전부 + 일괄 실행기 + 엔진이 쓰는 공용 파일. 엔진 하나의 열쇠는 parse_engines.engine_code_fp가 따로 맡는다.
    "p0": [
        "pipeline/transform/parse/engines/**/*.py",
        "pipeline/transform/parse/parse_engines.py",
        "pipeline/config.py",
        "pipeline/shared/raw_cache.py",
        "pipeline/shared/env_error.py",
        "pipeline/shared/pdf_kind.py",
        "pipeline/shared/vlmcall.py",
    ],
    # 대표 결과(represent·figures)를 만드는 코드 — 원문 파싱 관리(받기·준비·중복)는 빼서 그 코드를 고쳐도 p1이 바뀌지 않게.
    "p1": [
        "pipeline/config.py",
        "pipeline/transform/parse/parse_engines.py",  # 첨부 다시 파싱(_isolated)·VLM 엔진 목록
        "pipeline/transform/parse/engines/registry.py",  # p1 파일이 import하는 엔진 파일
        "pipeline/transform/parse/engines/mhtml/parser.py",
        "pipeline/transform/parse/engines/rapidocr/parser.py",
        "pipeline/transform/parse/engines/_common/*.py",
        "pipeline/shared/raw_cache.py",
        "pipeline/shared/env_error.py",
        "pipeline/shared/pdf_kind.py",
        "pipeline/shared/ext_groups.py",
        "pipeline/shared/vlmcall.py",
    ]
    + [
        f"pipeline/transform/represent/{n}.py"
        for n in (
            "build_rep",
            "crosscheck",
            "parse_scoring",
            "mail_attachments",
            "figure_context",
            "fragment_vote",
            "superscripts",
            "table_inline",
            "table_standard",
            "text_normalize",
        )
    ]
    + [
        f"pipeline/transform/figures/{n}.py"
        for n in (
            "chart_values",
            "diagram_edges",
            "figure_extract",
            "nested_figures",
            "overlay_groups",
            "pptx_edges",
            "pptx_render",
            "shape_detect",
            "vector_regions",
            "scan_page_vlm",
        )
    ],
    # 구조화 — transform/structure/ 글로브를 쓰지 않고 파일 목록으로(오프라인 도구는 NOT_LAYER).
    "s": [
        "pipeline/config.py",
        "pipeline/transform/structure/__init__.py",
        "pipeline/transform/structure/gold_bundle.py",
        "pipeline/transform/structure/chunking.py",
        "pipeline/transform/structure/client_roster.py",
    ],
    "r": [
        "mcp_server/config.py",
        "mcp_server/services/search/retriever.py",
        "mcp_server/services/search/rank_rules.py",
        "mcp_server/services/search/pgsearch.py",
        "mcp_server/services/search/query_expand.py",
        "mcp_server/services/search/question_type.py",
        "mcp_server/services/search/bm25_weights.py",
    ],
}

# 층에 넣지 않는 transform 파일 — 결과를 만들지 않는 오프라인 도구(사람이 따로 돌림). 새 transform 파일은 위 층 목록이나 여기 둘 중 하나에
# 적는다(tests/server/common/test_code_fp.py가 빠진 파일을 잡음 — 결과를 바꾸는 파일이 빠지면 낡은 결과를 다시 쓴다).
NOT_LAYER = (
    "pipeline/transform/parse/__init__.py",
    "pipeline/transform/parse/engine_check.py",  # 시작 때 엔진 구성 검사(결과를 만들지 않음)
    "pipeline/transform/represent/__init__.py",
    "pipeline/transform/structure/__init__.py",  # 빈 파일 — s 층 목록에는 따로 적어 둠
    "pipeline/transform/structure/roster_from_edw.py",
    "pipeline/transform/structure/glossary_suggest.py",
    "pipeline/transform/structure/draft_terms.py",  # 묶음 밖 용어 초안 도구
)
# 지문 계산에서 따라가지 않는 common 파일·폴더(결과와 무관 — 기록·DB 연결·표 정의·설정 도구). 따라가면 로그 → DB 기록 → 표 정의로
# 이어져 DB 표 칸 하나만 고쳐도 모든 층 지문이 바뀐다. 설정 모델(config/settings.py)은 기본값이 결과를 바꿀 수 있어, store/pg.py는 검색(r)이 벡터 글자(vec)를 만들어 그대로 둔다.
CODE_FP_SKIP = (
    "core/artifacts.py",
    "core/jsonlog.py",
    "core/runlog.py",
    "core/span.py",
    "core/resources.py",
    "store/logsink.py",
    "store/pg_standin.py",
    "store/mssql.py",
    "store/objectstore.py",
    "store/parsing_meta_db.py",
    "store/db/",
    "config/boot.py",
    "config/export.py",
    "config/keyscan.py",
    "config/overrides.py",
    "config/sample.py",
    "config/setarg.py",
    "config/show.py",
)


def _skipped(rel):
    return any(rel == s or (s.endswith("/") and rel.startswith(s)) for s in CODE_FP_SKIP)


def _common_deps(files, base):
    """층 파일들이 (직접·간접) import하는 common 모듈 파일만 — ast로 `from common import x`·`from common.x import y`·
    `import common.x`를 찾는다. `from common.ai.llm import profile`처럼 2단 이상도 오므로, 점으로
    이어진 이름을 뒤에서부터 줄여가며 실제 파일(.py)이나 패키지(__init__.py)를 찾는다(마지막 조각이 모듈이
    아니라 그 안의 심볼 이름일 수 있어서 — from pkg.mod import symbol).
    common 전체가 아니라 실제로 쓰는 것만 넣어, 한 층 전용 모듈을 고쳐도 다른 층 지문은 그대로다."""
    import ast

    PREFIX = "common"
    root = base / "common"

    def _resolve(dotted):
        """점으로 이어진 이름을 뒤에서부터 줄여가며 찾되, 중간 폴더까지 폴더 목록으로 대소문자를 정확히 맞춰
        내려간다 — `.is_file()`만 쓰면 Windows(대소문자 구분 없음)에서 `from common import CONTRACT`
        (__init__.py의 상수)가 `contract/` 패키지로 잘못 걸린다(Linux는 원래부터 대소문자 구분이라 영향 없음)."""
        parts = dotted.split(".")
        for end in range(len(parts), 0, -1):
            cur = root
            for part in parts[: end - 1]:
                try:
                    nxt = next((c for c in cur.iterdir() if c.is_dir() and c.name == part), None)
                except OSError:
                    nxt = None
                if nxt is None:
                    cur = None
                    break
                cur = nxt
            if cur is None:
                continue
            try:
                children = {c.name: c for c in cur.iterdir()}
            except OSError:
                children = {}
            leaf = parts[end - 1]
            f = children.get(leaf + ".py")
            if f and f.is_file():
                return f
            d = children.get(leaf)
            if d and d.is_dir() and (d / "__init__.py").is_file():
                return d / "__init__.py"
        return None

    seen, todo = set(), list(files)
    while todo:
        f = todo.pop()
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        candidates = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and (n.module == PREFIX or n.module.startswith(PREFIX + ".")):
                tail = "" if n.module == PREFIX else n.module[len(PREFIX) + 1 :]
                for a in n.names:
                    candidates.add(f"{tail}.{a.name}" if tail else a.name)
                if tail:
                    candidates.add(tail)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.name == PREFIX or a.name.startswith(PREFIX + "."):
                        tail = "" if a.name == PREFIX else a.name[len(PREFIX) + 1 :]
                        if tail:
                            candidates.add(tail)
        for dotted in candidates:
            p = _resolve(dotted)
            if p and p not in seen and not _skipped(p.relative_to(root).as_posix()):
                seen.add(p)
                todo.append(p)
    return seen


def code_fp(layer, root=None):
    """그 층을 만드는 소스 파일(글로브) + 그 파일들이 실제로 import하는 common 모듈의 정렬된 내용 → sha256[:12].
    root(기본 DEV) — selftest가 임시 복사본으로 건드려 보게 받을 수 있다(실제 코드 수정 없이)."""
    base = Path(root) if root else DEV
    own = {p for g in LAYER_CODE[layer] for p in base.glob(g) if p.is_file()}
    files = sorted(own | _common_deps(own, base))
    h = hashlib.sha256()
    for p in files:  # 경로도 해시에 넣음 — 파일 추가/삭제도 지문을 바꾸게
        h.update(p.relative_to(base).as_posix().encode("utf-8"))
        # 줄바꿈 통일 — 작업 사본의 CRLF/LF 차이(편집기·git 체크아웃)로 지문이 흔들리지 않게
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]


def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def key(layer, parts, root=None):
    """열쇠 = sha256(parts의 표준 JSON + 그 층 code_fp)[:16] — parts의 dict 순서는 안 탄다(sort_keys)."""
    payload = _canon(parts) + code_fp(layer, root)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _git_commit():
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=DEV, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or None if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def manifest(path, layer, parts, root=None):
    """저장본 폴더에 `_manifest.json`을 쓴다(parts·code_fp·git commit·생성 시각) — audit·is_stale이 이걸 읽는다."""
    d = Path(path)
    d.mkdir(parents=True, exist_ok=True)
    m = {
        "layer": layer,
        "parts": parts,
        "code_fp": code_fp(layer, root),
        "git_commit": _git_commit(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (d / "_manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    return m


def is_stale(dir, root=None):
    """→ (낡음?, 이유). manifest 없음 = 낡음(버전 미상 취급 — 설계 문서 "기존 output/parse는 provenance 없어 낡음 표시")."""
    d = Path(dir)
    f = d / "_manifest.json"
    if not f.exists():
        return True, "_manifest.json 없음"
    m = json.loads(f.read_text(encoding="utf-8"))
    cur = code_fp(m.get("layer"), root)
    if cur != m.get("code_fp"):
        return True, f"code_fp 바뀜({m.get('code_fp')} → {cur})"
    return False, ""


def sha8(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]
