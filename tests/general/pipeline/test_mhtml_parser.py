"""pipeline.transform.parse.engines.mhtml.parser(엔진 파일 — 엔진 지문) 자기 점검 — S9b(VS9 B-1, D-018)에 모듈 `__main__`에서 옮김(줄 글자 그대로).
옛 명령 `python -m pipeline.transform.parse.engines.mhtml.parser`(반입 판정 목록 밖 — 일반 시험).
⚠️ 이 옮기기는 엔진 지문을 바꾼다(사용자 10-28 — 엔진 파일 옮기기 커밋 하나, 되돌리기는 그 커밋 revert · refactor.md C-52)."""

from pipeline.transform.parse.engines.mhtml.parser import decode_mail_text, parse_mhtml


def test_main():  # 옛 `if __name__ == "__main__":   # 자기점검: HTML 표 + 이미지 1개인 MHT` 몸통
    import tempfile
    from email.mime.image import MIMEImage
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    m = MIMEMultipart("related")
    m["Subject"] = "견적 회신"
    m.attach(
        MIMEText(
            "<html><body><p>단가 안내</p><table><tr><th>항목</th><th>값</th></tr><tr><td>단가</td><td>USD 85 / g</td></tr>"
            "<tr><td>MTOP</td><td>2 batches</td></tr></table><img src='cid:a'></body></html>",
            "html",
            "utf-8",
        )
    )
    m.attach(MIMEImage(b"\x89PNG\r\n\x1a\n" + b"0" * 20, "png"))
    with tempfile.NamedTemporaryFile(suffix=".mht", delete=False) as f:
        f.write(m.as_bytes())
    r = parse_mhtml(f.name)
    assert r["tables"][0]["rows"] == 3 and r["trace"]["images"] == 1 and "단가 안내" in r["text"], r
    print("mhtml self-check OK")

    # SI42 — EML 한글 깨짐 3종 재현(사용자 보고): 선언(widen) → cp949 → utf-8 순 디코드로 구제되는지
    body1 = "안녕 똠 쀍".encode("cp949")  # ① ks_c_5601-1987 선언 + CP949 확장 글자(Python ks_c_5601-1987→euc_kr 별칭이면 그 글자만 깨짐)
    assert decode_mail_text(body1, "ks_c_5601-1987") == "안녕 똠 쀍", decode_mail_text(body1, "ks_c_5601-1987")
    body2 = "안녕하세요 반갑습니다".encode("cp949")  # ② charset 선언 없음 + EUC-KR 바이트
    assert decode_mail_text(body2, None) == "안녕하세요 반갑습니다", decode_mail_text(body2, None)
    body3 = "단가 안내 전체".encode("cp949")  # ③ utf-8 선언인데 실제 EUC-KR(utf-8 strict는 실패 → cp949로)
    assert decode_mail_text(body3, "utf-8") == "단가 안내 전체", decode_mail_text(body3, "utf-8")
    # 엔진 end-to-end(①) — parse_mhtml이 get_content()(선언 charset 그대로) 대신 바이트+decode_mail_text를 쓰는지
    raw_html = "<html><body>안녕 똠 쀍</body></html>".encode("cp949")
    mime = b'Content-Type: text/html; charset="ks_c_5601-1987"\r\nContent-Transfer-Encoding: 8bit\r\nSubject: test\r\n\r\n' + raw_html
    with tempfile.NamedTemporaryFile(suffix=".eml", delete=False) as f2:
        f2.write(mime)
    r2 = parse_mhtml(f2.name)
    assert "똠" in r2["text"] and "쀍" in r2["text"] and "�" not in r2["text"], r2["text"]
    print("decode_mail_text self-check OK — ks_c_5601-1987+cp949 확장·무선언 EUC-KR·utf-8 오선언 3종 구제 + parse_mhtml end-to-end")
