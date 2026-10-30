"""pipeline.extract.run_all 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.extract.run_all --selftest`."""

import json
import sys
from pathlib import Path

from common.config import settings as C
from common.core.paths import APP_ROOT
from pipeline import config as pc
from pipeline.extract.engines import registry
from pipeline.extract.run_all import (
    OCR_ENGINES,
    VLM_ENGINES,
    _default_procs,
    _old_phase_timeout,
    _sha,
    _stamp_provenance,
    engine_code_fp,
    engines_for_doc,
    p0_key,
    p0_status,
    page_timeout,
    redact,
)
from pipeline.shared import artifacts as P0


def selftest():
    # S7c1(코디네이터 답 ①b) — --procs 기본이 옛 `get("PIPE_PROCS") or "1"`과 같은지: auto → auto · 없음·빈 값 → 1 · 숫자 → 그 글자
    from common.config.settings import COMMON, IMAGE_DEFAULTS

    # 없음 = 기본값(PC 1 · pipeline 이미지 auto — 옛 이미지 ENV, S7e2 B-2) · 빈 값은 이미지에서도 1(옛 env_file `PIPE_PROCS=`이 이미지 ENV를 덮던 것)
    want = {None: "auto" if IMAGE_DEFAULTS.get("PIPE_PROCS") == "auto" else "1", "": "1", "auto": "auto", "3": "3", "2.5": "2.5"}
    got = {}
    for raw in want:
        with COMMON.env(PIPE_PROCS=raw):
            got[raw] = _default_procs()
    assert got == want, got
    print("[selftest] S7c1 — --procs 기본(PIPE_PROCS: auto → auto · 없음·빈 값 → 1 · 숫자 그대로) 옛 판정과 같음 통과")
    # PE1(2026-10-07) — PARSE_ENGINE_SCOPE: stack이면 문서 형식 키(stack.json과 같은 키)의 parse 목록으로만 좁힘
    pdf_cands, doc_cands = ([e for e in registry.engines_for(x) if e not in OCR_ENGINES] for x in (".pdf", ".doc"))  # OCR 기본 끔(10-29)
    assert "pymupdf" in pdf_cands and "kreuzberg" in pdf_cands and len(pdf_cands) > 2  # 좁혀짐을 보려면 전체가 2개보다 많아야
    stack_parse = {".pdf_text": ["pymupdf", "kreuzberg"]}
    missing = set()
    a_pdf = Path("a.pdf")
    assert engines_for_doc(a_pdf, "stack", stack_parse, {"a.pdf": ".pdf_text"}, missing) == [
        e for e in pdf_cands if e in stack_parse[".pdf_text"]
    ]
    assert missing == set()  # 키 있음 — 로그 없음
    # 키 없는 형식(.doc 등) — 지금처럼 그대로(핵심 엔진 합집합 대체, 누락 방지) + 형식별 1회만 로그
    assert engines_for_doc(Path("b.doc"), "stack", stack_parse, {"b.doc": ".doc"}, missing) == doc_cands
    assert missing == {".doc"}
    assert (
        engines_for_doc(Path("c.doc"), "stack", stack_parse, {"c.doc": ".doc"}, missing) == doc_cands
    )  # 두 번째도 그대로(로그는 1회만, missing 그대로)
    assert missing == {".doc"}
    # all(기본) — stack.json 내용과 무관하게 지금 동작 그대로(실험 경로·명시 --engines 호출이 이 env를 안 건드리므로 영향 없음)
    assert engines_for_doc(a_pdf, "all", stack_parse, {"a.pdf": ".pdf_text"}, set()) == pdf_cands
    print("[selftest] PE1 — PARSE_ENGINE_SCOPE=stack 형식별 좁히기(키 없으면 그대로+1회 로그) · all=이전과 동일 통과")

    # 사용자 10-29 — .pdf_text 안 스캔 쪽 때문에 .pdf_image 엔진을 합치지 않음(대표 결과의 쪽 VLM이 그 쪽만 채움)
    stack_pi = {".pdf_text": ["pymupdf"], ".pdf_image": ["rapidocr_ko", "qwen_vlm"]}
    assert engines_for_doc(Path("mixed.pdf"), "stack", stack_pi, {"mixed.pdf": ".pdf_text"}, set()) == ["pymupdf"]
    print("[selftest] 10-29 — .pdf_text 문서에 .pdf_image 엔진을 합치지 않음 통과")

    # 사용자 10-29 — OCR 엔진은 ocr_engine(PARSE_OCR_ENGINE) 켤 때만 · 기본은 이미지·스캔 문서도 VLM 엔진만
    png_stack = {".png": ["rapidocr_ko", "qwen_vlm"]}
    assert OCR_ENGINES == {"rapidocr", "rapidocr_ko"}
    assert engines_for_doc(Path("x.png"), "stack", png_stack, {"x.png": ".png"}, set()) == ["qwen_vlm"]
    assert not OCR_ENGINES & set(engines_for_doc(Path("x.png"), "all", {}, {}, set()))
    with pc.PIPE.env(PARSE_OCR_ENGINE="1"):
        assert set(engines_for_doc(Path("x.png"), "stack", png_stack, {"x.png": ".png"}, set())) == {"rapidocr_ko", "qwen_vlm"}
    print("[selftest] 10-29 — OCR 엔진 기본 끔(켜면 포함) 통과")

    # 사용자 10-29 — 형식당 엔진 2개 넘으면 설정 오류(진입점 resolve·run_all 같은 검사)
    from pipeline.stackcfg import over_limit

    assert over_limit({"parse": {".pdf_text": ["pymupdf", "kreuzberg"], ".png": ["qwen_vlm"]}}) == []
    bad = over_limit({"parse": {".docx": ["office", "anydoc", "kreuzberg"]}})
    assert len(bad) == 1 and ".docx" in bad[0], bad
    from common.core.paths import STACK_FILE

    stack_file = json.loads(STACK_FILE.read_text(encoding="utf-8"))
    assert over_limit(stack_file) == [], "PC 기본 stack 표가 형식당 2개를 넘음"
    print("[selftest] 10-29 — 형식당 엔진 2개 상한(over_limit) 통과")

    # 사용자 10-29 — 쪽당 제한: 글자 엔진 10초·VLM 120초(설정) · 첫 문서 warmup 하한 · 별도 프로세스 여유 더함
    with pc.PIPE.env(PARSE_TEXT_PAGE_SEC="10", PARSE_VLM_PAGE_SEC="120", PARSE_WARMUP_SEC="60", PARSE_ISOLATE_OVERHEAD="10"):
        assert page_timeout("pymupdf", 3) == 3 * 10 + 10
        assert page_timeout("pymupdf", 0) == 10 + 10  # 쪽 수 못 셈 → 1쪽
        assert page_timeout("pymupdf", 2, first=True) == 60 + 10  # 첫 문서는 warmup 하한
        assert page_timeout(next(iter(VLM_ENGINES)), 2) == 2 * 120 + 10
        assert page_timeout("qwen_vlm", 1, first=True) == 120 + 10  # warmup보다 크면 그대로
    with pc.PIPE.env(PARSE_TEXT_PAGE_SEC="0.5", PARSE_ISOLATE_OVERHEAD="0"):
        assert page_timeout("pymupdf", 4) == 2.0
    print("[selftest] 10-29 — 쪽당 제한 계산(글자·VLM·warmup·별도 프로세스 여유) 통과")

    # phase 시절의 옛 시간 초과 기록(phase 칸 있음)은 막지 않고 다시 시도 · 새 기록·다른 실패는 그대로 막음
    assert _old_phase_timeout({"phase": 1, "error": "TimeoutError: 문서×엔진 시간 제한 초과"})
    assert not _old_phase_timeout({"error": "TimeoutError: 문서×엔진 시간 제한 초과(20초)"})
    assert not _old_phase_timeout({"phase": 2, "error": "RuntimeError: 깨짐"})
    print("[selftest] 10-29 — 옛 phase 시간 초과 기록은 다시 시도 대상 통과")

    # 이름≠폴더 엔진(office→office_stdlib)도 자기 엔진 코드가 지문에 들어가야 함(10-05 결함: _common만 해시돼 엔진 수정이 안 잡힘)
    assert engine_code_fp("office") != engine_code_fp("no-such-engine-xyz"), "office 지문에 office_stdlib 코드가 빠짐"
    assert p0_status(None, "pymupdf", "a" * 64)[0] == "unknown"  # 옛 기록(열쇠 없음) = 버전 미상
    ver = P0.engine_version("pymupdf")
    sha = "a" * 64
    # 기록할 때 쓰는 열쇠로 다음 실행 판정이 'ok' — 기록·비교가 다른 열쇠를 쓰던 결함(10-04) 회귀 방지
    new = {"p0_key": p0_key("pymupdf", sha, ver), "p0_code": engine_code_fp("pymupdf"), "engine_version": ver, "sha": sha}
    assert p0_status(new, "pymupdf", sha)[0] == "ok"
    assert p0_status({**new, "p0_key": "다른값"}, "pymupdf", sha)[0] == "stale"  # 새 형식인데 열쇠 다름(엔진 코드·버전 바뀜) → 낡음
    # 옛 형식(p0_code 없음): 같은 sha·같은 엔진 버전이면 재사용, 버전이 다르면 낡음
    assert p0_status({"p0_key": "옛열쇠", "engine_version": ver, "sha": sha}, "pymupdf", sha)[0] == "ok"
    assert p0_status({"p0_key": "옛열쇠", "engine_version": "0.0-다름", "sha": sha}, "pymupdf", sha)[0] == "stale"
    # 열쇠는 common·run_all과 무관(검색 토크나이저만 바꿔도 원문 재파싱하던 일) — 엔진 폴더 코드·sha·버전만
    assert p0_key("pymupdf", sha, ver) == p0_key("pymupdf", sha, ver) and p0_key("pymupdf", sha, ver) != p0_key("pymupdf", "b" * 64, ver)
    print("[selftest] P0 열쇠(버전 미상·재사용·낡음·기록=비교 같은 열쇠·옛 열쇠) 판정 통과")

    import tempfile

    dst = Path(tempfile.mkdtemp()) / "x.json"
    dst.write_text(json.dumps({"text": "본문"}), encoding="utf-8")
    _stamp_provenance(dst, "pymupdf", "1.2.3", "deadbeef", "default")
    d = json.loads(dst.read_text(encoding="utf-8"))
    assert d["text"] == "본문" and d["provenance"]["engine"] == "pymupdf" and d["provenance"]["engine_version"] == "1.2.3"
    assert d["provenance"]["p0_key"] == "deadbeef" and d["provenance"]["params"] == {"profile": "default"}
    print("[selftest] 엔진 결과 JSON에 provenance 블록 추가 통과")

    # X2 ⑤: 오류 글자에 섞인 문서 내용(인용부호로 감싼 긴 조각)을 가림 — 짧은 인용(엔진·파일 이름 등)은 그대로 둠
    body = "계약 금액은 1,234,567원이고 수령인은 홍길동이며 주소는 서울특별시 어딘가의 매우 긴 문장입니다"
    assert "가림" in redact(f"ValueError: bad token '{body}'") and body not in redact(f"ValueError: bad token '{body}'")
    assert redact("ImportError: No module named 'pandas'") == "ImportError: No module named 'pandas'"  # 30자 미만은 그대로
    print("[selftest] X2 — 오류 글자의 긴 인용 조각(문서 내용 가능성) 가림 통과")

    # RB3② — env 오류(qwen_vlm: VLM_BASE_URL·VLM_MODEL 미설정) 엔진은 이번 실행 안에서 첫 실패 뒤 나머지 문서는 빠르게 건너뜀
    #   (SI33 — cognee_import 어댑터 삭제로 REQUIRES_ENV가 있는 다른 엔진으로 교체, 같은 missing_env 경로)
    import subprocess
    import tempfile as _tf

    sdir, odir = Path(_tf.mkdtemp()), Path(_tf.mkdtemp())
    for i in range(3):
        (sdir / f"d{i}.png").write_bytes(f"fake {i}".encode())  # 내용이 달라야 sha256 dedup(같은 내용 사본)에 안 걸림
    # 하위 프로세스(시험) 설정 — 덮기 파일(S7e2 — VLM_*는 엔진 키라 env에서도 지움). PIPE_PROCS=1 — 이미지 기본 auto: 여러 프로세스면
    # '첫 실패' 기억을 서로 안 나눠 이 시험 전제가 깨짐(순차 동작만 확인)
    env = C.child_env(VLM_BASE_URL=None, VLM_MODEL=None, PIPE_PROCS="1")
    r = subprocess.run(
        [sys.executable, "-m", "pipeline.extract.run_all", "--src", str(sdir), "--out", str(odir), "--engines", "qwen_vlm"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(APP_ROOT),
        timeout=60,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    recs = [json.loads(ln) for ln in (odir / "runs.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(recs) == 3, recs
    assert recs[0]["error"] and "미설정" in recs[0]["error"] and not recs[0].get("skipped_env"), recs[
        0
    ]  # 첫 문서는 실제로 시도(진짜 env 오류)
    for rec in recs[1:]:
        assert rec["error"] == f"건너뜀(환경 — 첫 실패 {recs[0]['doc']})" and rec.get("skipped_env") is True and rec["sec"] == 0, rec
    print("[selftest] RB3② — env 오류 엔진은 이번 실행 안에서 첫 실패 뒤 같은 엔진 나머지 문서를 건너뜀(runs.jsonl 기록) 통과")

    # SI23 — PARSE_RUN_ID(env)가 있으면 runs.jsonl 각 줄에 run_id로 기록(run_board가 이번 실행만 거르게) · 없으면 칸 없음(옛 형식 호환)
    sdir3, odir3 = Path(_tf.mkdtemp()), Path(_tf.mkdtemp())
    (sdir3 / "d0.png").write_bytes(b"fake")
    env3 = C.child_env(VLM_BASE_URL=None, VLM_MODEL=None)  # 하위 프로세스(시험) 설정 — 덮기 파일(S7e2)
    env3["PARSE_RUN_ID"] = "20261007-999999"  # env 남김 — 내부 신호(5-3 H)
    r3 = subprocess.run(
        [sys.executable, "-m", "pipeline.extract.run_all", "--src", str(sdir3), "--out", str(odir3), "--engines", "qwen_vlm"],
        capture_output=True,
        text=True,
        env=env3,
        cwd=str(APP_ROOT),
        timeout=60,
    )
    assert r3.returncode == 0, r3.stderr[-2000:]
    recs3 = [json.loads(ln) for ln in (odir3 / "runs.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(recs3) == 1 and recs3[0]["run_id"] == "20261007-999999", recs3
    env3.pop("PARSE_RUN_ID")
    r4 = subprocess.run(
        [sys.executable, "-m", "pipeline.extract.run_all", "--src", str(sdir3), "--out", str(odir3), "--engines", "qwen_vlm", "--force"],
        capture_output=True,
        text=True,
        env=env3,
        cwd=str(APP_ROOT),
        timeout=60,
    )
    assert r4.returncode == 0, r4.stderr[-2000:]
    recs4 = [json.loads(ln) for ln in (odir3 / "runs.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert "run_id" not in recs4[-1], recs4[-1]  # env 없으면 칸 없음(호환)
    print("[selftest] SI23 — PARSE_RUN_ID(env)가 있으면 runs.jsonl에 run_id 기록, 없으면 칸 없음(호환) 통과")

    # SI44③ — 앞 실행에서 실패 엔진 전부가 암호 오류면(엔진마다 메시지가 달라도) encrypted_detected로 적고 다시 시도 안 함
    sdir5, odir5 = Path(_tf.mkdtemp()), Path(_tf.mkdtemp())
    doc5 = sdir5 / "enc.pptx"
    doc5.write_bytes(b"fake pptx")
    cand5 = [e for e in registry.engines_for(".pptx") if e not in OCR_ENGINES]
    assert len(cand5) >= 2, cand5  # 엔진마다 다른 메시지로도 전부 걸리는지 확인하려면 2개 이상
    sha5 = _sha(doc5)
    with (odir5 / "runs.jsonl").open("w", encoding="utf-8") as f:
        for i, e in enumerate(cand5):
            f.write(
                json.dumps(
                    {
                        "doc": doc5.name,
                        "engine": e,
                        "sha": sha5,
                        "sec": 1,
                        "phase": 1,
                        "error": "ValueError: document is encrypted" if i == 0 else "password error",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    r5 = subprocess.run(
        [sys.executable, "-m", "pipeline.extract.run_all", "--src", str(sdir5), "--out", str(odir5)],
        capture_output=True,
        text=True,
        env=C.child_env(PIPE_PROCS="1"),
        cwd=str(APP_ROOT),
        timeout=60,
    )  # 하위 프로세스(시험) — 덮기 파일(S7e2)
    assert r5.returncode == 0, r5.stderr[-2000:]
    skip_log5 = sdir5 / "skipped.jsonl"
    assert skip_log5.exists(), "encrypted_detected가 prepare와 같은 skipped.jsonl에 기록돼야 함"
    skipped5 = [json.loads(ln) for ln in skip_log5.read_text(encoding="utf-8").splitlines()]
    assert any(s["file"] == "enc.pptx" and s["reason"] == "encrypted_detected" for s in skipped5), skipped5
    recs5 = [json.loads(ln) for ln in (odir5 / "runs.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(recs5) == len(cand5), "새로 시도한 기록이 없어야 함(재시도 안 함) — " + str(recs5)
    r6 = subprocess.run(
        [sys.executable, "-m", "pipeline.extract.run_all", "--src", str(sdir5), "--out", str(odir5)],
        capture_output=True,
        text=True,
        env=C.child_env(PIPE_PROCS="1"),
        cwd=str(APP_ROOT),
        timeout=60,
    )  # 하위 프로세스(시험) — 덮기 파일(S7e2)
    assert r6.returncode == 0, r6.stderr[-2000:]
    skipped6 = [json.loads(ln) for ln in skip_log5.read_text(encoding="utf-8").splitlines()]
    assert sum(1 for s in skipped6 if s["file"] == "enc.pptx" and s["reason"] == "encrypted_detected") == 1, "여러 실행에 중복 기록 안 됨"
    print("[selftest] SI44③ — 앞 실행 전부 암호 오류면 encrypted_detected 기록·재시도 안 함·중복 기록 없음 통과")


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    selftest()


def test_retry_doubles_limit():
    """10-29 — 시간 초과면 같은 실행에서 제한을 두 배로 한 번 더(가짜 _isolated — 첫 번 TimeoutError, 둘째 성공 / 둘 다 실패)."""
    from unittest import mock

    from pipeline.extract import run_all as RA

    seen = []

    def once(eng, doc, dst, profile, tmo, env=None):
        seen.append(tmo)
        if len(seen) == 1:
            raise TimeoutError(f"문서×엔진 시간 제한 초과({tmo}초)")

    with mock.patch.object(RA, "_isolated", once):
        err, tmo = RA._run_with_retry("pymupdf", Path("a.pdf"), Path("a.json"), "default", 20.0, [], None)
    assert err is None and seen == [20.0, 40.0] and tmo == 40.0, (err, seen)

    seen.clear()
    always = mock.Mock(side_effect=TimeoutError("시간 제한 초과"))
    with mock.patch.object(RA, "_isolated", always):
        err, tmo = RA._run_with_retry("pymupdf", Path("a.pdf"), Path("a.json"), "default", 20.0, [], None)
    assert err and "Timeout" in err and always.call_count == 2 and tmo == 40.0  # 한 번만 더 — 세 번째 없음

    other = mock.Mock(side_effect=RuntimeError("깨짐"))
    with mock.patch.object(RA, "_isolated", other):
        err, _ = RA._run_with_retry("pymupdf", Path("a.pdf"), Path("a.json"), "default", 20.0, [], None)
    assert err and other.call_count == 1  # 시간 초과가 아니면 다시 안 함


def test_run_docs_engines_concurrent():
    """10-29 — 한 문서의 엔진 2개는 동시에(둘이 같이 기다려야 풀리는 장벽 — 차례로 돌면 시간 초과로 깨짐)."""
    import threading

    from pipeline.extract.run_all import _run_docs

    barrier = threading.Barrier(2, timeout=10)
    ran = []

    def job(j):
        barrier.wait()
        ran.append(j[1])

    d = Path("one.pdf")
    _run_docs([(d, "pymupdf", None, "s"), (d, "kreuzberg", None, "s")], job, workers=1)
    assert sorted(ran) == ["kreuzberg", "pymupdf"]


def test_run_procs_doc_shards():
    """10-29 — --procs는 엔진 묶음이 아니라 문서 조각: 조각 수 = min(procs, 문서 수), 자식마다 --shard i/k --procs 1."""
    import argparse
    from unittest import mock

    from common.core import resources
    from pipeline.extract import run_all as RA

    cmds = []
    fake = mock.Mock(side_effect=lambda cmd, **kw: (cmds.append(cmd), mock.Mock(wait=lambda: 0))[1])
    a = argparse.Namespace(procs=4, src="s", out="o", engines="")
    argv = ["run_all", "--src", "s", "--procs", "4", "--engines", "pymupdf"]
    with mock.patch.object(resources, "gated_popen", fake), mock.patch.object(RA, "write_progress"), mock.patch.object(sys, "argv", argv):
        RA.run_procs(a, [Path("a.pdf"), Path("b.pdf"), Path("c.pdf")])
    shards = sorted(c[c.index("--shard") + 1] for c in cmds)
    assert shards == ["0/3", "1/3", "2/3"], shards
    for c in cmds:
        assert c[c.index("--procs") + 1] == "1" and c.count("--procs") == 1 and "--engines" in c  # 엔진 인자는 그대로 넘김


def test_low_priority_children():
    """10-29 — 일괄 파싱 엔진 자식은 낮은 우선순위(OS 분기 한 곳 — pipeline.extract.resources), 끄면(parse MCP 서비스) 아무 인자 없음."""
    import os
    import subprocess

    from pipeline.extract import resources as PR

    assert PR.low_priority_kw(False) == {}
    if os.name == "nt":
        assert PR.low_priority_kw(True) == {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS}
    else:
        assert PR.low_priority_kw(True) == {}  # POSIX는 띄운 뒤 renice_low
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
        try:
            before = os.getpriority(os.PRIO_PROCESS, p.pid)
            PR.renice_low(p.pid, True)
            assert os.getpriority(os.PRIO_PROCESS, p.pid) == min(19, before + PR.LOW_NICE)
        finally:
            p.kill()
            p.wait()
    with pc.PIPE.env(PARSE_LOW_PRIORITY="0"):
        assert pc.cfg().extract.low_priority is False
    assert pc.cfg().extract.low_priority is True  # 기본 켬(일괄 파싱)


def test_kill_group_reaps_grandchild():
    """10-29 — group_kw로 띄운 자식이 손자를 띄워도 kill_group이 묶음째 끝냄(POSIX만 — Windows는 taskkill /T, 여기선 건너뜀)."""
    import os
    import subprocess
    import time

    from pipeline.extract import resources as PR

    if os.name == "nt":
        print("[selftest] kill_group — Windows는 건너뜀(taskkill /T)")
        return
    code = "import subprocess, sys, time; g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); print(g.pid, flush=True); time.sleep(60)"
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, **PR.group_kw())
    gpid = int(p.stdout.readline())
    PR.kill_group(p)
    assert p.returncode is not None

    def alive(pid):
        """살아 있나 — 좀비(죽었고 거둘 부모만 없음: init 없는 컨테이너의 PID 1 — `docker run` without --init)는 죽은 것으로(이미지 관문 10-30)."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        try:
            return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0] != "Z"
        except OSError:
            return True  # /proc 없음(macOS) — kill(0)이 됐으니 살아 있음

    for _ in range(50):  # 손자는 init이 거둠 — 잠깐 기다림
        if not alive(gpid):
            break
        time.sleep(0.1)
    else:
        raise AssertionError(f"손자 {gpid}가 남음")


def test_vlm_child_env_caps_timeout():
    """10-29 M3 — VLM 엔진 자식의 VLM_TIMEOUT = min(models.vlm.timeout, vlm_page_sec) · 쪽당 제한이 더 길면 덮지 않음(None)."""
    from common.config.settings import COMMON
    from pipeline.extract.run_all import _vlm_child_env

    with COMMON.env(VLM_TIMEOUT="180"), pc.PIPE.env(PARSE_VLM_PAGE_SEC="60"):
        env = _vlm_child_env()
        assert env is not None and env["VLM_TIMEOUT"] == "60", env and env.get("VLM_TIMEOUT")
    with COMMON.env(VLM_TIMEOUT="100"), pc.PIPE.env(PARSE_VLM_PAGE_SEC="120"):
        assert _vlm_child_env() is None
