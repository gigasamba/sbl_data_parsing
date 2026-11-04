"""F6(11-03 PC 시험) — 문단 보정(represent._merge_paragraphs)이 다른 엔진 문단으로 바꿔도 대표 본문의 쪽 나눔(\f)을 남김
(전에는 strip()으로 사라져 2쪽 PDF 청크 13/15가 page=None)."""

from pipeline.transform.represent.build_rep import _merge_paragraphs


def test_keeps_page_breaks():
    cases = [  # (대표 본문, 다른 엔진 본문, 기대)
        ("p1 short\n\n\x0cp2 short", "p1 short\n\np2 a much longer paragraph", "p1 short\n\n\x0cp2 a much longer paragraph"),
        ("a\n\nb", "a longer\n\nb", "a longer\n\nb"),  # 쪽 나눔 없으면 그대로 바꿈
        ("\x0cx", "\x0cx longer", "\x0cx longer"),  # 다른 엔진도 쪽 나눔이 있으면 더 붙이지 않음
        (
            "a\n\n…p1 tail\n\x0cp2 head",
            "a\n\n…p1 tail p2 head and more text",
            "a\n\n…p1 tail\n\x0cp2 head",
        ),  # 문단 안 쪽 나눔 — 바꾸지 않음
    ]
    for rep, other, want in cases:
        got, _ = _merge_paragraphs(rep, [other])
        assert got == want, (rep, other, got)
