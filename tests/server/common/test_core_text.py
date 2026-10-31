"""common.core.text(인계 파일 — FINGERPRINT) 자기 점검 — S9(D-018)에 모듈 `__main__`에서 옮김(줄 글자 그대로). 옛 사례 `python -m common.core.text`.
⚠️ 이 옮기기는 인계 지문(FINGERPRINT)을 바꾼다(사용자 10-28 — 인계 파일 옮기기 커밋 하나, 되돌리기는 그 커밋 revert · refactor.md C-52)."""

from common.config.settings import COMMON
from common.core.text import _en_singular, supsub_mark, tokens


def test_main():  # 옛 `if __name__ == "__main__":   # 자기점검: 첨자 토큰(T1)이 기존 분리 토큰에 더해 통짜로도 남는지` 몸통
    t = tokens("속도는 10^6 m/s^2, H_2O 농도")
    assert "10^6" in t and "m/s^2" in t and "h_2o" in t, t
    assert "10" in t and "6" in t and "h" in t, t  # 기존 분리는 그대로(가산만, 회귀 없음)
    assert tokens("D-2024-190 계약") == tokens("D-2024-190 계약")  # 결정성(같은 입력 같은 출력)
    print("text self-check OK")

    # G16(SI43) — 영어 단·복수 정규화(가산만: 기존 복수 토큰은 그대로, 단수형이 더해짐)
    tg = tokens("12 batches were produced over 6 months in 3 lots")
    assert "batches" in tg and "batch" in tg, tg
    assert "months" in tg and "month" in tg, tg
    assert "lots" in tg and "lot" in tg, tg
    tg2 = tokens("supply companies and storage boxes")
    assert "companies" in tg2 and "company" in tg2, tg2  # -ies → -y
    assert "boxes" in tg2 and "box" in tg2, tg2  # -xes → 둘 지움
    tg3 = tokens("current status of the business process")  # -us·-ss류는 단수형이 더해지지 않음(오탐 방지)
    assert "statu" not in tg3 and "busines" not in tg3 and "proces" not in tg3, tg3
    assert tokens("batch 1") == tokens("batch 1")  # 결정성(같은 입력 같은 출력)
    with COMMON.env(SEARCH_EN_STEM="0"):  # op-09 — 인계 파일도 설정 객체로 읽음
        tg4 = tokens("12 batches")
        assert "batch" not in tg4 and "batches" in tg4, tg4  # 끔 스위치 — 옛 동작과 바이트 동일
    print("[selftest] G16 — 영어 단·복수 정규화(SEARCH_EN_STEM, =0이면 바이트 동일) 통과")

    # engine-qa BLOCK 4 — 낱말 열거 대신 접미사 규칙(-us·-sis·-ss·-ics): census·radius·surplus(-us)·hypothesis·emphasis(-sis)는
    # 복수가 아닌데 '-s'로 끝나 보여도 단수화 토큰이 더해지지 않아야 함(가짜 단수형 'censu'·'radiu'·'surplu'·'hypothesi'·'emphasi' 없음)
    assert _en_singular("census") is None and _en_singular("radius") is None and _en_singular("surplus") is None
    assert _en_singular("hypothesis") is None and _en_singular("emphasis") is None
    tg5 = tokens("census radius surplus hypothesis emphasis")
    assert not ({"censu", "radiu", "surplu", "hypothesi", "emphasi"} & set(tg5)), tg5
    assert _en_singular("statistics") is None  # -ics
    assert _en_singular("viruses") == "virus"  # 진짜 복수(-ses)는 그대로 단수화됨(회귀 아님)
    for w in ("news", "axis", "this", "series", "species", "always"):
        assert _en_singular(w) is None, w  # 실존 단어 오탐 방지(engine-qa 10-08)
    print("[selftest] engine-qa BLOCK 4 — 접미사 규칙(-us·-sis·-ss·-ics)으로 census·radius·hypothesis 등 오탐 방지 통과")

    # AD37 — 엔진마다 다른 첨자 표기(<sup>·<sub>·⁶·₂)를 ^·_ 하나로
    assert supsub_mark("10<sup>6</sup> m") == "10^6 m"
    assert supsub_mark("CO<sub>2</sub>") == "CO_2"
    assert supsub_mark("10⁶ CO₂") == "10^6 CO_2"  # 유니코드 위/아래첨자 숫자 → ^·_
    assert supsub_mark("10^6 CO_2") == "10^6 CO_2"  # 이미 ^·_면 그대로(중복 처리 안 됨)
    assert supsub_mark("") == ""
    print("[selftest] AD37 — 첨자 표기 통합(supsub_mark) 통과")

    # 독립 검토 MAJOR 2 — plain=True(채점용)은 마커 없이 내용만(각주형처럼 마커 앞뒤가 영숫자가 아니어도 안 남음)
    assert supsub_mark("값: <sup>6</sup>", plain=True) == "값: 6"
    assert supsub_mark("(참고 <sup>a</sup>)", plain=True) == "(참고 a)"
    assert supsub_mark("<sup>6</sup>항목", plain=True) == "6항목"
    assert supsub_mark("10⁶ CO₂", plain=True) == "106 CO2"
    print("[selftest] 독립 검토 MAJOR 2 — plain=True 각주형 마커 잔류 없음 통과")

    # T1(search.md) — 숫자 정규화: 쉼표·공백·작은따옴표 천 단위 구분자 → 붙임꼴과 같은 토큰
    assert "2000" in tokens("2,000") and "2000" in tokens("2000")
    assert "430000" in tokens("430,000") and "430000" in tokens("430 000") and "430000" in tokens("430000")
    assert "1000" in tokens("1'000")
    assert "4300000" in tokens("4.300.000")
    t_invalid = tokens("4,30,000")
    assert "430000" not in t_invalid and {"4", "30", "000"} <= set(t_invalid), t_invalid
    t_ambig = tokens("430.000")
    assert t_ambig == ["430.000"], t_ambig
    assert tokens("97.3%") == tokens("97.3 %")
    print("[selftest] T1(a) number thousands-separator normalization OK")

    assert tokens("35℃") == tokens("35°C") == ["35", "c"]
    assert "2000" in tokens("２，０００")
    print("[selftest] T1(c) NFKC (fullwidth/compat chars) OK")

    t_ppm = tokens("10ppm")
    assert {"10ppm", "10", "ppm"} <= set(t_ppm), t_ppm
    t_l = tokens("2000l")
    assert {"2000l", "2000", "l"} <= set(t_l), t_l
    assert "d-2024-190" in tokens("D-2024-190") and "d-2024-190" not in t_l
    print("[selftest] T1(d) number+unit split (additive) OK")

    with COMMON.env(TOKEN_NUM_NORM="0"):
        t_off = tokens("2,000")
        assert "2000" not in t_off and set(t_off) == {"2", "000"}, t_off
        assert tokens("35℃") != tokens("35°C")
        assert tokens("10ppm") == ["10ppm"]
    print("[selftest] T1 TOKEN_NUM_NORM=0 byte-identical OK")
