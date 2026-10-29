"""토큰·정규화·색인 본문 규칙 — 구조화(키워드 색인 chunk_term)와 검색(질의 토큰)이 반드시 같아야 함."""
import os
import re
import unicodedata


def normalize_value(v):
    """NFKC → 소문자 → 제로폭 제거 → 숫자 사이 쉼표 제거 → 공백 전부 제거(공백 무시 매칭용)."""
    v = unicodedata.normalize("NFKC", str(v)).lower()
    v = re.sub(r"[​‌‍﻿]", "", v)
    v = re.sub(r"(?<=\d),(?=\d)", "", v)
    return re.sub(r"\s+", "", v)


_NUM_ONLY = re.compile(r"[-+]?[\d.]+")   # 검토 지적(W20b) — 음수·부호 값도 숫자 경계 판정


def no_digit_boundary_hit(key, haystack):
    """key(이미 정규화된 비교 문자열 — 쉼표·공백 지움, 소문자)가 haystack 안에 있는지 — W20b(금지 값 거짓 양성):
    key가 숫자·점으로만 되어 있으면 양옆에 숫자(또는 소수점 뒤 숫자) 이어짐이 없을 때만 '있음'으로 친다
    (예: "3,360"이 "3,360,000"·"13,360" 안에 끼어 있는 걸 거짓 양성으로 안 셈 · "3,360원"·문장 끝 "3,360."은 그대로 맞음).
    글자 값(숫자·점 아닌 글자가 하나라도 있으면)은 경계 없이 그대로 부분 문자열 — score_gold.must_not_hits·
    stack_matrix._must_not_violations 공용(둘 다 같은 함수를 거쳐야 같은 결과 — enforcement §2)."""
    if not key:
        return False
    if not _NUM_ONLY.fullmatch(key):
        return key in haystack
    i = haystack.find(key)
    while i != -1:
        j = i + len(key)
        before_digit = i > 0 and (haystack[i - 1].isdigit() or (haystack[i - 1] in ".," and i > 1 and haystack[i - 2].isdigit()))
        after_digit = j < len(haystack) and (haystack[j].isdigit() or (haystack[j] in ".," and j + 1 < len(haystack) and haystack[j + 1].isdigit()))
        if not before_digit and not after_digit:
            return True
        i = haystack.find(key, i + 1)
    return False


_HTML_SUP = re.compile(r"<\s*sup\s*>(.*?)<\s*/\s*sup\s*>", re.I | re.S)
_HTML_SUB = re.compile(r"<\s*sub\s*>(.*?)<\s*/\s*sub\s*>", re.I | re.S)
_UNI_SUP = re.compile("[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+")
_UNI_SUB = re.compile("[₀₁₂₃₄₅₆₇₈₉₊₋]+")
_SUP_TABLE = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
_SUB_TABLE = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋", "0123456789+-")


def supsub_mark(s, plain=False):
    """첨자 표기(AD37·SI17 — 엔진마다 `<sup>`·`<sub>`·⁶·₂로 다름)를 ^·_ 하나로.
    후보정(modules/parse/post/supsub.py)·채점(cli/score_gold.py)이 같이 쓴다 — 각자 규칙을 만들면 또 벌어짐(SI17 재발 방지).
    plain=True(채점 전용, 독립 검토 MAJOR 2) — 마커 없이 내용만 남긴다. 각주형('값: <sup>6</sup>'처럼 마커 앞뒤가
    영숫자가 아닌 경우)은 기본값이 ^·_를 붙인 뒤 지우는 정규식이 공백·구두점 앞뒤에서 마커를 못 지워 남기므로
    채점(score_gold.canon)은 이 옛 동작(마커 자체가 없던 — 내용만 비교)과 바이트 동일하게 plain을 쓴다."""
    if not s:
        return s
    if plain:
        s = _HTML_SUP.sub(lambda m: m.group(1), s)
        s = _HTML_SUB.sub(lambda m: m.group(1), s)
        s = _UNI_SUP.sub(lambda m: m.group(0).translate(_SUP_TABLE), s)
        s = _UNI_SUB.sub(lambda m: m.group(0).translate(_SUB_TABLE), s)
        return s
    s = _HTML_SUP.sub(lambda m: "^" + m.group(1), s)
    s = _HTML_SUB.sub(lambda m: "_" + m.group(1), s)
    s = _UNI_SUP.sub(lambda m: "^" + m.group(0).translate(_SUP_TABLE), s)
    s = _UNI_SUB.sub(lambda m: "_" + m.group(0).translate(_SUB_TABLE), s)
    return s


# T1(search.md) — 검색 토큰 숫자·단위 정규화(TOKEN_NUM_NORM, 기본 켬, =0으로 끔 — AD25와 같은 끔 규칙, 단 AD25는
# 파싱 교차 대조용 common/meaning.py 쪽, 이건 검색 색인·질의 공용 tokens() 쪽이라 따로 둔다).
# 공백·쉼표·작은따옴표 3자리 묶음(유효 그룹만 — AD25 meaning.py _SPACE_GROUPED·_VALID_GROUPED와 같은 조건, 4,30,000류
# 무효 묶음은 앞뒤 lookaround가 걸러 그대로 둔다) + 유럽식 마침표 '두 묶음 이상'(4.300.000류, 소수점은 마침표 하나뿐이라
# 모호하지 않음). 마침표 한 묶음(430.000)은 소수와 모호해 AD25와 같이 그대로 둔다(별도 토큰, 조용히 안 합침).
_NUM_SEP_GROUPED = re.compile(r"(?<![\d,.'])\d{1,3}(?:[ ,']\d{3})+(?![\d,.'])")
_NUM_DOT_MULTI = re.compile(r"(?<![\d,.'])\d{1,3}(?:\.\d{3}){2,}(?![\d,.'])")
_NUM_UNIT_SPLIT = re.compile(r"^(\d[\d.]*\d|\d)([a-z]+)$")   # 숫자+단위 붙음(10ppm·2000l) — 가산 분리(기존 붙은 토큰은 유지)


def _num_norm_enabled():
    """T1 TOKEN_NUM_NORM(기본 켬, =0으로 끔) — 단일 읽기 지점."""
    return str(os.environ.get("TOKEN_NUM_NORM", "1")).strip().lower() not in ("", "0", "none", "false")


def _fuse_num_seps(s):
    """T1(a) — 숫자 사이 천 단위 구분자(쉼표·공백·작은따옴표·유효 유럽식 마침표 다중 묶음)를 지운다. _TOK가 쉼표·공백에서
    토큰을 쪼개 '2,000'이 '2000'과 다른 토큰 쌍('2','000' vs '2000')이 되던 것(색인·질의 숫자 표기 불일치)을 막는다."""
    s = _NUM_SEP_GROUPED.sub(lambda m: re.sub(r"[ ,']", "", m.group(0)), s)
    return _NUM_DOT_MULTI.sub(lambda m: m.group(0).replace(".", ""), s)


_TOK = re.compile(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣\-.]*")
_SPLIT = re.compile(r"[a-z0-9][a-z0-9\-.]*[a-z0-9]|[a-z0-9]|[가-힣]+")
_IDTOK = re.compile(r"[a-z]{1,8}(?:-[a-z]{1,8})*-?\d[a-z0-9\-.]*")
_SUPTOK = re.compile(r"[a-z0-9]+(?:[\^_/][a-z0-9]+)+")   # 10^6·m/s^2·h_2o류 — 첨자 토큰(W19 T1)
_EN_WORD = re.compile(r"^[a-z]+$")
# engine-qa BLOCK 4(G16) — 낱말 열거 대신 접미사 규칙: '-us'(status·campus·census·radius·surplus) · '-sis'(analysis·
# hypothesis·emphasis·crisis·basis) · '-ss'(class·business·process) · '-ics'(statistics·physics 류)로 끝나는 말은
# 복수가 아닌데 '-s'로 끝나 보여 단수화하면 틀린 토큰이 된다 — 아예 손대지 않음(짧은 말 len<4도 길이 조건으로 제외).
_EN_NO_SINGULAR_SUFFIX = ("us", "sis", "ss", "ics")
# 접미사 규칙에 안 걸리는 -s 단수·불변 단어(engine-qa 10-08 — news→new 같은 실존 단어 오탐 방지)
_EN_NO_SINGULAR = frozenset({"this", "axis", "news", "always", "series", "species", "lens", "gas", "bias",
                             "chaos", "canvas", "atlas", "alias", "means", "perhaps", "whereas", "towards"})


def _en_singular(word):
    """G16 — 영어 복수 → 단수 하나(색인·질의 공용 — 가산만, 기존 복수 토큰은 그대로 남음). 간단 규칙만:
    -ies→-y(companies→company) · -ches/-shes/-xes/-zes/-ses→그 둘 지움(batches→batch·boxes→box·viruses→virus) ·
    그 외 -s→지움(lots→lot·months→month). 길이 4 미만·영문자 아닌 토큰·_EN_NO_SINGULAR_SUFFIX 접미사는 건드리지 않음(None)."""
    if len(word) < 4 or not _EN_WORD.fullmatch(word) or word.endswith(_EN_NO_SINGULAR_SUFFIX) or word in _EN_NO_SINGULAR:
        return None
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "xes", "zes", "ses")):
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return None


def tokens(s):
    """BM25용 토큰 — 한글 조사 대응 보조 bigram 포함 + 영어 단·복수 정규화(G16, SEARCH_EN_STEM=0으로 끔, 기본 켬)
    + T1 숫자·단위 정규화(TOKEN_NUM_NORM=0으로 끔, 기본 켬 — 꺼지면 이 함수 전체가 바이트 동일, __main__ 자기점검으로 확인)."""
    s = str(s)
    norm = _num_norm_enabled()
    if norm:
        s = _fuse_num_seps(unicodedata.normalize("NFKC", s))   # 전각·호환 문자(℃→°C·２，０００→2,000) + 천 단위 구분자 정리
    low = s.lower()
    toks = _TOK.findall(low)
    out = list(toks)
    for t in toks:
        if not re.search(r"[가-힣]", t):
            continue
        parts = _SPLIT.findall(t) if re.search(r"[a-z0-9]", t) else [t]
        if len(parts) > 1:
            # 'd-2024-190의'·'usd160이며'처럼 ID·숫자에 조사가 붙은 덩어리 → 영문·숫자 부분과 한글 부분을 따로도(정확한 ID 일치)
            out += parts
        for p in parts:                                   # 보조 bigram은 한글 부분에만(숫자 조각 bigram은 아무 문서와 겹침)
            if re.fullmatch(r"[가-힣]+", p) and len(p) > 2:
                out += [p[i:i + 2] for i in range(len(p) - 1)]
    # ^·_로 이어진 덩어리(10^6·m/s^2·H_2O)는 기존 분리 토큰에 더해 통짜로도(첨자가 BM25에서 흩어지지 않게, 가산만·기존 분리는 유지)
    out += [m for m in _SUPTOK.findall(low) if "^" in m or "_" in m]
    if os.environ.get("SEARCH_EN_STEM", "1") != "0":   # G16 — batches·lots·months처럼 영어 복수가 질문 단수형과 안 맞던 것(가산만)
        out += [b for t in toks for b in (_en_singular(t),) if b]
    if norm:   # T1(d) — 숫자+단위 붙음(10ppm·2000l)을 가산 분리(기존 붙은 토큰은 그대로 유지, 글로서리 units.csv 메모와 같은 규칙)
        for t in toks:
            m = _NUM_UNIT_SPLIT.match(t)
            if m:
                out += [g for g in m.groups() if g]
    return out


def id_terms(terms):
    """질의 토큰 중 ID 모양(D-2024-190 · LOT-2025-324 · Q-2026-351 · PO12345) — 정확히 일치하는 청크를 검색 1순위로(메타 필터 대용)."""
    return sorted({t for t in terms if len(t) >= 5 and _IDTOK.fullmatch(t) and re.search(r"\d{2,}", t)})


def index_text(c):
    """검색 색인용 본문 = 머리말 한 줄 + 청크 본문(G9). 표시·근거 본문은 chunk_text 그대로."""
    return (c["head"] + "\n" + c["chunk_text"]) if c.get("head") else c["chunk_text"]

