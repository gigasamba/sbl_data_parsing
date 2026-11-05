"""호스트 flow 러너 run_pipeline.py가 만드는 컨테이너 명령 줄 고정(설정 값은 `--set`으로).
run_pipeline.py는 로컬에서 실행하지 않는다(CLAUDE.md 3절) — 이 시험은 명령 줄을 만드는 함수만 부른다(설정 파일·docker·운영 접속 없음).
PC 일반 시험: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/general`."""

import argparse
import importlib.util
import re
import shlex
from unittest import mock

import yaml

from common.config import setarg
from common.core.paths import DEPLOY_ROOT

ROOT = DEPLOY_ROOT  # 저장소 루트(paths 상수)
INPROCESS = True  # 상태를 바꾸지 않는 시험 — pytest가 함수마다 그대로 모음(tests/conftest.py)


def _load():
    spec = importlib.util.spec_from_file_location("run_pipeline_under_test", ROOT / "deploy" / "host" / "scripts" / "run_pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 모듈 맨 위는 정의만(configure()·docker 호출 없음)
    return mod


RD = _load()

GOLDEN = {
    "staging": "docker exec data-pipeline bash -c 'umask 0002 && mkdir -p /app/output/_staging && cd /app && PYTHONPATH=/app/deploy PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.extract.candidate_ready --set SOURCE_STAGING=/app/output/_staging --set SOURCE_FETCH_WORKERS=2 stage --csv /app/output/_docflow/9/batch.csv --out /app/output/_docflow/9 --prepared /app/output/_docflow/9/prepared --no-scan-rotate'",
    "parse_light": "docker exec data-pipeline bash -c 'umask 0002 && cd /app && echo [envcheck] gate=9 채널=light; RUN_PIPELINE_DOC=/app/output/_docflow/7 PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.cli --set PIPE_OUT_ROOT=/app/output/_docflow/7 --set DOC_DIR_PREPARED=/app/output/_docflow/7/prepared --set PARSE_IMAGES_ROOT=/app/output/_docflow/7/parse/_images --set PARSE_RAW_ROOT=/app/output/_docflow/7/parse --set VLM_MAX_CONCURRENCY=8 --set VLM_CONCURRENCY=8 --set VLM_FIGURES_MAX=10 --set PARSE_POST=supsub,charts,figures,context,attachments --set RAPIDOCR_PAGE_WORKERS=2 --set OCR_THREADS=1 --set PIPE_PROCS=4 --set PARSE_REP_SELECT=first --set PARSE_QA_LIGHT=1 --set CPU_MAX_LOAD=9 parse --staged'",
    "parse_vlm": "docker exec data-pipeline bash -c 'umask 0002 && cd /app && echo [envcheck] gate=1.3 채널=vlm; RUN_PIPELINE_DOC=/app/output/_docflow/9 PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.cli --set PIPE_OUT_ROOT=/app/output/_docflow/9 --set DOC_DIR_PREPARED=/app/output/_docflow/9/prepared --set PARSE_IMAGES_ROOT=/app/output/_docflow/9/parse/_images --set PARSE_RAW_ROOT=/app/output/_docflow/9/parse --set VLM_MAX_CONCURRENCY=8 --set VLM_CONCURRENCY=8 --set VLM_FIGURES_MAX=10 --set PARSE_POST=supsub,charts,figures,context,attachments --set RAPIDOCR_PAGE_WORKERS=2 --set OCR_THREADS=1 --set PIPE_PROCS=4 --set PARSE_REP_SELECT=first --set PARSE_QA_LIGHT=1 --set VLM_MAX_CONCURRENCY=6 --set VLM_CONCURRENCY=6 --set PARSE_POST=supsub,charts,figures,context,attachments,vlm_page --set VLM_PAGE_MAX= --set CPU_MAX_LOAD=1.3 parse --staged'",
    "struct": "docker exec data-pipeline bash -c 'umask 0002 && cd /app && PYTHONPATH=/app/deploy PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.transform.structure.gold_bundle --set EMBED_CONCURRENCY=6 --set EMBED_BATCH=32 --set BM25_THREADS=3 --parse-dir /app/output/_docflow/9/parse --out /app/output/_docflow/9/bundle && PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.load.pgvector_load --set EMBED_CONCURRENCY=6 --set EMBED_BATCH=32 --set BM25_THREADS=3 load --bundle /app/output/_docflow/9/bundle --rep-dir /app/output/_docflow/9/parse/_rep >> /app/output/_docflow/9/structure.log 2>&1'",
    "publish": "docker exec data-pipeline bash -c 'umask 0002 && cd /app && PYTHONPATH=/app/deploy PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.load.publish_parse_result --out /app/output/_docflow/9 --source-system FileStorageMap --apply >> /app/output/_docflow/9/publish.log 2>&1'",
    "sweep": "docker exec data-pipeline bash -c \"for p in /proc/[0-9]*; do grep -aqzx 'RUN_PIPELINE_DOC=/app/output/_docflow/9' \\$p/environ 2>/dev/null && kill \\${p##*/} 2>/dev/null; done\"",
    "list": "docker exec data-pipeline bash -c 'umask 0002 && cd /app && PYTHONPATH=/app/deploy PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.extract.candidate_pick list --filter RFP,proposal --start-offset 0 --skip-done --max-docs 30 --faq-seen /app/output/_faq_seen.txt --out /app/output/_docflow/targets.json'",
}


LIST_ARGS = argparse.Namespace(filter="RFP,proposal", start_offset=0, limit=0, seqs="", skip_done=True, max_docs=30)


def _built():
    return {
        "staging": RD.stage_cmd(9),
        "parse_light": RD.parse_cmd(7, "light", "9"),
        "parse_vlm": RD.parse_cmd(9, "vlm", "1.3"),
        "struct": RD.struct_cmd(9),
        "list": RD.list_cmd(LIST_ARGS),
        "publish": RD.publish_cmd(9),
        "sweep": RD.sweep_cmd(9),
    }


def test_command_lines_fixed():
    """명령 글자가 고정값과 같다 — 바꿀 때는 이 표도 같은 커밋에서(서버 운영 명령이 바뀜)."""
    assert _built() == GOLDEN


def _inner(cmd):
    """docker exec <컨테이너> bash -c '<안>'의 <안>."""
    return shlex.split(cmd)[-1]


def test_container_command_from_setting():
    """컨테이너 명령은 DOCKER(셸 env > 설정 ops.host.container_cli > podman·docker)에서 — 고정 docker 글자가 남지 않음."""
    old = RD.DOCKER
    try:
        RD.DOCKER = "podman"
        assert all(v.startswith("podman exec ") for v in _built().values()), _built()
    finally:
        RD.DOCKER = old


def test_settings_only_via_set():
    """컨테이너 안 python에 설정 칸 이름을 env(`X=값 python`·`X=값 … && python`)로 주지 않는다 — 모두 --set(앱은 env의 설정 이름을
    읽지 않음). env로 남는 것은 라이브러리(PYTHON*)·문서 표지(RUN_PIPELINE_DOC)뿐."""
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
    """문서별 파싱은 결과·준비·이미지·원문 폴더를 그 문서 폴더로, 채널 값은 뒤 --set이 이긴다."""
    names, rest = setarg.split(shlex.split(_inner(GOLDEN["parse_vlm"])))
    inside = "/app/output/_docflow/9"
    assert names["PIPE_OUT_ROOT"] == inside and names["DOC_DIR_PREPARED"] == f"{inside}/prepared"
    assert names["PARSE_RAW_ROOT"] == f"{inside}/parse" and names["PARSE_IMAGES_ROOT"] == f"{inside}/parse/_images"
    assert names["VLM_CONCURRENCY"] == "6" and names["VLM_PAGE_MAX"] == "" and "PREPARE_ROTATE" not in names
    assert names["PARSE_POST"].endswith(",vlm_page") and names["CPU_MAX_LOAD"] == "1.3"
    assert rest[rest.index("parse") + 1 :] == ["--staged"]  # 받기·거르기는 stage가 끝냄
    light, _ = setarg.split(shlex.split(_inner(GOLDEN["parse_light"])))
    assert light["VLM_CONCURRENCY"] == "8" and "VLM_PAGE_MAX" not in light and light["CPU_MAX_LOAD"] == "9"


def test_sweep_marker_matches_parse():
    """고아 정리가 찾는 표지 env가 파싱 명령이 주는 표지와 같다."""
    mark = f"{RD.DOC_MARK}=/app/output/_docflow/9"
    assert mark in _inner(GOLDEN["parse_vlm"]) and mark in GOLDEN["sweep"]


# ── 레인·대기열 정책(docs/prd/runner.md rn-01·rn-02) ──
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
    vals, probs = RD.run_pipeline_policy({})
    assert vals == RD.RUN_PIPELINE_DEFAULTS and probs == []
    doc = {"pipeline": {"host": {"run_pipeline": {"staging": "30", "struct_backlog": "0", "vlm_shared": "", "light_dedicated": "2"}}}}
    vals, probs = RD.run_pipeline_policy(doc)  # BaseLoader — 글자로 들어옴
    assert (vals["staging"], vals["struct_backlog"], vals["vlm_shared"], vals["light_dedicated"]) == (30, 0, 1, 2) and probs == []
    _, probs = RD.run_pipeline_policy({"pipeline": {"host": {"run_pipeline": {"staging": "-1", "vlm_cap": "x"}}}})
    assert len(probs) == 2 and all("형식 오류" in p for p in probs), probs
    no_shared = {f"{c}_shared": "0" for c in RD.LANES}
    # 배치가 끝나지 않는 설정 → 문제 있음 / 경계 바로 안쪽 → 문제 없음
    for sec, bad in [
        ({f"{c}_{k}": "0" for c in RD.LANES for k in ("dedicated", "shared")}, True),
        ({"vlm_cap": "0"}, True),
        ({"staging": "0"}, True),
        ({**no_shared, "vlm_dedicated": "0"}, True),
        ({**no_shared}, False),
        ({"vlm_dedicated": "0"}, False),  # 공유 워커가 vlm을 가져감
        ({"vlm_cap": "1", "staging": "1"}, False),
    ]:
        probs = RD.run_pipeline_policy({"pipeline": {"host": {"run_pipeline": sec}}})[1]
        assert bool(probs) == bad, (sec, probs)


def test_defaults_match_settings_model():
    """러너 기본값 = 설정 모델 기본값(호스트 python은 모델을 import하지 않아 두 곳에 있음)."""
    from pipeline.config import PipelineHostRunPipeline

    assert RD.RUN_PIPELINE_DEFAULTS == {k: f.default for k, f in PipelineHostRunPipeline.model_fields.items()}


def test_no_stack_version():
    """엔진 구성은 파일(판 번호 없음): 파싱·구조화 명령에 STACK_VERSION·--stack-version이 없다."""
    cmds = RD.parse_cmd(7, "light", "9") + RD.struct_cmd(9)
    assert "STACK_VERSION" not in cmds and "--stack-version" not in cmds and "engine_check" not in cmds


def test_read_settings_new_layout(tmp_path):
    """러너는 파일 배치를 모델 배치로 바꿔 읽고(글자 그대로), 옛 배치·같은 칸 두 번은 거부."""
    f = tmp_path / "settings.yaml"
    f.write_text(
        "required:\n  env: {run_env: dev}\n  edw: {read_password: '0123'}\nops:\n  run_pipeline:\n    staging: {max_docs: '30'}\n    structure: {max_backlog: null}\n",
        encoding="utf-8",
    )
    doc, err = RD.read_settings(f)
    assert err is None and doc["common"]["run_env"] == "dev" and doc["common"]["connections"]["rdb"]["read"]["password"] == "0123"
    vals, probs = RD.run_pipeline_policy(doc)
    assert (
        vals["staging"] == 30 and vals["struct_backlog"] == RD.RUN_PIPELINE_DEFAULTS["struct_backlog"] and probs == []
    )  # YAML null = 비움
    f.write_text("common:\n  run_env: dev\n", encoding="utf-8")
    doc, err = RD.read_settings(f)
    assert doc == {} and "common.run_env → required.env.run_env" in err
    f.write_text(
        "required:\n  env: {run_env: dev}\nops:\n  host: {docker: podman}\nops:\n  nightly: {start_time: '01:00'}\n", encoding="utf-8"
    )
    doc, err = RD.read_settings(f)
    assert doc == {} and "같은 칸 두 번: ops" in err  # 앱 settings와 같은 거부(layout.reject_dup_keys)


def test_instance_names(tmp_path):
    """여러 벌 — 러너도 앱과 같은 규칙으로 컨테이너·PG 스키마가 갈리고, prd에서 벌 이름·기본 포트는 거부(EDW 기록 표는 컨테이너가 읽음)."""
    req = {p: "x" for p, _ in RD.SETTINGS_REQUIRED}
    ports = {"mcp.server.port": "8775", "common.runtime.data_parsing_port": "8776"}
    # (run_env, 벌, 더 적는 칸, 기대 (컨테이너, 스키마) — None이면 거부)
    for run, inst, extra, want in (
        ("dev", "", {}, ("data-pipeline", "rag")),
        ("dev", "hong", ports, ("data-pipeline-hong", "rag_hong")),
        ("dev", "kim-a", ports, ("data-pipeline-kim-a", "rag_kim_a")),  # 스키마 접미는 -를 _로
        ("prd", "hong", ports, None),
        ("dev", "hong", {"mcp.server.port": "8775"}, None),  # 파싱 포트가 기본값 그대로
        ("dev", "hong", {"common.runtime.data_parsing_port": "8776"}, None),  # 검색 포트가 기본값 그대로
    ):
        rd = _load()  # 모듈 값을 바꾸므로 따로 읽음
        model = {}
        base = {**req, "common.run_env": run, "common.connections.pg.db_schema": "rag", "common.connections.rdb.port": "1433"}
        for p, v in {**base, "common.host.instance": inst, **extra}.items():
            rd._host().layout().set_path(model, p, v)
        f = tmp_path / "settings.yaml"
        f.write_text(yaml.safe_dump(rd._host().layout().to_file(model)), encoding="utf-8")
        probs = rd.configure(f)
        if want is None:
            assert probs, (run, inst, extra)
            continue
        assert probs == [] and (rd.PIPE_C, rd.PG_SCHEMA) == want, (run, inst, probs)


def test_staging_name_same():
    """staging 파일 이름(버킷|키의 sha1)은 컨테이너 쪽(candidate_ready._staging_path)과 같다 — 분류·원본 삭제가 그 이름을 쓴다."""
    from pathlib import Path

    from pipeline.extract import candidate_ready

    for bucket, key in [("raw", "SFDC/a.pdf"), ("버킷", "CRMS/한글 이름.hwp"), ("", "x")]:
        with mock.patch.object(RD, "SOURCE_BUCKET", bucket):
            assert RD._staging_bin({"s3_key": key}) == candidate_ready._staging_path(Path("w"), bucket, key).name, (bucket, key)


def test_deadline_at():
    """새벽 배치 마감 — 다음 그 시각, 지금보다 이르거나 같으면 다음 날(자정을 넘는 배치)."""
    import datetime

    now = datetime.datetime(2026, 11, 2, 23, 30)
    cases = [
        ("23:45", now.replace(minute=45)),
        ("05:00", datetime.datetime(2026, 11, 3, 5, 0)),
        ("23:30", datetime.datetime(2026, 11, 3, 23, 30)),
    ]
    for hhmm, want in cases:
        assert RD.deadline_at(hhmm, now) == want.timestamp(), hhmm


def test_parallel_stage_respects_free_slots():
    """pl-48 — 미리 받기 워커 여럿이 동시에 받되, 실제 동시 받기 = min(워커 수, 대기열 빈자리). 시험용 가짜 받기만(docker 없음)."""
    import threading
    import time
    from unittest import mock

    def run(workers, target, n_docs):
        RD.LANEQ.update({c: __import__("collections").deque() for c in RD.LANES})
        RD._fetching.clear()
        now, peak, lock = [0], [0], threading.Lock()

        def fake_stage(seq, row):
            with lock:
                now[0] += 1
                peak[0] = max(peak[0], now[0])
            time.sleep(0.05)
            with lock:
                now[0] -= 1
            return True

        rows = {i: {"s3_key": f"k{i}", "original_filename": f"f{i}.txt", "file_size": 1} for i in range(n_docs)}
        with (
            mock.patch.object(RD, "stage_one", fake_stage),
            mock.patch.object(RD, "classify_doc", lambda seq, row, cache=None: "light"),
            mock.patch.object(RD, "mark", lambda *a, **k: None),
            mock.patch.object(RD, "depth", lambda *a, **k: None),
            mock.patch.object(RD, "_class_cache", lambda: {}),
            mock.patch.object(RD, "STAGING_WORKERS", workers),
            mock.patch.object(RD, "STAGING_TARGET", target),
        ):
            RD.downloader(rows, list(range(n_docs)))
        return peak[0], sum(len(q) for q in RD.LANEQ.values())

    assert run(workers=3, target=20, n_docs=6) == (3, 6)  # 빈자리 넉넉 → 워커 수만큼 동시에
    assert run(workers=3, target=2, n_docs=2) == (2, 2)  # 빈자리 2 → 워커가 3이어도 2개만
    assert run(workers=1, target=20, n_docs=3) == (1, 3)  # 워커 1 = 하나씩


def test_classify_cache_skips_probe():
    """분류 캐시에 있으면 doc_lane_group(docker exec)를 부르지 않는다.
    캐시가 없으면 컨테이너 답의 마지막 줄(경고 줄 무시)을 쓰고, 답이 없으면 vlm(rn-01)."""
    from unittest import mock

    cases = [  # (파일 이름, 캐시 값, 컨테이너 답, 기대 레인)
        ("a.pdf", "vlm", None, "vlm"),
        ("a.pdf", "medium", None, "medium"),
        ("a.pptx", "vlm", None, "vlm"),
        ("a b.pdf", "", "MuPDF warning\nvlm\n", "vlm"),
        ("a.docx", "", "medium\n", "medium"),
        ("a.txt", "", "", "vlm"),  # 답 없음(컨테이너 실패) — 보수적으로 vlm
    ]
    for name, cached, out, want in cases:
        row = {"s3_key": "k", "original_filename": name, "file_size": 2048}
        sh = mock.Mock(return_value=(0, out, "")) if out is not None else mock.Mock(side_effect=AssertionError("probe 불림"))
        with (
            mock.patch.object(RD, "sh", sh),
            mock.patch.object(RD, "mark", lambda *a, **k: None),
            mock.patch.object(RD, "_class_save", lambda c: None),
        ):
            assert RD.classify_doc(5, row, cache={"k": cached} if cached else {}) == want, name
        if out is not None:
            assert sh.call_args[0][0].endswith(
                f"doc_lane_group.py {RD._img('output_root')}/_staging/{RD._staging_bin(row)} {shlex.quote(name)} 2048"
            ), name


def test_pg_count_sums_source_schemas():
    """문서·청크 수는 원천 스키마(<스키마>_<원천>) 5벌의 합 — 원천 목록은 검색 표 정의와 같다."""
    from common.store.db.models.search_tables import SOURCES

    assert RD.PG_SOURCES == SOURCES
    seen = []
    with mock.patch.object(RD, "sh", lambda cmd, timeout=0: seen.append(cmd) or (0, "3|7\n", "")):
        with mock.patch.object(RD, "PG_SCHEMA", "rag"):
            assert RD.pg_count() == (3, 7)
    assert all(f"rag_{s}.doc" in seen[0] and f"rag_{s}.chunk" in seen[0] for s in SOURCES) and "rag.doc" not in seen[0], seen
