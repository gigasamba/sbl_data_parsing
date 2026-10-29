"""pipeline.transform.figures.figures_resume 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.figures.figures_resume --selftest`."""

import json
from pathlib import Path

from pipeline import config as pc
from pipeline.transform.figures import figures as fig_mod
from pipeline.transform.figures.figures_resume import bump_parse_mark, capped_docs, resume_one
from pipeline.transform.represent.represent import apply_post


def selftest():
    """capped.jsonl 목록·대표 결과 갱신·끝 표시 run_id 갱신(VLM 네트워크 호출 없음 — 캐시만)."""
    import io
    import os  # 시험 그림 바이트(os.urandom)용 — 환경변수 아님
    import tempfile

    d = Path(tempfile.mkdtemp())
    pd = d / "parse"
    (pd / "_rep").mkdir(parents=True)
    (pd / "pymupdf").mkdir(parents=True)
    doc_file = d / "a.txt"
    doc_file.write_text("본문", encoding="utf-8")
    (pd / "pymupdf" / "a.txt.json").write_text(json.dumps({"text": "원본 본문"}, ensure_ascii=False), encoding="utf-8")
    rep = {
        "text": "원본 본문",
        "rep": {"engine": "pymupdf", "source": {"path": str(doc_file), "sha256": "x" * 64}},
        "post": {"features": []},
    }
    (pd / "_rep" / "a.txt.json").write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    _env = pc.PIPE.env(PARSE_IMAGES_ROOT=str(pd / "_images"))  # S7c — 설정 객체만 바꿔 끼움(os.environ 안 건드림)
    _env.__enter__()
    try:
        assert capped_docs() == []  # capped.jsonl 자체가 없음 — 빈 목록(오류 아님)
        fig_mod.record_capped("a.txt", "x" * 64, 3, 1, ["a.txt#p0#i2"])
        assert capped_docs() == [
            {"doc": "a.txt", "doc_key": "x" * 64, "total": 3, "vlm": 1, "skipped": 1, "skipped_ids": ["a.txt#p0#i2"], "at": fig_mod.NOW}
        ]
        assert capped_docs("없는문서") == []
        ok, n_figs, remaining = resume_one({"doc": "a.txt"}, pd, 5)  # figures 기능이 꺼진(features=[]) 문서 — 그림 호출 없이도 안전
        assert ok and n_figs == 0
        rep2 = json.loads((pd / "_rep" / "a.txt.json").read_text(encoding="utf-8"))
        assert rep2["text"] == "원본 본문" and rep2["post"]["features"] == []  # PARSE_POST=none과 같은 불변 경로
        print("[selftest] capped.jsonl 목록 · 대표 결과 갱신(기능 없음 — 본문 불변) 통과")

        (pd / "_rep" / "_DONE.json").write_text(json.dumps({"module": "parse", "run_id": "old-id"}, ensure_ascii=False), encoding="utf-8")
        rid = bump_parse_mark(pd)
        assert rid and rid != "old-id"
        assert bump_parse_mark(d / "없음") is None
        print("[selftest] _rep/_DONE.json run_id 갱신 통과")

        # figures 기능을 켠 문서 — 실제 build_records를 거쳐 capped.jsonl이 완전히 비워지는지(AD21③ 전체 경로)
        import docx as _docx
        from PIL import Image

        doc2_file, doc2 = d / "b.docx", _docx.Document()
        png1, png2 = io.BytesIO(), io.BytesIO()
        Image.frombytes("RGB", (80, 80), os.urandom(80 * 80 * 3)).save(png1, "PNG")
        Image.frombytes("RGB", (80, 80), os.urandom(80 * 80 * 3)).save(png2, "PNG")
        doc2.add_paragraph().add_run().add_picture(png1)
        doc2.add_paragraph().add_run().add_picture(png2)
        doc2.save(doc2_file)
        (pd / "pymupdf" / "b.docx.json").write_text(json.dumps({"text": "b 원본 본문"}, ensure_ascii=False), encoding="utf-8")
        rep_b = {
            "text": "b 원본 본문",
            "rep": {"engine": "pymupdf", "source": {"path": str(doc2_file), "sha256": "y" * 64}},
            "post": {"features": ["figures"]},
        }
        (pd / "_rep" / "b.docx.json").write_text(json.dumps(rep_b, ensure_ascii=False), encoding="utf-8")
        with pc.PIPE.env(VLM_FIGURES_MAX="1"):
            apply_post({"text": "b 원본 본문", "rep": rep_b["rep"]}, "b.docx", doc2_file, frozenset({"figures"}))
        assert capped_docs("b.docx") != []  # 상한 1로 그림 1개가 걸림
        ok2, n_figs2, remaining2 = resume_one({"doc": "b.docx"}, pd, 5)
        assert ok2 and n_figs2 == 2 and remaining2 == 0  # 상한을 올려 둘 다 처리 — capped.jsonl에서 지워짐
        assert capped_docs("b.docx") == []
        print("[selftest] figures 기능 켠 문서 — 상한 해제 후 capped.jsonl 비워짐(전체 경로) 통과")
    finally:
        _env.__exit__(None, None, None)


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
