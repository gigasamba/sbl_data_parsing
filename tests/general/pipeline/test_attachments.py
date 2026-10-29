"""pipeline.transform.represent.attachments 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.represent.attachments`."""

import io
import zipfile
from pathlib import Path

from pipeline import config as pc
from pipeline.transform.represent.attachments import _expand_zip, _max_n, extract, mail_blocks, thread_paragraphs


def selftest():
    import tempfile as T

    d = Path(T.mkdtemp())
    with pc.PIPE.env(PARSE_RAW_ROOT=str(d / "raw_store")):  # S7c — 설정 객체만 바꿔 끼움(raw_root()가 객체로 읽음)
        # 1) xlsx 첨부가 든 합성 .eml — openpyxl(새 단가 표) + email 표준 라이브러리
        from email.mime.application import MIMEApplication
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["품목", "단가"])
        ws.append(["A-1", "USD 85"])
        xbuf = io.BytesIO()
        wb.save(xbuf)

        m = MIMEMultipart()
        m["Subject"] = "새 단가 안내"
        m.attach(MIMEText("본문: 첨부 확인 바랍니다.", "plain", "utf-8"))
        att = MIMEApplication(xbuf.getvalue(), _subtype="xlsx")
        att.add_header("Content-Disposition", "attachment", filename="price.xlsx")
        m.attach(att)
        eml = d / "mail.eml"
        eml.write_bytes(m.as_bytes())

        atts = extract(eml)
        assert len(atts) == 1 and atts[0]["name"] == "price.xlsx"

        blocks, stats = mail_blocks(eml, "본문: 첨부 확인 바랍니다.")
        assert stats["n"] == 1 and stats["parsed"] == 1 and stats["cached"] == 0
        assert stats["sources"] == ["mail.eml#price.xlsx"]
        assert any(b.startswith("[첨부 price.xlsx]") and "85" in b for b in blocks)

        blocks2, stats2 = mail_blocks(eml, "본문: 첨부 확인 바랍니다.")  # 두 번째 — P0 캐시 적중
        assert stats2["parsed"] == 1 and stats2["cached"] == 1
        assert blocks2 == blocks
        print("[selftest] eml → xlsx 첨부 추출·파싱·P0 캐시 재사용 통과")

        # 1-1) pdf 첨부 — stack.json 키가 .pdf_text/.pdf_image라 확장자(.pdf)로는 엔진이 안 잡히던 문제(10-11 gold-human2 mail_attach_pdf)
        import pymupdf

        pdoc = pymupdf.open()
        pdoc.new_page().insert_text((72, 72), "Contract amount 1,234,567 KRW")
        mp = MIMEMultipart()
        mp.attach(MIMEText("본문", "plain", "utf-8"))
        ap = MIMEApplication(pdoc.tobytes(), _subtype="pdf")
        ap.add_header("Content-Disposition", "attachment", filename="c.pdf")
        mp.attach(ap)
        emlp = d / "mailp.eml"
        emlp.write_bytes(mp.as_bytes())
        bp, sp = mail_blocks(emlp, "본문")
        assert sp["parsed"] == 1 and any(b.startswith("[첨부 c.pdf]") and "1,234,567" in b for b in bp), (sp, bp)
        print("[selftest] eml → pdf 첨부(.pdf_text 엔진) 통과")

        # 2) 이미지 첨부(인라인 아님)도 image/* — figures.py 담당, attachments는 건너뜀
        from email.mime.image import MIMEImage

        m2 = MIMEMultipart()
        m2["Subject"] = "그림만"
        m2.attach(MIMEText("본문", "plain", "utf-8"))
        img = MIMEImage(b"\x89PNG" + b"0" * 20, "png")
        img.add_header("Content-Disposition", "attachment", filename="x.png")
        m2.attach(img)
        eml2 = d / "mail2.eml"
        eml2.write_bytes(m2.as_bytes())
        assert extract(eml2) == []
        print("[selftest] 이미지 첨부는 attachments가 건너뜀(figures.py 담당) 통과")

        # 3) 크기·개수 상한
        with pc.PIPE.env(ATTACH_MAX_MB="0.001"):  # 1KB — xlsx(수백 바이트 이상) 넘김 — S7c: 객체만 바꿔 끼움
            _, stats3 = mail_blocks(eml, "본문")
            assert stats3["n"] == 0 and stats3["parsed"] == 0

        m3 = MIMEMultipart()
        m3["Subject"] = "첨부 여러 개"
        for i in range(12):
            a = MIMEApplication(b"x" * 20, _subtype="txt")
            a.add_header("Content-Disposition", "attachment", filename=f"f{i}.txt")
            m3.attach(a)
        eml3 = d / "mail3.eml"
        eml3.write_bytes(m3.as_bytes())
        assert len(extract(eml3)) == _max_n()  # 기본 10 — 12개 중 10개만
        print("[selftest] 크기 상한(ATTACH_MAX_MB)·개수 상한(기본 10) 통과")

        # 4) zip 깊이 1단 — 안의 zip은 더 안 풂
        inner_zip = io.BytesIO()
        with zipfile.ZipFile(inner_zip, "w") as z2:
            z2.writestr("deep.txt", "안쪽")
        outer_zip = io.BytesIO()
        with zipfile.ZipFile(outer_zip, "w") as z1:
            z1.writestr("a.txt", "1단 글자")
            z1.writestr("nested.zip", inner_zip.getvalue())
        entry = {"name": "pack.zip", "bytes": outer_zip.getvalue(), "depth": 0}
        expanded = _expand_zip(entry, 1)
        names = sorted(e["name"] for e in expanded)
        assert names == ["pack.zip#a.txt", "pack.zip#nested.zip"]  # nested.zip은 depth 1에서 cap(1) 도달 — 안 풂
        print("[selftest] zip 첨부 깊이 1단(ATTACH_MAX_DEPTH) 통과")
        # 4-1) zip 폭탄 — 풀린 크기 합이 상한을 넘으면 읽기 전에 멈춤
        bomb = io.BytesIO()
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zb:
            zb.writestr("ok.txt", "작은 파일")
            zb.writestr("big.bin", b"\0" * (3 * 1024 * 1024))  # 압축하면 수 KB, 풀면 3MB
        with pc.PIPE.env(ATTACH_MAX_MB="1"):
            got = _expand_zip({"name": "b.zip", "bytes": bomb.getvalue(), "depth": 0}, 1)
        assert [e["name"] for e in got] == ["b.zip#ok.txt"]  # big.bin은 풀지 않음
        print("[selftest] zip 폭탄 — 풀린 크기 상한 먼저 확인 통과")

        # 5) 인용 스레드 — 영문 "On ... wrote:" · 한글 "보낸 사람:"
        thread = (
            "최신 회신\n\nOn Mon, Jan 5, 2026, Kim Cheolsu <k@x.com> wrote:\n> 이전 제안: USD 80\n>\n"
            "> -----Original Message-----\n> 보낸 사람: Lee Younghee\n> 날짜: 2026-01-03\n> 최초 제안: USD 75"
        )
        tp = thread_paragraphs(thread)
        assert "[인용 Mon, Jan 5, 2026 · Kim Cheolsu]" in tp and "USD 80" in tp
        assert "Lee Younghee" in tp and "2026-01-03" in tp and "USD 75" in tp
        assert thread_paragraphs("인용 없는 본문") == ""
        print("[selftest] 인용 스레드 영문·한글 헤더 단락화 통과")

        # 6) .eml·.msg 아닌 문서 → 빈 블록(본문 불변 보장)
        assert mail_blocks(d / "x.pdf", "본문") == ([], {"n": 0, "parsed": 0, "cached": 0, "sources": []})
        print("[selftest] eml·msg 아닌 문서는 빈 블록 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
