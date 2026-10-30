#!/usr/bin/env python3
"""실험 저장소 공통 계약(docs/testing.md) — 층별 코드 지문·열쇠·`_manifest.json`·낡음 판정.
parse·structure·load·search(옛 modules/)는 import하지 않는다(계약 코드는 모듈 경계 밖 — 파싱 이식 쪽이 이 함수들만 가져다 씀).
"같은 입력 + 같은 코드 지문 = 같은 열쇠" — 층 코드가 바뀌면 지문이 바뀌어 저장본이 자동으로 낡음이 된다.
10-14 함수별 분리(사용자) — data-parsing 이미지에서만 쓰는 prompt_id·raw_engine_path·raw_vlm_path·engine_version·
purge_caches는 pipeline/shared/artifacts.py로 옮김(로직 바이트 동일) — 여기는 2개 이상 이미지가 쓰는 계약만.
"""

import hashlib
import json
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEV = HERE.parent.parent  # deploy/ — CT1(contract/ 한 단 더 깊음, HERE.parent=common_tools/ — S3부터 core/ 한 단, HERE.parent=common/) · 10-14 이미지별 폴더 분리 뒤
# 층 코드는 형제 패키지(engine-qa 10-14 BLOCKER 1: HERE로 두면 글롭이 빈 집합 = 늘 같은 빈 해시)

# 층별 소스 파일 glob(deploy/ 기준) — common은 그 층 파일이 실제로 import하는 모듈만 더함(_common_deps, 10-05).
# p0은 엔진마다 다름 — code_fp("p0:<engine>")로 호출(그 엔진 파서 폴더 + run_all.py만).
# 10-14 분리로 paths·structdb 등 공용 코드가 실제로 바뀌어 p1·s·r·a 지문은 한 번 바뀜(저장본 1회 재생성) — 인계 지문·엔진 지문은 legacy_names로 유지.
LAYER_CODE = {
    "p0": ["pipeline/extract/engines/{engine}/**/*.py", "pipeline/extract/run_all.py"],
    # 후보정(represent)이 실제로 쓰는 코드만 — 원문 파싱 관리(run_all·prepare·dedup·source·보고·진행)는 빼서 그 코드를 고쳐도 P1 이상이 다시 지어지지 않게(10-04).
    # ponytail: postprocess/attachments가 run_all._isolated를 씀 — 그 함수가 바뀌면 PARSE_POST 첨부 결과가 달라질 수 있으나 드묾(바뀌면 P1_LAYOUT 올림)
    # I2(data_etl 단계 폴더 — S4부터 pipeline/, 접두어만 바뀜) — 옛 postprocess/ 패키지(26개)가 represent/·figures/·shared/로 나뉘어 글로브 대신 파일 목록(옮기기 전과 같은 집합)
    "p1": [
        "pipeline/transform/represent/represent.py",
        "pipeline/transform/represent/crosscheck.py",
        "pipeline/transform/represent/parse_qa.py",
        "pipeline/shared/postprocess.py",
    ]
    + [
        f"pipeline/transform/represent/{n}.py"
        for n in (
            "attachments",
            "context",
            "fuse",
            "reread",
            "shadow",
            "supsub",
            "table_inline",
            "table_std",
            "trace",
        )
    ]
    + [
        f"pipeline/transform/figures/{n}.py"
        for n in (
            "chart_values",
            "charts",
            "diagram_edges",
            "figures",
            "mermaid",
            "nested",
            "overlay",
            "pptx_edges",
            "pptx_render",
            "shape_detect",
            "vector",
            "vgate",
            "vlm_page",
        )
    ],
    # 옛 structure/ 파일만 — load/와 한 폴더로 합쳐져 **면 적재 코드까지 들어감(I2 뒤에도 transform/structure/ 글로브를 쓰지 않음). 새 구조화 파일은 여기 추가.
    "s": [
        "pipeline/transform/structure/__init__.py",
        "pipeline/transform/structure/build_bundle.py",
        "pipeline/transform/structure/chunking.py",
        "pipeline/transform/structure/draft_terms.py",
        "pipeline/transform/structure/facts.py",
    ],
    "r": [
        "mcp_server/services/search/retriever.py",
        "mcp_server/services/search/local.py",
        "mcp_server/services/search/pgsearch.py",
    ],
    "a": [],  # S5(10-26, C-25 ① — 코디네이터 답 Q1 a) 빈 층: research.py는 S5a에 지움(D-025). 옛 stack_matrix(10-30 지움) answer 캐시 열쇠·audit이 층 a를 써서
    # 층 이름은 남김 — 빈 층 해시 e3b0c44298fc는 S5a 뒤 값 그대로라 answer 캐시 열쇠도 그대로
}


def _layer_globs(layer):
    if layer.startswith("p0:"):
        engine = layer.split(":", 1)[1]
        return [g.format(engine=engine) for g in LAYER_CODE["p0"]]
    return LAYER_CODE[layer]


def _common_deps(files, base):
    """층 파일들이 (직접·간접) import하는 common 모듈 파일만 — ast로 `from common import x`·
    `from common_tools.x import`·`import common_tools.x`(단계 4, 10-13 — 옛 `common`/`common.x`에서 옮김) ·
    S3(10-26) — 다시 `common`/`common.x`(common/{core,ai,store,check}) — 이름 글자만 바뀌고 찾는 방법은 그대로 ·
    CT1(10-16) — common_tools 하위가 역할 묶음(model/·store/·contract/·runtime/)으로 한 단 깊어져 `from
    common.ai import llm`·`from common.ai.llm import profile`처럼 2단 이상도 와서, 점으로
    이어진 이름을 뒤에서부터 줄여가며 실제 파일(.py)이나 패키지(__init__.py)를 찾는다(마지막 조각이 모듈이
    아니라 그 안의 심볼 이름일 수 있어서 — from pkg.mod import symbol).
    10-05: common/*.py 전부를 모든 층에 넣어 docmeta(구조화·검색 전용) 한 줄 수정에도 P1(VLM 후보정)까지 다시 지어야 했음 → 실제 쓰는 것만."""
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
            if p and p not in seen:
                seen.add(p)
                todo.append(p)
    return seen


def code_fp(layer, root=None):
    """그 층을 만드는 소스 파일(글로브) + 그 파일들이 실제로 import하는 common 모듈의 정렬된 내용 → sha256[:12].
    root(기본 DEV) — selftest가 임시 복사본으로 건드려 보게 받을 수 있다(실제 코드 수정 없이)."""
    base = Path(root) if root else DEV
    own = {p for g in _layer_globs(layer) for p in base.glob(g) if p.is_file()}
    files = sorted(own | _common_deps(own, base))
    h = hashlib.sha256()
    for p in files:  # 경로도 해시에 넣음 — 파일 추가/삭제도 지문을 바꾸게
        h.update(p.relative_to(base).as_posix().encode("utf-8"))
        # 10-13 — 줄바꿈 통일: 작업 사본이 CRLF/LF로 바뀌기만 해도(다른 세션 편집·git 체크아웃) 지문이 흔들려 P1을 못 찾았음
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
