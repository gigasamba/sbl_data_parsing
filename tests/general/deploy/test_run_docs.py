"""호스트 flow 러너 run_docs.py가 만드는 컨테이너 명령 줄 고정(S9 Step A — VS8b U-1, 사용자 10-28 `--set`).
run_docs.py는 로컬에서 실행하지 않는다(CLAUDE.md 3절) — 이 시험은 명령 줄을 만드는 함수만 부른다(설정 파일·docker·운영 접속 없음).
PC 일반 시험: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/general`(S9 — tests/general/deploy로 옮김)."""

import importlib.util
import re
import shlex

from common.config import setarg
from common.core.paths import DEPLOY_ROOT

ROOT = DEPLOY_ROOT  # 저장소 루트(op-09 — paths 상수)
INPROCESS = True  # 상태를 바꾸지 않는 시험 — pytest가 함수마다 그대로 모음(tests/conftest.py)


def _load():
    spec = importlib.util.spec_from_file_location("run_docs_under_test", ROOT / "deploy" / "host" / "scripts" / "run_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 모듈 맨 위는 정의만(configure()·docker 호출 없음)
    return mod


RD = _load()

GOLDEN = {
    "warm": "docker exec data-pipeline bash -c 'umask 0002 && mkdir -p /app/output/_warm && cd /app && PYTHONPATH=/app/deploy PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.extract.source --set SOURCE_WARM=/app/output/_warm warm --csv /app/output/_docflow/9/batch.csv'",
    "parse_light": "docker exec data-pipeline bash -c 'umask 0002 && cd /app && echo [envcheck] gate=9 채널=light; RUN_DOCS_DOC=/app/output/_docflow/7 PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.cli --set PIPE_OUT_ROOT=/app/output/_docflow/7 --set DOC_DIR_PREPARED=/app/output/_docflow/7/prepared --set PARSE_IMAGES_ROOT=/app/output/_docflow/7/parse/_images --set PARSE_RAW_ROOT=/app/output/_docflow/7/parse --set VLM_MAX_CONCURRENCY=8 --set VLM_CONCURRENCY=8 --set VLM_FIGURES_MAX=10 --set PARSE_POST=supsub,charts,figures,context,attachments --set RAPIDOCR_PAGE_WORKERS=2 --set OCR_THREADS=1 --set PIPE_PROCS=4 --set SOURCE_WARM=/app/output/_warm --set SOURCE_FETCH_WORKERS=2 --set PARSE_REP_SELECT=first --set PARSE_QA_LIGHT=1 --set CPU_MAX_LOAD=9 parse --source rdb:csv:/app/output/_docflow/7/batch.csv'",
    "parse_vlm_scan": "docker exec data-pipeline bash -c 'umask 0002 && cd /app && echo [envcheck] gate=1.3 채널=vlm; RUN_DOCS_DOC=/app/output/_docflow/9 PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.cli --set PIPE_OUT_ROOT=/app/output/_docflow/9 --set DOC_DIR_PREPARED=/app/output/_docflow/9/prepared --set PARSE_IMAGES_ROOT=/app/output/_docflow/9/parse/_images --set PARSE_RAW_ROOT=/app/output/_docflow/9/parse --set VLM_MAX_CONCURRENCY=8 --set VLM_CONCURRENCY=8 --set VLM_FIGURES_MAX=10 --set PARSE_POST=supsub,charts,figures,context,attachments --set RAPIDOCR_PAGE_WORKERS=2 --set OCR_THREADS=1 --set PIPE_PROCS=4 --set SOURCE_WARM=/app/output/_warm --set SOURCE_FETCH_WORKERS=2 --set PARSE_REP_SELECT=first --set PARSE_QA_LIGHT=1 --set VLM_MAX_CONCURRENCY=6 --set VLM_CONCURRENCY=6 --set PARSE_POST=supsub,charts,figures,context,attachments,vlm_page --set VLM_PAGE_MAX= --set PREPARE_ROTATE=0 --set CPU_MAX_LOAD=1.3 parse --source rdb:csv:/app/output/_docflow/9/batch.csv'",
    "struct": "docker exec data-pipeline bash -c 'umask 0002 && cd /app && PYTHONPATH=/app/deploy PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.transform.structure.build_bundle --set EMBED_CONCURRENCY=6 --set EMBED_BATCH=32 --set BM25_THREADS=3 --parse-dir /app/output/_docflow/9/parse --out /app/output/_docflow/9/bundle && PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.load.pgvector_load --set EMBED_CONCURRENCY=6 --set EMBED_BATCH=32 --set BM25_THREADS=3 load --bundle /app/output/_docflow/9/bundle --rep-dir /app/output/_docflow/9/parse/_rep >> /app/output/_docflow/9/structure.log 2>&1'",
    "publish": "docker exec data-pipeline bash -c 'umask 0002 && cd /app && PYTHONPATH=/app/deploy PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.load.publish_parse_result --set PM_BUCKET_SKIP_OVERLAP_CHECK=1 --out /app/output/_docflow/9 --source-system FileStorageMap --apply >> /app/output/_docflow/9/publish.log 2>&1'",
    "sweep": "docker exec data-pipeline bash -c \"for p in /proc/[0-9]*; do grep -aqzx 'RUN_DOCS_DOC=/app/output/_docflow/9' \\$p/environ 2>/dev/null && kill \\${p##*/} 2>/dev/null; done\"",
    "faq_sync": "docker exec data-pipeline bash -c 'umask 0002 && cd /app && PYTHONPATH=/app/deploy PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache python -m pipeline.load.pgvector_load faq-sync --reset --out /app/output/_docflow/faq_sync.json'",
}


def _built():
    return {
        "warm": RD.warm_cmd(9),
        "parse_light": RD.parse_cmd(7, "light", False, "9"),
        "parse_vlm_scan": RD.parse_cmd(9, "vlm", True, "1.3"),
        "struct": RD.struct_cmd(9),
        "faq_sync": RD.faq_sync_cmd(True),
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
    """op-10 — 컨테이너 명령은 DOCKER(설정 ops.host.docker, 없으면 podman·docker)에서 — 고정 docker 글자가 남지 않음."""
    old = RD.DOCKER
    try:
        RD.DOCKER = "podman"
        assert all(v.startswith("podman exec ") for v in _built().values()), _built()
    finally:
        RD.DOCKER = old


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
    inside = "/app/output/_docflow/9"
    assert names["PIPE_OUT_ROOT"] == inside and names["DOC_DIR_PREPARED"] == f"{inside}/prepared"
    assert names["PARSE_RAW_ROOT"] == f"{inside}/parse" and names["PARSE_IMAGES_ROOT"] == f"{inside}/parse/_images"
    assert names["VLM_CONCURRENCY"] == "6" and names["VLM_PAGE_MAX"] == "" and names["PREPARE_ROTATE"] == "0"
    assert names["PARSE_POST"].endswith(",vlm_page") and names["CPU_MAX_LOAD"] == "1.3"
    assert rest[rest.index("parse") + 1 : rest.index("parse") + 3] == ["--source", f"rdb:csv:{inside}/batch.csv"]
    light, _ = setarg.split(shlex.split(_inner(GOLDEN["parse_light"])))
    assert light["VLM_CONCURRENCY"] == "8" and "VLM_PAGE_MAX" not in light and light["CPU_MAX_LOAD"] == "9"


def test_sweep_marker_matches_parse():
    """고아 정리가 찾는 표지 env가 파싱 명령이 주는 표지와 같다(옛 PIPE_OUT_ROOT env 자리)."""
    mark = f"{RD.DOC_MARK}=/app/output/_docflow/9"
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


def test_no_stack_version():
    """사용자 11-01 — 엔진 구성은 파일(판 번호 없음): 파싱·구조화 명령에 STACK_VERSION·--stack-version이 없다."""
    cmds = RD.parse_cmd(7, "light", False, "9") + RD.struct_cmd(9)
    assert "STACK_VERSION" not in cmds and "--stack-version" not in cmds and "stackcfg" not in cmds


def test_read_settings_new_layout(tmp_path):
    """op-08 ② — 러너는 새 배치 파일을 모델 배치로 바꿔 읽고(글자 그대로), 옛 배치는 migrate 안내로 거부."""
    f = tmp_path / "settings.yaml"
    f.write_text("required:\n  env: {run_env: dev}\n  edw: {read_password: '0123'}\nops:\n  run_docs: {warm: '30'}\n", encoding="utf-8")
    doc, err = RD.read_settings(f)
    assert err is None and doc["common"]["run_env"] == "dev" and doc["common"]["connections"]["rdb"]["read"]["password"] == "0123"
    assert RD.run_docs_policy(doc)[0]["warm"] == 30
    f.write_text("common:\n  run_env: dev\n", encoding="utf-8")
    doc, err = RD.read_settings(f)
    assert doc == {} and "common.config.migrate" in err
    f.write_text("required:\n  env: {run_env: dev}\nops:\n  host: {docker: podman}\nops:\n  nightly: {time: '01:00'}\n", encoding="utf-8")
    doc, err = RD.read_settings(f)
    assert doc == {} and "같은 칸 두 번: ops" in err  # 앱 settings와 같은 거부(layout.reject_dup_keys)


def test_done_keys_match_parsing_meta():
    """운영 고침 11b — 끝난 문서 상태는 ParsingMeta 쪽(DONE_STATUSES — ok·partial·skipped_dup, 사용자 11-01 C10)과 같다."""
    from common.store.parsing_meta_db import DONE_STATUSES, GOLD_STATUSES

    assert RD.DONE_STATUSES == DONE_STATUSES and RD.GOLD_STATUSES == GOLD_STATUSES  # gold_version도 봄(사용자 11-02)


def test_deadline_at():
    """새벽 배치 마감(사용자 11-02) — 다음 그 시각, 지금보다 이르거나 같으면 다음 날(자정을 넘는 배치)."""
    import datetime

    now = datetime.datetime(2026, 11, 2, 23, 30)
    cases = [
        ("23:45", now.replace(minute=45)),
        ("05:00", datetime.datetime(2026, 11, 3, 5, 0)),
        ("23:30", datetime.datetime(2026, 11, 3, 23, 30)),
    ]
    for hhmm, want in cases:
        assert RD.deadline_at(hhmm, now) == want.timestamp(), hhmm


def test_parallel_warm_respects_free_slots():
    """pl-48(사용자 11-02) — 미리 받기 워커 여럿이 동시에 받되, 실제 동시 받기 = min(워커 수, 대기열 빈자리). 시험용 가짜 받기만(docker 없음)."""
    import threading
    import time
    from unittest import mock

    def run(workers, target, n_docs):
        RD.LANEQ.update({c: __import__("collections").deque() for c in RD.LANES})
        RD._warming.clear()
        now, peak, lock = [0], [0], threading.Lock()

        def fake_warm(seq, row):
            with lock:
                now[0] += 1
                peak[0] = max(peak[0], now[0])
            time.sleep(0.05)
            with lock:
                now[0] -= 1
            return True

        rows = {i: {"s3_key": f"k{i}", "original_filename": f"f{i}.txt", "file_size": 1} for i in range(n_docs)}
        with (
            mock.patch.object(RD, "warm_one", fake_warm),
            mock.patch.object(RD, "classify_doc", lambda seq, row, cache=None: "light"),
            mock.patch.object(RD, "mark", lambda *a, **k: None),
            mock.patch.object(RD, "depth", lambda *a, **k: None),
            mock.patch.object(RD, "_class_cache", lambda: {}),
            mock.patch.object(RD, "WARM_WORKERS", workers),
            mock.patch.object(RD, "WARM_TARGET", target),
        ):
            RD.downloader(rows, list(range(n_docs)))
        return peak[0], sum(len(q) for q in RD.LANEQ.values())

    assert run(workers=3, target=20, n_docs=6) == (3, 6)  # 빈자리 넉넉 → 워커 수만큼 동시에
    assert run(workers=3, target=2, n_docs=2) == (2, 2)  # 빈자리 2 → 워커가 3이어도 2개만
    assert run(workers=1, target=20, n_docs=3) == (1, 3)  # 워커 1 = 옛 동작(하나씩)


def test_faq_first(tmp_path):
    """pl-41 — 새 FAQ(faq_seen에 없던 키)면 --reset + FAQ 전체를 맨 앞에(--filter에 없던 FAQ 행은 덧붙임), faq_seen은 교체가 끝난 뒤에만 ·
    새 FAQ가 없으면 gold에 없는 FAQ만(지우지 않음, 완전 중복 skipped_dup은 뺌) · faq-sync 결과가 없으면 FAQ 전체(이미 있는 문서는 적재가 건너뜀)."""
    import json as J
    from unittest.mock import patch

    U1, U2 = "FAQ/u1/q.xlsx", "FAQ/u2/r.xlsx"
    faq = [{"s3_key": U1}, {"s3_key": U2}]
    cmds = []

    def run(status, out, rc=0):
        rows = [{"s3_key": "SFDC/u/a.pdf"}, {"s3_key": U1}, {"s3_key": "LAS/u/b.pdf"}]

        def sh(c, **k):
            cmds.append(c)
            if out is not None:
                (tmp_path / "faq_sync.json").write_text(J.dumps(out), encoding="utf-8")
            return rc, "", "boom"

        with (
            patch.object(RD, "DOCFLOW", tmp_path),
            patch.object(RD, "PROG", tmp_path),
            patch.object(RD, "log", print),
            patch.object(RD, "sh", sh),
            patch.object(RD, "edw_faq", lambda: (faq, status)),
        ):
            return RD.faq_first(rows, [0, 2]), len(rows)

    seen = tmp_path / "faq_seen.txt"
    seen.write_text(U1 + "\n", encoding="utf-8")
    assert run({U1: "ok"}, None, rc=2) == ([1, 3, 0, 2], 4)  # u2가 새 FAQ인데 교체 실패(판 확인 등) — 전체, 다음 실행이 다시 교체
    assert cmds[-1] == RD.faq_sync_cmd(True) and U2 not in seen.read_text(encoding="utf-8")
    assert run({U1: "ok", U2: "ok"}, {"faq_reset": 1, "gold": []}) == ([1, 3, 0, 2], 4)  # ParsingMeta에 있어도(--seqs 실행) 새 FAQ — 교체
    assert cmds[-1] == RD.faq_sync_cmd(True) and U2 in seen.read_text(encoding="utf-8")  # 교체가 끝난 뒤에만 적음
    assert run({U1: "ok", U2: "ok"}, {"faq_reset": 0, "gold": [U1]}) == ([3, 0, 2], 4)  # gold에 없는 u2만
    assert cmds[-1] == RD.faq_sync_cmd(False)
    assert run({U1: "ok", U2: "ok"}, {"faq_reset": 0, "gold": [U1, U2]}) == ([0, 2], 4)  # 그대로
    assert run({U1: "ok"}, {"faq_reset": 0, "gold": [U1]}) == ([3, 0, 2], 4)  # u2 파싱 실패(ParsingMeta 없음) — 지우지 않고 채움
    assert run({U1: "ok", U2: "skipped_dup"}, {"faq_reset": 0, "gold": [U1]}) == ([0, 2], 4)  # 완전 중복은 gold에 안 올라감 — 안 채움
    seen.unlink()
    assert run({U1: "ok", U2: "ok"}, {"faq_reset": 2, "gold": []}) == ([1, 3, 0, 2], 4)  # 처음 실행(파일 없음) — 한 번 교체
    assert seen.read_text(encoding="utf-8") == f"{U1}\n{U2}\n"


def test_classify_cache_skips_probe():
    """A3 — 분류 캐시에 있으면 probe(docker exec)를 부르지 않는다. 캐시는 레인만 담으므로 PDF의 vlm은 스캔으로 되살린다(probe heavy일 때만 PDF가 vlm)."""
    from unittest import mock

    cases = [  # (파일 이름, 캐시 값, 기대 레인, 스캔?)
        ("a.pdf", "vlm", "vlm", True),
        ("a.pdf", "medium", "medium", False),
        ("a.pptx", "vlm", "vlm", False),
    ]
    for name, cached, want, scan in cases:
        RD._scan.clear()
        row = {"s3_key": "k", "original_filename": name, "file_size": 1}
        with (
            mock.patch.object(RD, "sh", side_effect=AssertionError("probe 불림")),
            mock.patch.object(RD, "mark", lambda *a, **k: None),
            mock.patch.object(RD, "_class_save", lambda c: None),
        ):
            assert RD.classify_doc(5, row, cache={"k": cached}) == want, name
        assert (5 in RD._scan) is scan, name
