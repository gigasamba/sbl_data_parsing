"""pipeline.transform.represent.figure_context 시험."""

from pipeline.transform.represent.figure_context import link_context, render, value_check


def selftest():
    f = {"before": [], "after": ["그림 2. 배치별 titer"], "near": []}
    doc_text = "배치 실적은 그림 2와 같다 B-05가 4.1 g/L로 가장 높고 B-04는 3.9였다."  # 문장 안에 마침표+공백 없음(쪼개지지 않게)
    ctx = link_context(f, doc_text)
    assert ctx["caption"] == "그림 2. 배치별 titer" and ctx["caption_source"] == "아래 줄"
    assert any("B-05" in m for m in ctx["mentions"])
    rec = {"values": [{"label": "B-05", "value": "4.1"}, {"label": "B-04", "value": "3.8"}], "text": ""}
    check = value_check(rec, ctx["mentions"])
    assert check["agree"] == {"B-05": "4.1"} and check["conflict"] == {"B-04": {"그림": "3.8", "본문": "3.9"}}
    text = render({**f, "image_id": "d#p1#i1"}, {"kind": "그래프", "summary": "요약", "text": "글자"}, ctx, check)
    assert "[그림 d#p1#i1]" in text and "값 충돌(사람 확인): B-04" in text and "캡션(아래 줄)" in text
    print("[selftest] 캡션 연결·값 확인/충돌·렌더 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
