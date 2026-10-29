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
    "parse_light": "docker exec data-pipeline-parse bash -c 'cd /app && echo [envcheck] gate=9 채널=light; RUN_DOCS_DOC=/app/output/docflow/7 FIG_OCR_BUDGET=0 PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.cli --set PIPE_OUT_ROOT=/app/output/docflow/7 --set DOC_DIR_PREPARED=/app/output/docflow/7/prepared --set PARSE_IMAGES_ROOT=/app/output/docflow/7/parse/_images --set PARSE_RAW_ROOT=/app/output/docflow/7/parse --set VLM_GLOBAL_CONCURRENCY=8 --set VLM_CONCURRENCY=8 --set FIGURES_VLM_PARALLEL=8 --set VLM_FIGURES_MAX=10 --set PARSE_POST=supsub,charts,figures,context,attachments --set OCR_DPI=120 --set RAPIDOCR_PAGE_WORKERS=2 --set OCR_THREADS=1 --set PIPE_PROCS=4 --set SOURCE_WARM=/app/output/_warm --set SOURCE_FETCH_WORKERS=2 --set PARSE_REP_SELECT=first --set PARSE_MERGE_PAGES=1 --set FUSE_REREAD_MAX=3 --set FUSE_REREAD_DPI=120 --set PARSE_FUSE_REREAD_P3=0 --set PARSE_QA_LIGHT=1 --set CPU_MAX_LOAD=9 parse --source rdb:csv:/app/output/docflow/7/batch.csv'",
    "parse_vlm_scan": "docker exec data-pipeline-parse bash -c 'cd /app && echo [envcheck] gate=1.3 채널=vlm; RUN_DOCS_DOC=/app/output/docflow/9 FIG_OCR_BUDGET=0 PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.cli --set PIPE_OUT_ROOT=/app/output/docflow/9 --set DOC_DIR_PREPARED=/app/output/docflow/9/prepared --set PARSE_IMAGES_ROOT=/app/output/docflow/9/parse/_images --set PARSE_RAW_ROOT=/app/output/docflow/9/parse --set VLM_GLOBAL_CONCURRENCY=8 --set VLM_CONCURRENCY=8 --set FIGURES_VLM_PARALLEL=8 --set VLM_FIGURES_MAX=10 --set PARSE_POST=supsub,charts,figures,context,attachments --set OCR_DPI=120 --set RAPIDOCR_PAGE_WORKERS=2 --set OCR_THREADS=1 --set PIPE_PROCS=4 --set SOURCE_WARM=/app/output/_warm --set SOURCE_FETCH_WORKERS=2 --set PARSE_REP_SELECT=first --set PARSE_MERGE_PAGES=1 --set FUSE_REREAD_MAX=3 --set FUSE_REREAD_DPI=120 --set PARSE_FUSE_REREAD_P3=0 --set PARSE_QA_LIGHT=1 --set VLM_GLOBAL_CONCURRENCY=6 --set VLM_CONCURRENCY=6 --set FIGURES_VLM_PARALLEL=6 --set PARSE_POST=supsub,charts,figures,context,attachments,vlm_page --set VLM_PAGE_MAX= --set VLM_PAGE_SLOW=45 --set PREPARE_ROTATE=0 --set CPU_MAX_LOAD=1.3 parse --source rdb:csv:/app/output/docflow/9/batch.csv --engines anydoc,docx2python,html_stdlib,hwpx,kreuzberg,markitdown,mhtml,msg_extract,office,plaintext,pymupdf,pymupdf4llm,qwen_vlm'",
    "struct": "docker exec data-pipeline-structure bash -c 'cd /app && SERVICE_MASTER_CSV=/app/config/service_master.csv DIVISION_MASTER_CSV=/app/config/division_master.csv PROD_MASTER_CSV=/app/config/prod_master.csv PYTHONPATH=/app/deploy S=$(python -m pipeline.stackcfg --path /app/output/docflow/9) && python -m pipeline.transform.structure.build_bundle --set EMBED_CONCURRENCY=6 --set EMBED_BATCH=32 --set BM25_THREADS=3 --set FILE_META_PATH=/app/output/file_meta_new.jsonl --parse-dir /app/output/docflow/9/parse --stack \"$S\" --out /app/output/docflow/9/bundle && python -m pipeline.load.pgvector_load --set EMBED_CONCURRENCY=6 --set EMBED_BATCH=32 --set BM25_THREADS=3 --set FILE_META_PATH=/app/output/file_meta_new.jsonl load --bundle /app/output/docflow/9/bundle >> /app/output/docflow/9/structure.log 2>&1'",
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
    안 읽음). env로 남는 것은 라이브러리(PYTHON*)·읽는 코드 없는 이름·문서 표지(RUN_DOCS_DOC)·셸 변수 S뿐."""
    known = setarg._fields()
    allowed = {
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONPYCACHEPREFIX",
        RD.DOC_MARK,
        "S",
        "FIG_OCR_BUDGET",
        "SERVICE_MASTER_CSV",
        "DIVISION_MASTER_CSV",
        "PROD_MASTER_CSV",
    }
    for name, cmd in _built().items():
        inner = _inner(cmd)
        env_words = set(re.findall(r"(?:^|[\s;&(])([A-Z][A-Z0-9_]+)=", re.sub(r"--set [^ ']+", "", inner)))
        assert env_words <= allowed, (name, sorted(env_words - allowed))
        assert not (env_words - {"S"}) & set(known), (name, sorted((env_words - {"S"}) & set(known)))


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
