"""pipeline.transform.represent.agent_tools 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.represent.agent_tools --selftest`."""

import json
from pathlib import Path

from common.config.settings import COMMON
from pipeline.transform.represent.agent_tools import TOOL_NAMES, build_tools


def selftest():
    import tempfile

    from common.ai import adk as A

    d = Path(tempfile.mkdtemp())
    doc_path = d / "x.txt"
    doc_path.write_text("고객: 홍길동\n계약 번호: A-123\n단가: 1,000\n", encoding="utf-8")
    out_dir, parse_dir = d / "_agent", d / "parse"  # 둘 다 스크래치 — dev/out/parse(공유)는 안 건드림
    tools, ctx = build_tools("x.txt", doc_path, out_dir, parse_dir=parse_dir)
    assert set(tools) == set(TOOL_NAMES)
    assert ctx["parse_dir"] == str(parse_dir)  # rag_out() 기본값이 아니라 넘긴 parse_dir을 씀

    # P0 재사용(10-07 결정 ②) — 같은 문서·엔진을 두 번 부르면 두 번째는 registry.run을 다시 안 부름
    from pipeline.extract.engines import registry

    calls = []
    orig_run = registry.run
    registry.run = lambda *a, **k: (calls.append(1), orig_run(*a, **k))[1]
    try:
        r1 = tools["parse_text"](["plaintext"])
        assert r1["plaintext"]["ok"] and not r1["plaintext"]["cached"] and len(calls) == 1
        tools2, _ = build_tools("x.txt", doc_path, out_dir, parse_dir=parse_dir)  # 새 세션 — 같은 parse_dir
        r2 = tools2["parse_text"](["plaintext"])
        assert r2["plaintext"]["ok"] and r2["plaintext"]["cached"] and len(calls) == 1  # 재실행 0
        assert (parse_dir / "runs.jsonl").exists() and (parse_dir / "plaintext" / "x.txt.json").exists()
    finally:
        registry.run = orig_run

    sig = tools["inspect_document"]()
    assert sig["format"] == ".txt" and sig["pages"] == 1 and sig["drm"] is None and not sig["is_image_pdf"]

    r = tools["parse_text"](["plaintext"])
    assert r["plaintext"]["ok"] and r["plaintext"]["chars"] > 0
    assert "x.txt 없음" not in json.dumps(r)  # 요약에 원문 전체가 섞여 나오지 않음

    r2 = tools["extract_images"]()
    assert r2["count"] == 0  # .txt엔 그림이 없음(figures()가 모르는 확장자는 [])

    r3 = tools["cross_check"]()
    assert r3["agree"] == 0 and r3["conflicts"] == 0  # 엔진 1개뿐 — 계열 2개 합의 조건을 못 채움

    r4 = tools["choose_representative"]()
    assert r4["engine"] == "plaintext" and r4["candidates"] == ["plaintext"]

    r5 = tools["apply_post"]()
    assert "features" in r5 and r5["figures"] == 0  # .txt엔 그림이 없음 — write_index가 빈 index는 만들어도 PNG는 0개
    assert not list((Path(out_dir) / "_images").rglob("*.png"))  # 공유 저장소 대신 out_dir/_images에만(PNG는 0개라 확인은 목록 비었음으로)

    r6 = tools["finalize"]()
    assert r6["engine"] == "plaintext" and r6["decisions"] >= 5

    # vlm_read — context != "none"은 명시적으로 미구현
    try:
        tools["vlm_read"](context="summary")
        raise AssertionError("context=summary인데 NotImplementedError 안 남")
    except NotImplementedError:
        pass
    # .txt는 스캔이 아니므로 모델 호출 0(안전 경로) — VLM 설정 여부와 무관
    with COMMON.env(VLM_BASE_URL=None, VLM_MODEL=None):  # S7c — 설정 객체만 바꿔 끼움
        r7 = tools["vlm_read"](target="page")
        assert r7["chars"] == 0 and r7["pages"] == 0  # is_scan(.txt) == False — page_text가 즉시 빈 답

        r8 = tools["vlm_read"](target="figure:없음")
        assert "error" in r8  # extract_images가 안 만든 그림 id

    # summarize_document — model="vlm"은 미구현, model="llm"은 LLM 미설정이면 ModelUnavailable을 에러로 담음(네트워크 0)
    try:
        tools["summarize_document"](model="vlm")
        raise AssertionError("model=vlm인데 NotImplementedError 안 남")
    except NotImplementedError:
        pass
    with COMMON.env(LLM_BASE_URL=None, LLM_MODEL=None):  # S7c — 설정 객체만 바꿔 끼움
        r9 = tools["summarize_document"]()
    assert r9["summary"] == "" and "error" in r9
    assert isinstance(A.ModelUnavailable, type)  # 가져오기 확인(위에서 쓴 타입)

    # detect_rotation·ocr_region — 플러밍(모의 OCR 함수로, 실제 RapidOCR 모델 호출은 .venv-parse 실문서 점검에서)
    from PIL import Image

    png_doc = d / "z.png"
    Image.new("RGB", (10, 10), "white").save(png_doc)
    tools2, _ctx2 = build_tools("z.png", png_doc, d / "_agent2")
    import pipeline.extract.prepare as P

    def fake_best_angle(im, probe, min_gain):
        return 90, {0: 1.0, 90: 2.0, 180: 0.0, 270: 0.0}

    orig = P.best_angle
    P.best_angle = fake_best_angle
    try:
        rot = tools2["detect_rotation"](page=1)
        assert rot["angle"] == 90 and rot["scores"]["90"] == 2
    finally:
        P.best_angle = orig

    def fake_ocr_lines(arr):
        return [([[0, 0], [10, 0], [10, 5], [0, 5]], "글자", 0.9)]

    orig2 = P._ocr_lines
    P._ocr_lines = fake_ocr_lines
    try:
        region = tools2["ocr_region"](page=1, bbox=[0, 0, 1, 1])
        assert region["lines"] == 1 and region["chars"] == 2 and region["avg_conf"] == 0.9 and region["preview"] == "글자"
    finally:
        P._ocr_lines = orig2

    print(
        "[selftest] 도구 11개 — inspect·parse_text·extract_images·cross_check·choose_representative·apply_post·"
        "finalize(실제 호출, 네트워크 0) · vlm_read/summarize_document 미구현 분기 · detect_rotation/ocr_region 플러밍"
        "(모의 OCR) 통과"
    )


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
