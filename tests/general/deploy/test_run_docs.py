"""호스트 flow 러너 run_docs.py가 만드는 컨테이너 명령 줄 고정(S9 Step A — VS8b U-1, 사용자 10-28 `--set`).
run_docs.py는 로컬에서 실행하지 않는다(CLAUDE.md 3절) — 이 시험은 명령 줄을 만드는 함수만 부른다(설정 파일·docker·운영 접속 없음).
PC 일반 시험: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/general`(S9 — tests/general/deploy로 옮김)."""

import importlib.util
import re
import shlex
from pathlib import Path

from common.config import setarg

ROOT = Path(__file__).resolve().parents[3]
INPROCESS = True  # 상태를 바꾸지 않는 시험 — pytest가 함수마다 그대로 모음(tests/conftest.py)


def _load():
    spec = importlib.util.spec_from_file_location("run_docs_under_test", ROOT / "deploy" / "host" / "scripts" / "run_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 모듈 맨 위는 정의만(configure()·docker 호출 없음)
    return mod


RD = _load()

GOLDEN = {
    "warm": "docker exec data-pipeline-parse bash -c 'mkdir -p /app/output/_warm && cd /app && PYTHONPATH=/app/deploy python -m pipeline.extract.source --set SOURCE_WARM=/app/output/_warm warm --csv /app/output/docflow/9/batch.csv'",
    "parse_light": "docker exec data-pipeline-parse bash -c 'cd /app && echo [envcheck] gate=9 채널=light; RUN_DOCS_DOC=/app/output/docflow/7 PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.cli --set PIPE_OUT_ROOT=/app/output/docflow/7 --set DOC_DIR_PREPARED=/app/output/docflow/7/prepared --set PARSE_IMAGES_ROOT=/app/output/docflow/7/parse/_images --set PARSE_RAW_ROOT=/app/output/docflow/7/parse --set VLM_GLOBAL_CONCURRENCY=8 --set VLM_CONCURRENCY=8 --set FIGURES_VLM_PARALLEL=8 --set VLM_FIGURES_MAX=10 --set PARSE_POST=supsub,charts,figures,context,attachments --set OCR_DPI=120 --set RAPIDOCR_PAGE_WORKERS=2 --set OCR_THREADS=1 --set PIPE_PROCS=4 --set SOURCE_WARM=/app/output/_warm --set SOURCE_FETCH_WORKERS=2 --set PARSE_REP_SELECT=first --set PARSE_MERGE_PAGES=1 --set FUSE_REREAD_MAX=3 --set FUSE_REREAD_DPI=120 --set PARSE_QA_LIGHT=1 --set CPU_MAX_LOAD=9 parse --source rdb:csv:/app/output/docflow/7/batch.csv'",
    "parse_vlm_scan": "docker exec data-pipeline-parse bash -c 'cd /app && echo [envcheck] gate=1.3 채널=vlm; RUN_DOCS_DOC=/app/output/docflow/9 PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.cli --set PIPE_OUT_ROOT=/app/output/docflow/9 --set DOC_DIR_PREPARED=/app/output/docflow/9/prepared --set PARSE_IMAGES_ROOT=/app/output/docflow/9/parse/_images --set PARSE_RAW_ROOT=/app/output/docflow/9/parse --set VLM_GLOBAL_CONCURRENCY=8 --set VLM_CONCURRENCY=8 --set FIGURES_VLM_PARALLEL=8 --set VLM_FIGURES_MAX=10 --set PARSE_POST=supsub,charts,figures,context,attachments --set OCR_DPI=120 --set RAPIDOCR_PAGE_WORKERS=2 --set OCR_THREADS=1 --set PIPE_PROCS=4 --set SOURCE_WARM=/app/output/_warm --set SOURCE_FETCH_WORKERS=2 --set PARSE_REP_SELECT=first --set PARSE_MERGE_PAGES=1 --set FUSE_REREAD_MAX=3 --set FUSE_REREAD_DPI=120 --set PARSE_QA_LIGHT=1 --set VLM_GLOBAL_CONCURRENCY=6 --set VLM_CONCURRENCY=6 --set FIGURES_VLM_PARALLEL=6 --set PARSE_POST=supsub,charts,figures,context,attachments,vlm_page --set VLM_PAGE_MAX= --set VLM_PAGE_SLOW=45 --set PREPARE_ROTATE=0 --set CPU_MAX_LOAD=1.3 parse --source rdb:csv:/app/output/docflow/9/batch.csv --engines anydoc,docx2python,html_stdlib,hwpx,kreuzberg,markitdown,mhtml,msg_extract,office,plaintext,pymupdf,pymupdf4llm,qwen_vlm'",
    "struct": "docker exec data-pipeline-structure bash -c 'cd /app && PYTHONPATH=/app/deploy python -m pipeline.transform.structure.build_bundle --set EMBED_CONCURRENCY=6 --set EMBED_BATCH=32 --set BM25_THREADS=3 --set FILE_META_PATH=/app/output/file_meta_new.jsonl --parse-dir /app/output/docflow/9/parse --out /app/output/docflow/9/bundle && python -m pipeline.load.pgvector_load --set EMBED_CONCURRENCY=6 --set EMBED_BATCH=32 --set BM25_THREADS=3 --set FILE_META_PATH=/app/output/file_meta_new.jsonl load --bundle /app/output/docflow/9/bundle >> /app/output/docflow/9/structure.log 2>&1'",
    "publish": "docker exec data-pipeline-parse bash -c 'cd /app && PYTHONPATH=/app/deploy python -m pipeline.load.publish_parse_result --set PM_BUCKET_SKIP_OVERLAP_CHECK=1 --out /app/output/docflow/9 --source-system FileStorageMap --apply >> /app/output/docflow/9/publish.log 2>&1'",
    "sweep": "docker exec data-pipeline-parse bash -c \"for p in /proc/[0-9]*; do grep -aqzx 'RUN_DOCS_DOC=/app/output/docflow/9' \\$p/environ 2>/dev/null && kill \\${p##*/} 2>/dev/null; done\"",
}


def _built():
    return {
        "warm": RD.warm_cmd(9),
        "parse_light": RD.parse_cmd(7, "light", False, "9"),
        "parse_vlm_scan": RD.parse_cmd(9, "vlm", True, "1.3"),
        "struct": RD.struct_cmd(9),
        "publish": RD.publish_cmd(9),
        "sweep": RD.sweep_cmd(9),
    }


def test_command_lines_fixed():
    """명령 글자가 고정값과 같다 — 바꿀 때는 이 표도 같은 커밋에서(서버 운영 명령이 바뀜)."""
    assert _built() == GOLDEN


def _inner(cmd):
    """docker exec <컨테이너> bash -c '<안>'의 <안>."""
    return shlex.split(cmd)[-1]


def test_settings_only_via_set():
    """컨테이너 안 python에 설정 칸 이름을 env(`X=값 python`·`X=값 … && python`)로 주지 않는다 — 모두 --set(VS8b U-1: S7e2부터 env의 옛 이름은
    안 읽음). env로 남는 것은 라이브러리(PYTHON*)·문서 표지(RUN_DOCS_DOC)뿐."""
    known = setarg._fields()
    allowed = {
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONPYCACHEPREFIX",
        RD.DOC_MARK,
    }
    for name, cmd in _built().items():
        inner = _inner(cmd)
        env_words = set(re.findall(r"(?:^|[\s;&(])([A-Z][A-Z0-9_]+)=", re.sub(r"--set [^ ']+", "", inner)))
        assert env_words <= allowed, (name, sorted(env_words - allowed))
        assert not env_words & set(known), (name, sorted(env_words & set(known)))


def test_set_names_accepted():
    """--set으로 주는 이름은 모두 설정 칸(호스트·비밀 칸 아님) — setarg.check가 거부하지 않는다."""
    for name, cmd in _built().items():
        names, _ = setarg.split(shlex.split(_inner(cmd)))
        assert not setarg.check(names), (name, setarg.check(names))


def test_doc_folder_values():
    """문서별 파싱은 결과·준비·이미지·원문 폴더를 그 문서 폴더로, 채널 값은 뒤 --set이 이긴다(옛 bash env 순서와 같음)."""
    names, rest = setarg.split(shlex.split(_inner(GOLDEN["parse_vlm_scan"])))
    inside = "/app/output/docflow/9"
    assert names["PIPE_OUT_ROOT"] == inside and names["DOC_DIR_PREPARED"] == f"{inside}/prepared"
    assert names["PARSE_RAW_ROOT"] == f"{inside}/parse" and names["PARSE_IMAGES_ROOT"] == f"{inside}/parse/_images"
    assert names["VLM_CONCURRENCY"] == "6" and names["VLM_PAGE_MAX"] == "" and names["PREPARE_ROTATE"] == "0"
    assert names["PARSE_POST"].endswith(",vlm_page") and names["CPU_MAX_LOAD"] == "1.3"
    assert rest[rest.index("parse") + 1 : rest.index("parse") + 3] == ["--source", f"rdb:csv:{inside}/batch.csv"]
    light, _ = setarg.split(shlex.split(_inner(GOLDEN["parse_light"])))
    assert light["VLM_CONCURRENCY"] == "8" and "VLM_PAGE_MAX" not in light and light["CPU_MAX_LOAD"] == "9"


def test_sweep_marker_matches_parse():
    """고아 정리가 찾는 표지 env가 파싱 명령이 주는 표지와 같다(옛 PIPE_OUT_ROOT env 자리)."""
    mark = f"{RD.DOC_MARK}=/app/output/docflow/9"
    assert mark in _inner(GOLDEN["parse_vlm_scan"]) and mark in GOLDEN["sweep"]


# ── 레인·대기열 정책(사용자 10-29 — docs/prd/runner.md rn-01·rn-02) ──
# (자기 레인, 공유 워커?, 대기 길이 light/medium/vlm, 진행 중 vlm, vlm 상한) → 꺼낼 레인
PICK_CASES = [
    ("light", False, (2, 5, 5), 0, 2, "light"),  # 자기 레인 먼저
    ("light", False, (0, 5, 5), 0, 2, None),  # 전담 — 다른 레인이 차 있어도 안 가져옴
    ("light", True, (0, 5, 3), 0, 2, "medium"),  # 공유 — 비었으면 가장 긴 다른 레인
    ("light", True, (1, 5, 9), 0, 2, "light"),  # 공유도 자기 레인이 있으면 steal 안 함
    ("medium", True, (0, 0, 4), 2, 2, None),  # vlm 상한이면 vlm 문서 건너뜀
    ("medium", True, (1, 0, 4), 2, 2, "light"),  # 상한일 때 다음 레인으로
    ("vlm", False, (0, 0, 4), 2, 2, None),  # 전담 vlm도 상한을 지킴
    ("vlm", False, (0, 0, 4), 1, 2, "vlm"),
]


def test_pick_lane_table():
    for own, shared, (nl, nm, nv), vlm_run, cap, want in PICK_CASES:
        queues = {"light": [0] * nl, "medium": [0] * nm, "vlm": [0] * nv}
        got = RD.pick_lane(own, shared, queues, {"light": 0, "medium": 0, "vlm": vlm_run}, cap)
        assert got == want, (own, shared, (nl, nm, nv), vlm_run, got, want)


def test_policy_from_settings():
    vals, probs = RD.run_docs_policy({})
    assert vals == RD.RUN_DOCS_DEFAULTS and probs == []
    doc = {"pipeline": {"host": {"run_docs": {"warm": "30", "struct_backlog": "0", "vlm_shared": "", "light_dedicated": "2"}}}}
    vals, probs = RD.run_docs_policy(doc)  # BaseLoader — 글자로 들어옴
    assert (vals["warm"], vals["struct_backlog"], vals["vlm_shared"], vals["light_dedicated"]) == (30, 0, 1, 2) and probs == []
    _, probs = RD.run_docs_policy({"pipeline": {"host": {"run_docs": {"warm": "-1", "vlm_cap": "x"}}}})
    assert len(probs) == 2 and all("형식 오류" in p for p in probs), probs
    no_shared = {f"{c}_shared": "0" for c in RD.LANES}
    # 배치가 끝나지 않는 설정(PR #7 리뷰) → 문제 있음 / 경계 바로 안쪽 → 문제 없음
    for sec, bad in [
        ({f"{c}_{k}": "0" for c in RD.LANES for k in ("dedicated", "shared")}, True),
        ({"vlm_cap": "0"}, True),
        ({"warm": "0"}, True),
        ({**no_shared, "vlm_dedicated": "0"}, True),
        ({**no_shared}, False),
        ({"vlm_dedicated": "0"}, False),  # 공유 워커가 vlm을 가져감
        ({"vlm_cap": "1", "warm": "1"}, False),
    ]:
        probs = RD.run_docs_policy({"pipeline": {"host": {"run_docs": sec}}})[1]
        assert bool(probs) == bad, (sec, probs)


def test_defaults_match_settings_model():
    """러너 기본값 = 설정 모델 기본값(호스트 python은 모델을 import하지 않아 두 곳에 있음)."""
    from pipeline.config import PipelineHostRunDocs

    assert RD.RUN_DOCS_DEFAULTS == {k: f.default for k, f in PipelineHostRunDocs.model_fields.items()}


def test_stack_version_passed_once():
    """엔진 구성 판 번호(main()이 시작 때 한 번 — STACK_VER)가 파싱(--set STACK_VERSION)·구조화(--stack-version)에 같이 간다(pl-32 — 사본 파일 없음).
    빈 글자(PC 파일)면 둘 다 인자 없음(위 고정 명령)."""
    keep = RD.STACK_VER
    try:
        RD.STACK_VER = "7"
        assert RD.parse_cmd(7, "light", False, "9").endswith(
            "--set CPU_MAX_LOAD=9 --set STACK_VERSION=7 parse --source rdb:csv:/app/output/docflow/7/batch.csv'"
        )
        assert " --parse-dir /app/output/docflow/9/parse --stack-version 7 --out " in RD.struct_cmd(9)
        assert "stackcfg" not in RD.struct_cmd(9)
    finally:
        RD.STACK_VER = keep
