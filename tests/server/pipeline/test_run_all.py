"""pipeline.extract.run_all 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.extract.run_all --selftest`."""

import json
import sys
from pathlib import Path

from common.config import settings as C
from common.core.paths import APP_ROOT
from pipeline import config as pc
from pipeline.extract.engines import registry
from pipeline.extract.run_all import (
    _default_procs,
    _is_scan_pdf,
    _sha,
    _stamp_provenance,
    engine_code_fp,
    engines_for_doc,
    p0_key,
    p0_status,
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
    pdf_cands, doc_cands = registry.engines_for(".pdf"), registry.engines_for(".doc")
    assert "pymupdf" in pdf_cands and "kreuzberg" in pdf_cands and len(pdf_cands) > 2  # 좁혀짐을 보려면 전체가 2개보다 많아야
    stack_parse = {
        ".pdf_text": ["pymupdf", "kreuzberg"]
    }  # .pdf_image 키 없음 — 아래서 _ocr_fallback_needed가 안 불림(extra가 빈 목록이라 단락 평가)
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

    # 독립 검토 BLOCK 1(2026-10-07) — 안전판: .pdf_text로 판정된 혼합 PDF(글자 쪽 3 + 스캔 쪽 1)도 stack에서 OCR 엔진 포함
    import io
    import tempfile

    import fitz
    from PIL import Image

    tmp = Path(tempfile.mkdtemp())
    mixed = tmp / "mixed.pdf"
    mdoc = fitz.open()
    for _ in range(3):
        mdoc.new_page(width=400, height=600).insert_text((50, 50), "본문 글자가 충분히 있는 쪽 " * 5)
    buf = io.BytesIO()
    Image.new("RGB", (400, 600), "gray").save(buf, "PNG")
    mdoc.new_page(width=400, height=600).insert_image(fitz.Rect(0, 0, 400, 600), stream=buf.getvalue())
    mdoc.save(mixed)
    mdoc.close()
    with pc.PIPE.env(
        PARSE_RAW_ROOT=str(tmp / "raw")
    ):  # S7c — 설정 객체(shared/postprocess.raw_root가 읽음) · page_signals 캐시 위치 — 운영 raw/ 안 건드림
        stack_pi = {".pdf_text": ["pymupdf"], ".pdf_image": ["rapidocr_ko", "qwen_vlm"]}
        out_eng = engines_for_doc(mixed, "stack", stack_pi, {mixed.name: ".pdf_text"}, set())
        assert "pymupdf" in out_eng and "rapidocr_ko" in out_eng and "qwen_vlm" in out_eng, out_eng  # 스캔 쪽 1장 감지 → OCR·VLM 합침
        # pdf_image 키가 없으면(합칠 게 없음) 단락 평가로 scan_pages 호출 자체를 안 함 — 글자 전용 문서와 동작 같음
        assert engines_for_doc(mixed, "stack", {".pdf_text": ["pymupdf"]}, {mixed.name: ".pdf_text"}, set()) == [
            e for e in pdf_cands if e == "pymupdf"
        ]
        # 신호 계산 실패(진짜 PDF가 아님) — 안전하게 OCR 포함
        bogus = tmp / "bogus.pdf"
        bogus.write_bytes(b"not a real pdf")
        out_bogus = engines_for_doc(bogus, "stack", stack_pi, {bogus.name: ".pdf_text"}, set())
        assert "rapidocr_ko" in out_bogus and "qwen_vlm" in out_bogus, out_bogus
    print("[selftest] PE1 독립 검토 BLOCK 1 — .pdf_text 안 스캔 쪽(또는 신호 계산 실패) → .pdf_image 엔진 합침 통과")

    # SI9 남음 — 스캔 PDF(전체 쪽 글자층 20자 미만)도 이미지 파일처럼 job_timeout 면제 대상(_is_scan_pdf)
    scan_pdf = tmp / "scan.pdf"
    sdoc = fitz.open()
    pg = sdoc.new_page(width=400, height=600)
    buf3 = io.BytesIO()
    Image.new("RGB", (400, 600), "gray").save(buf3, "PNG")
    pg.insert_image(fitz.Rect(0, 0, 400, 600), stream=buf3.getvalue())
    sdoc.save(scan_pdf)
    sdoc.close()
    assert _is_scan_pdf(scan_pdf) is True
    assert _is_scan_pdf(mixed) is False  # 글자 쪽이 섞여 있음 — 문서 전체는 스캔 아님
    assert _is_scan_pdf(tmp / "없음.pdf") is False  # 신호 계산 실패 — 안전하게 False(기존 동작, 이미지 파일만 면제)
    print("[selftest] SI9 — _is_scan_pdf(스캔 PDF 면제·혼합/실패는 False) 통과")

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

    # SI44③ — phase 1 실패 엔진 전부가 암호 오류면(엔진마다 메시지가 달라도) encrypted_detected로 적고 다음 phase 재시도 안 함
    sdir5, odir5 = Path(_tf.mkdtemp()), Path(_tf.mkdtemp())
    doc5 = sdir5 / "enc.pptx"
    doc5.write_bytes(b"fake pptx")
    cand5 = registry.engines_for(".pptx")
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
        [sys.executable, "-m", "pipeline.extract.run_all", "--src", str(sdir5), "--out", str(odir5), "--phase", "2"],
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
    assert len(recs5) == len(cand5), "phase 2에서 새로 시도한 기록이 없어야 함(재시도 안 함) — " + str(recs5)
    r6 = subprocess.run(
        [sys.executable, "-m", "pipeline.extract.run_all", "--src", str(sdir5), "--out", str(odir5), "--phase", "3"],
        capture_output=True,
        text=True,
        env=C.child_env(PIPE_PROCS="1"),
        cwd=str(APP_ROOT),
        timeout=60,
    )  # 하위 프로세스(시험) — 덮기 파일(S7e2)
    assert r6.returncode == 0, r6.stderr[-2000:]
    skipped6 = [json.loads(ln) for ln in skip_log5.read_text(encoding="utf-8").splitlines()]
    assert sum(1 for s in skipped6 if s["file"] == "enc.pptx" and s["reason"] == "encrypted_detected") == 1, (
        "여러 phase 호출에 중복 기록 안 됨"
    )
    print("[selftest] SI44③ — phase 1 전부 암호 오류면 encrypted_detected 기록·다음 phase 재시도 안 함·중복 기록 없음 통과")


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    selftest()
