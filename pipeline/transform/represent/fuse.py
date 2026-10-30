"""AD29 P1 — 대표 결과를 '문서 단위 선택'에서 '조각 단위 융합'으로(맞추기+투표, 모델 호출 0).

설계(backlog dev/docs/backlog/parse.md AD29): ① 조각 나누기 = 줄·표 칸·라벨:값 · 엔진 간 같은 자리 맞추기 =
좌표가 있으면 좌표, 없으면 쪽별 순서 정렬(정규화 글자 비교, OCR 앙상블 ROVER 방식) ② 조각별 투표 = 점수
= 출처 신뢰도(원문 추출 > VLM > OCR) × 형식 타당성(3자리 쉼표 묶음·깨짐 비율) + 동점이면 대표 엔진 가산점,
결과마다 출처(동의 엔진·탈락 후보) 기록. ③(좌표 영역만 다시 읽기)는 범위 밖(재판독 P2·P3는 pl-34 10-30에 지움).

④(사전·그래프 타당성, AD29 ④)·AD26 2:2 동점 판정을 이 모듈(P1)에 더함(10-08 조각 대표값 마무리, engine-qa
CONCERN 반영 10-08 2차):
  - `term_plausibility()` — 조각이 용어 사전(`common/terms.load_glossary`)·고객 명부(`common/terms._aliases`)
    표기와 근접(오탈자 수준)하면 가산점. 완전히 같으면(이미 정식 표기) 가산 없음 — **원문을 사전 표기로 바꿔
    쓰지 않는다**(새 이름 오교정 방지, AD29 ④ 원칙), 투표 점수만 거든다. 업무 관계 그래프(AD28 ②③ 고객-계약
    -제품 개체·관계)는 아직 없어(구조화 단계 과제 — 파싱이 그 결과를 당겨 쓰면 레이어 역행) 그 대신 **문서
    안 교차 언급**(같은 정규화 값이 서로 다른 라벨 자리에도 나오면 우연한 오독일 확률이 낮다)을 그래프 타당성의
    가벼운 대역으로 쓴다 — `_doc_value_graph()`. **한계(engine-qa 10-08 ③)**: 엔진 구분이 없어 같은 엔진이
    자기 추출 오류를 여러 자리에 반복해도(예: 한 엔진이 같은 틀린 값을 표 세 칸에 똑같이 잘못 읽음) 교차 언급
    으로 오인해 가산할 수 있다 — 독립적인 다른 엔진·다른 쪽 출처가 아니라 "같은 엔진의 자기 반복"과 "서로
    다른 출처의 교차 확인"을 구분하지 않음(AD28 업무 그래프가 생기면 엔진이 아니라 개체 단위로 다시 판단).
  - `format_plausibility(text, locale_pref)` — AD26 (c) 문서 언어권 표기: 쉼표·마침표 3자리 묶음 둘 다 유효한
    '묶음 모양'으로 인정하되, 문서 안에서 더 흔한 구분자(`_doc_locale_pref()`, 다수 없으면 가산 없음)에 추가
    가산 — 두 표기(430,000/430.000)가 신뢰도·형식에서 똑같이 나올 때 로캘 관행으로 갈린다. **한계·일부 수정
    (engine-qa 10-08 ④)**: `_doc_locale_pref()`의 로캘 **집계**는 마침표 쪽만 2묶음 이상(`\\d(\\.\\d{3}){2,}`,
    예 1.234.567)일 때만 증거로 센다 — 1묶음(430.000·0.500류)은 소수점인지 천 단위인지 그 자체로 모호해
    집계에서 뺀다(개별 조각 채점 `format_plausibility`는 여전히 1묶음도 '묶음 모양'으로 인정 — 그 부분은 안
    바꿈, 거기서 모호함은 AD26 (d) VLM 선택형으로 넘긴다). 0.500처럼 순수 소수인 값까지 로캘 증거로 잘못
    세는 문제의 1차 완화 — 완전한 해결(소수점 자리수·문맥으로 판별)은 더 큼.
  - `vote_fragment()` 반환에 `"split"`(bool)·`"resolved_by"`("trust"|"heuristic"|None) — **split·resolved_by는
    항상 계산**(신호 유무와 무관, PARSE_FUSE_SIGNALS를 꺼도 — engine-qa 10-08 ⑤). 그룹마다 "기본 점수"(신뢰도
    ×형식_locale없이+대표엔진 가산, = 신호 꺼짐 때와 같은 셈)와 "전체 점수"(+사전·그래프·로캘 가산)를 따로
    매겨 1위·2위를 비교한다: 기본 점수로도 이미 갈렸으면 **"trust"**(split=False, 가산 없이도 확실) · 기본
    점수는 동점인데 전체 점수가 갈랐으면 **"heuristic"**(split=**True로 유지** — 대표는 그래도 전체 점수가
    높은 후보로 뽑지만, 근거가 신뢰도·형식이 아니라 사전·그래프·로캘 같은 보조 신호뿐이라 **아직 확인된 건
    아니다**로 보고 미확인 자리로 남긴다) · 전체 점수도 동점이면
    **None**(split=True, 아무 신호로도 못 깸). (옛 P2 재판독이 좌표로 실제
    확인하면 split을 False로 해소했다 — pl-34에 지움, 이제 split은 그대로 남는다.)

PARSE_FUSE_SIGNALS(환경변수, 기본 켬, =0으로 끔, PARSE_FUSE 전제) — 끄면(=0) 사전·명부·문서 내 교차 언급·
로캘의 **점수 가산만** 빠져 이 커밋 이전과 점수가 바이트 동일(trust×format_plausibility만, format_plausibility
도 locale_pref 없이 옛 동작) — split·resolved_by 계산 자체는 안 빠진다(위 참조, 신호가 없으면 자연히 전부
"trust"/None이 된다). 단 **conflicts.jsonl 스키마는 꺼지면 이 기능 자체가 없던 코드와 바이트 동일**하도록
`fuse_facts()`가 꺼졌을 때(`on_signals()` False) "split"·"resolved_by" 키를 conflicts 항목에 아예 안 싣는다
(값은 계산해도 파일에는 안 씀) — 트러스트 점수에 끼어드는 새 신호라 P1 자체(PARSE_FUSE)와 별도 스위치로
따로 끌 수 있게.

이 모듈의 두 층:
  - `vote_fragment()` — 조각 하나(같은 자리로 이미 맞춰진 엔진별 텍스트 후보 목록)의 투표 — 범용(표 칸·라벨:값
    뿐 아니라 이미 자리가 맞춰진 어떤 텍스트 조각에도 씀, `dev/cli/eval_fuse_conflicts.py`가 재사용).
  - `fuse_facts()`/`fuse()` — 문서 하나의 라벨:값·표 칸 조각(= `facts`, 라벨 정규화 키로 자리를 맞춤 — 좌표 없이도
    라벨 자체가 자리 열쇠라 순서 정렬이 필요 없다)을 모아 투표하고 `rep["fused"]`에 들어갈 값을 만든다.
    ponytail: 줄(자유 문장) 단위 자리 맞추기(라벨이 없는 조각의 쪽별 순서 정렬)는 좌표 재확인(P2)과 묶어
    처리하는 게 더 값싸 이번엔 안 함 — `fuse()`는 facts만 다룬다(문서 본문 rep["text"]는 안 건드림).

PARSE_FUSE(환경변수, 기본 켬, =0으로 끔) — 끄면(=0) represent.py가 이 모듈을 안 불러 rep에 "fused" 키 자체가
안 생김(바이트 동일). 켜지면(기본) rep["text"]·rep["facts"](기존 칸)는 그대로 — fused는 새 칸으로만 추가된다(덮어쓰기 없음).
"""

import difflib
import re

from common.core.terms import (  # 용어 사전·고객 명부(AD29 ④) — common은 parse·search 공용층(이미지에도 둘 다 포함), rag-core↔rag-parse 역행 아님
    _aliases,
    load_glossary,
    split_terms,
)
from common.core.text import normalize_value  # NFKC·소문자·제로폭 제거·숫자 사이 쉼표 제거·공백 제거(조각 맞추기 키)
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.shared.summarize import FAMILY  # 엔진 → 인식 계열(요약 모듈과 같은 매핑, 중복 정의 안 함)
from pipeline.transform.represent.parse_qa import garbage_ratio  # 깨짐률(형식 타당성 신호 재사용)


def on(config=None):
    """PARSE_FUSE(환경변수, 기본 켬, =0으로 끔)."""
    config = (
        pc.cfg().transform.represent.fuse if config is None else config
    )  # S7c — 설정 객체(bool 칸 → "true"/"false"로 아래 판정이 옛 글자 판정과 같음)
    return str(config).strip().lower() not in ("", "0", "none", "false")


def on_signals(config=None):
    """PARSE_FUSE_SIGNALS(환경변수, 기본 켬, =0으로 끔, PARSE_FUSE 전제) — AD29 ④ 사전·명부·문서 내 교차
    언급 가산 + AD26 (c) 로캘 가산(점수만, split·resolved_by 계산 자체는 항상 돈다 — engine-qa 10-08 ⑤).
    끄면(=0) 점수는 이 커밋 이전과 바이트 동일 + `fuse_facts()`가 conflicts 항목에 "split"·"resolved_by"
    키를 아예 안 실어 `conflicts.jsonl` 스키마도 이 기능 이전과 바이트 동일하게 유지한다."""
    config = (
        pc.cfg().transform.represent.fuse_signals if config is None else config
    )  # S7c — 설정 객체(bool 칸 → "true"/"false"로 아래 판정이 옛 글자 판정과 같음)
    return str(config).strip().lower() not in ("", "0", "none", "false")


# 출처 신뢰도(AD26 (a)) — 원문 추출(텍스트 레이어·오피스 XML) > VLM > OCR. FAMILY(summarize.py)는 엔진 이름 →
# 인식 계열(모델)이고, 여기 집합에 없는 계열(=텍스트 레이어·오피스 XML 추출기, pdfplumber·pymupdf·office 등)은
# 기본값 "text"(가장 신뢰 — 원문 그대로). paddle-vl(PaddleOCR-VL류)은 글자 단위 인식이라 OCR 쪽에 둔다(AD26 — VLM은
# '그럴듯하게 고쳐 쓰는' 생성형만, 문자 인식형은 OCR과 같은 오류 모양).
_OCR_FAMS = {"paddle", "paddle-vl", "tesseract", "easyocr", "surya"}  # ocr-vlm은 엔진과 함께 지움(pl-31)
_VLM_FAMS = {"qwen", "cognee"}
TRUST = {"text": 3.0, "vlm": 2.0, "ocr": 1.0}


def engine_kind(engine):
    """엔진 이름 → 'text'/'vlm'/'ocr'(모르는 엔진은 'text' — 신설 엔진은 FAMILY에 등록해야 정확히 가늠됨)."""
    fam = FAMILY.get(engine, "")
    if fam in _VLM_FAMS:
        return "vlm"
    if fam in _OCR_FAMS:
        return "ocr"
    return "text"


def trust_weight(engine):
    return TRUST[engine_kind(engine)]


_GROUPED_OK = re.compile(r"\d{1,3}(?:,\d{3})+")  # 유효한 3자리 쉼표 묶음(1,520,000)
_GROUPED_PERIOD = re.compile(r"\d{1,3}(?:\.\d{3})+(?!\d)")  # 유럽식 3자리 마침표 묶음(430.000) — 표기만 다른 같은 '묶음 모양'(AD26 (c))
_GROUPED_BAD = re.compile(r"\d{1,3}(?:,\d{1,2}(?:,|$))+")  # 묶음 자리가 3자리가 아닌 쉼표열(4,30,000류 — 깨진 천단위로 봄)
_LOCALE_BONUS = 0.05  # AD26 (c) — 문서 다수 구분자와 같은 쪽에 추가 가산(묶음 자체 가산 0.1과 별개, 작게)


def format_plausibility(text, locale_pref=None):
    """형식 타당성(대략 0~1.15) — 깨짐 비율(garbage_ratio) 역수 + 3자리 묶음(쉼표·마침표 둘 다 유효한 '묶음
    모양'으로 봄, AD26 (c))이면 가산, 자리 수 안 맞는 쉼표열이면 감산(AD29 ② '자릿수 묶음 검사'). locale_pref
    ("," 또는 "." — `_doc_locale_pref()`가 문서 전체에서 센 다수 구분자, 증거 없으면 None)와 같은 구분자를
    쓰면 추가 가산 — 쉼표·마침표 묶음이 신뢰도·기본 가산에서 동점일 때 문서 언어권 표기 관행으로 갈린다
    (AD26 실측: 430,000 vs 430.000). ponytail: 같은 열의 다른 값과 자릿수·소수 자리를 맞춰 보는 칼럼 일관성
    검사(AD29 '같은 열 값들의 자릿수 일치')는 표 열 구조가 필요해 P1 범위 밖 — 표 칸 투표를 호출하는 쪽(향후
    fuse_facts 확장)에서 열 단위로 가산점을 더할 자리만 남겨 둔다."""
    text = text or ""
    score = 1.0 - garbage_ratio(text)
    comma, period = _GROUPED_OK.search(text), _GROUPED_PERIOD.search(text)
    if comma or period:
        score += 0.1
        if locale_pref and locale_pref == ("," if comma else "."):
            score += _LOCALE_BONUS
    if _GROUPED_BAD.search(text):
        score -= 0.1
    return round(score, 4)


def norm_key(text):
    """조각 자리 맞추기·그룹 묶기 비교 키 — common.core.text.normalize_value(NFKC·소문자·제로폭 제거·숫자 사이
    쉼표 제거·공백 전부 제거). 같은 값을 표기만 다르게 쓴 두 조각(공백·대소문자 차이)은 같은 키로 묶이지만,
    구분자 자체가 다른 숫자(430,000 vs 430.000)는 쉼표만 지워져 다른 키(마침표가 남음) — 의도된 동작
    (AD25·AD26 — 쉼표·마침표 중 어느 쪽이 천 단위인지는 섣불리 합치지 않는다)."""
    return normalize_value(text)


_TERM_FUZZY_MIN = 0.84  # 이 밑이면 '다른 말'로 보고 가산 없음(실험값 — OCR 한두 글자 오탈자 수준만 잡음)
_TERM_BONUS = 0.08  # 가산 상한(트러스트 가중치 1.0 차이보다 작게 — 사전 신호가 신뢰도·형식을 뒤엎지 않게)


def term_plausibility(text, glossary=None, aliases=None):
    """AD29 ④ — 조각이 용어 사전(canonical·동의어·약어, `common.core.terms.load_glossary`)·고객 명부(별칭,
    `common.core.terms._aliases`) 표기와 가까우면(오탈자 수준, 예 OCR `Pfzer` vs 정식 `Pfizer`) 가산점(최대
    `_TERM_BONUS`, 비율이 가까울수록 커짐) — 이미 표기가 완전히 같으면(비교할 다른 후보와 차이가 없어) 가산
    0. **원문은 바꾸지 않는다** — 이 함수는 점수만 매기고 호출부가 text를 고치는 일은 없다(새 이름 오교정
    방지, AD29 ④ 원칙). 사전·명부가 둘 다 없으면(선택 장치) 0. 짧은 글(3자 미만)·너무 긴 글(60자 초과,
    라벨:값 조각 범위 밖 — 자유 문장은 P1 대상이 아님)은 비교하지 않고 0."""
    t = (text or "").strip()
    if not t or len(t) < 3 or len(t) > 60:
        return 0.0
    names = []
    for r in (glossary or {}).values():
        names.append(r.get("canonical") or "")
        names.extend(split_terms(r.get("synonyms")))
    for canon, al in (aliases or {}).items():
        names.append(canon)
        names.extend(al)
    names = [n for n in names if n and 3 <= len(n) <= 60]
    if not names:
        return 0.0
    tk = norm_key(t)
    best = max(difflib.SequenceMatcher(None, tk, norm_key(n)).ratio() for n in names)
    if best >= 0.999 or best < _TERM_FUZZY_MIN:
        return 0.0
    return round(_TERM_BONUS * (best - _TERM_FUZZY_MIN) / (1 - _TERM_FUZZY_MIN), 4)


_GROUPED_PERIOD_EVIDENCE = re.compile(r"\d{1,3}(?:\.\d{3}){2,}")  # 마침표 묶음이 **2묶음 이상**(1.234.567류) —
# 1묶음(430.000·0.500)은 소수점인지 천 단위 구분자인지 그 자체로 모호해 로캘 **집계**(아래)에서는 증거로 안 센다
# (engine-qa 10-08 ④ — 순수 소수 0.500까지 '마침표 관행 문서' 증거로 잘못 세는 문제의 1차 완화). 개별 조각
# 채점(`format_plausibility`)은 1묶음도 '묶음 모양'으로 그대로 인정 — 그 판단은 `_GROUPED_PERIOD`(안 바꿈).


def _doc_locale_pref(engine_docs):
    """AD26 (c) — 문서 전체 facts 값에서 쉼표 3자리 묶음(`_GROUPED_OK`, 1묶음도 증거 — 쉼표는 천 단위 구분자
    외 다른 쓰임이 거의 없어 모호함이 적다)과 마침표 **2묶음 이상**(`_GROUPED_PERIOD_EVIDENCE`, 1묶음은 소수점과
    모양이 같아 집계에서 뺀다) 중 어느 쪽이 더 흔한지 센다(`format_plausibility`의 locale_pref 인자). 증거가
    같거나(둘 다 0 포함) 없으면 None — 불확실한 신호는 가산에 안 쓴다."""
    comma = period = 0
    for d in (engine_docs or {}).values():
        for f in (d or {}).get("facts") or []:
            v = f.get("value") or ""
            comma += len(_GROUPED_OK.findall(v))
            period += len(_GROUPED_PERIOD_EVIDENCE.findall(v))
    if comma == period:
        return None
    return "," if comma > period else "."


def _doc_value_graph(engine_docs):
    """AD29 ④ 그래프 타당성의 가벼운 대역(업무 관계 그래프 AD28 ②③은 구조화 단계 과제라 아직 없음·레이어
    역행 방지) — 문서 안에서 같은 정규화 값이 서로 다른 라벨(자리)에도 나오면 교차 언급(값 그래프 연결성)으로
    보고 `vote_fragment`에서 가산. 반환: {정규화 값: 등장한 서로 다른 라벨 수}(1이면 가산 없음)."""
    by_val = {}
    for d in (engine_docs or {}).values():
        for f in (d or {}).get("facts") or []:
            v = norm_key(f.get("value") or "")
            if not v:
                continue
            label = norm_key((f.get("context") or [""])[0])
            by_val.setdefault(v, set()).add(label)
    return {v: len(labels) for v, labels in by_val.items()}


_GRAPH_BONUS_STEP = 0.05  # 교차 언급 자리 하나 늘 때마다(2번째 자리부터)
_GRAPH_BONUS_MAX = 0.1


def _graph_bonus(key, value_graph):
    n = (value_graph or {}).get(key, 1)
    return round(min(_GRAPH_BONUS_STEP * (n - 1), _GRAPH_BONUS_MAX), 4) if n > 1 else 0.0


def vote_fragment(candidates, rep_engine=None, tie_bonus=0.5, locale_pref=None, term_ctx=None, value_graph=None):
    """조각 하나(이미 같은 자리로 맞춰진 엔진별 후보) 투표.
    candidates: [{"engine": str, "text": str}, ...] — 같은 자리의 엔진별 원문(없으면/빈 문자열이면 그 엔진은
    후보에서 빠짐 — 한 계열만 낸 조각은 그 계열 혼자만의 그룹이 된다, AD29 ③ '한 계열만 낸 조각' 신호).
    rep_engine: 지금 대표 엔진 — 그 엔진이 든 그룹에 tie_bonus(동점 깨기·안정성, AD29 ⑤)를 더한다(이건
    "기본" 점수에 포함 — 사전·그래프·로캘처럼 이번에 더한 보조 신호가 아니라 원래 있던 안정화 장치).
    locale_pref·term_ctx({"glossary","aliases"})·value_graph: AD29 ④·AD26 (c) 신호 — 전부 생략(None)하면
    이 세 가산 없이 옛(PARSE_FUSE_SIGNALS 전) 동작과 점수가 같다(fuse_facts가 on_signals()일 때만 넘긴다).
    그룹마다 두 점수를 매긴다 — **기본 점수**(base = trust_weight 합 × format_plausibility(locale_pref 없이)
    + rep_engine 보너스, = 신호가 전혀 없을 때와 같은 셈) · **전체 점수**(score = base + locale 가산(trust ×
    (locale 있는 format_plausibility − 없는 쪽)) + term_plausibility 가산 + 문서 내 교차 언급 가산). 승자는
    전체 점수로 뽑는다(결정적 — 동점이면 candidates에 먼저 나온 그룹). "split"·"resolved_by"는 **신호 유무와
    무관하게 항상 계산**(engine-qa 10-08 ⑤) — 승자·최선 패자의 **기본** 점수까지 비교해서 셋 중 하나로 가른다:
    기본 점수로 이미 갈렸으면 resolved_by="trust"(split=False, 사전·그래프·로캘 없이도 확실) · 기본 점수는
    동점인데 전체 점수가 갈랐으면 resolved_by="heuristic"(**split=True 유지** — AD26 (f): 대표는 그래도
    전체 점수가 높은 후보로 뽑지만, 신뢰도·형식만으로는 못 가른 자리라 "확인된 건 아님"으로 남긴다 — 재판독
    P2·P3는 pl-34 10-30에 지움) · 전체 점수도 동점이면 resolved_by=None(split=True, 아무 신호로도
    못 갈림). 패자가 없으면 split=False·resolved_by=None(갈릴 상대가 없음).
    반환: {"text", "engines"(동의), "score", "split", "resolved_by", "losers":[{engines,text,score}]}(승자
    기준 — 결과마다 동의 엔진·탈락 후보를 남겨 출처를 추적, AD29 ②) 또는 후보가 전부 비면 None.
    결정적: 같은 입력 → 같은 그룹·같은 점수."""
    cands = [c for c in candidates if (c.get("text") or "").strip()]
    if not cands:
        return None
    groups, order = {}, []
    for c in cands:
        k = norm_key(c["text"])
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(c)
    scored = []
    for k in order:
        members = groups[k]
        text0 = members[0]["text"]
        fp_base = max(format_plausibility(text0, None), 0.01)  # 0 이하로 떨어져 점수가 거꾸로 되는 것 방지(하한)
        fp_full = max(format_plausibility(text0, locale_pref), 0.01)
        trust = sum(trust_weight(m["engine"]) for m in members)
        bonus = tie_bonus if rep_engine and any(m["engine"] == rep_engine for m in members) else 0.0
        term_b = term_plausibility(text0, **term_ctx) if term_ctx else 0.0
        graph_b = _graph_bonus(k, value_graph) if value_graph else 0.0
        base = round(trust * fp_base + bonus, 4)
        full = round(base + trust * (fp_full - fp_base) + term_b + graph_b, 4)
        scored.append({"key": k, "text": text0, "engines": [m["engine"] for m in members], "base": base, "score": full})
    scored.sort(key=lambda g: (-g["score"], order.index(g["key"])))
    winner, losers = scored[0], scored[1:]
    if not losers:
        split, resolved_by = False, None
    elif winner["score"] == losers[0]["score"]:
        split, resolved_by = True, None
    elif winner["base"] == losers[0]["base"]:
        split, resolved_by = True, "heuristic"
    else:
        split, resolved_by = False, "trust"
    return {
        "text": winner["text"],
        "engines": winner["engines"],
        "score": winner["score"],
        "split": split,
        "resolved_by": resolved_by,
        "losers": [{"engines": g["engines"], "text": g["text"], "score": g["score"]} for g in losers],
    }


def _fact_key(f):
    """라벨:값 조각의 자리 열쇠 — represent.row_key와 같은 규칙(정규화한 행 라벨, 없으면 값 전체)이지만
    import 방향 때문에(represent.py가 이 모듈을 부름 — 서로 부르면 순환 import) 독립 구현. 규칙이 바뀌면
    양쪽 다 고친다(작은 순수 함수라 중복 비용이 낮음 — represent.row_key 쪽 docstring에도 적어 둠)."""
    label = (f.get("context") or [""])[0]
    return ("row", normalize_value(label)) if label.strip() else ("value", normalize_value(f.get("value") or ""))


def fuse_facts(engine_docs, rep_engine, tie_bonus=0.5):
    """문서 하나 — engine_docs: {엔진: {"facts": [...]}}(그 엔진 자신의 원본 facts, 대표가 다른 엔진 것을
    보충해 만든 rep["facts"] 말고 엔진별 원본 — represent.py가 합치기 전 스냅샷을 넘긴다) → 라벨:값·표 칸
    조각(facts, cells 포함) 융합. 자리 맞추기 = _fact_key(라벨 정규화) 같은 키끼리(좌표·쪽 순서 정렬 없이도
    라벨 자체가 자리 열쇠 — AD29 ①의 '좌표가 없으면' 경로를 facts에서는 라벨 키로 대신한다).
    on_signals()이면(기본) AD29 ④ 사전·명부·문서 내 교차 언급 + AD26 (c) 로캘을 문서 전체(모든 facts) 기준
    한 번만 계산해 매 자리의 vote_fragment에 넘긴다(끄면(=0) 전부 None — 옛 점수와 바이트 동일).
    반환: (facts, conflicts). facts = [{..원래 칸(from 빼고).., "value", "engines", "score"}] 승자만 —
    라벨 정렬(정렬 안정성) 순. conflicts = 같은 자리에서 승자 외 다른 값이 있던 자리만
    [{"label", "winner", "winner_engines", "losers"}] + on_signals()일 때만 `"split"`·`"resolved_by"`도
    (vote_fragment는 이 둘을 항상 계산하지만, **conflicts.jsonl 스키마는 꺼졌을 때 이 기능 이전과 바이트
    동일**하도록 여기서 싣는 걸 막는다 — engine-qa 10-08 ⑤). "split"=True면 AD26 (f) '갈림' — 사람 확인
    목록·검색 근거 '값 갈림' 꼬리표는 다른 모듈 몫, 여기는 플래그만 남긴다."""
    signals_on = on_signals()
    locale_pref, term_ctx, value_graph = None, None, None
    if signals_on:
        locale_pref = _doc_locale_pref(engine_docs)
        value_graph = _doc_value_graph(engine_docs)
        glossary, aliases = load_glossary(), _aliases()
        if glossary or aliases:
            term_ctx = {"glossary": glossary, "aliases": aliases}
    by_key = {}
    for eng, d in engine_docs.items():
        for f in (d or {}).get("facts") or []:
            by_key.setdefault(_fact_key(f), []).append({"engine": eng, "text": f.get("value") or "", "fact": f})
    facts, conflicts = [], []
    for k in sorted(by_key, key=lambda kk: kk[1]):
        cands = by_key[k]
        result = vote_fragment(
            [{"engine": c["engine"], "text": c["text"]} for c in cands], rep_engine, tie_bonus, locale_pref, term_ctx, value_graph
        )
        if not result:
            continue
        base_fact = next(c["fact"] for c in cands if c["text"] == result["text"])
        label = (base_fact.get("context") or [None])[0]
        facts.append(
            {
                **{kk2: vv for kk2, vv in base_fact.items() if kk2 != "from"},
                "value": result["text"],
                "engines": result["engines"],
                "score": result["score"],
            }
        )
        if result["losers"]:
            entry = {"label": label, "winner": result["text"], "winner_engines": result["engines"], "losers": result["losers"]}
            if signals_on:  # 꺼지면(=0) 이 기능 이전과 conflicts.jsonl 스키마가 바이트 동일하게(키 자체가 없음)
                entry["split"], entry["resolved_by"] = result["split"], result["resolved_by"]
            conflicts.append(entry)
    return facts, conflicts


def fuse(engine_docs, rep_engine, tie_bonus=0.5):
    """문서 하나 전체 융합 — rep["fused"]에 들어갈 값(대표 본문·기존 facts는 안 건드림, 새 칸만).
    engine_docs = {엔진: 그 엔진 자신의 파싱 결과(facts 포함, 성공한 후보만)}. 모델 호출 0 · 결정적(같은
    입력 → 같은 그룹·같은 점수·같은 정렬)."""
    facts, conflicts = fuse_facts(engine_docs, rep_engine, tie_bonus)
    return {
        "facts": facts,
        "conflicts": conflicts,
        "stats": {"fragments": len(facts), "conflicts": len(conflicts), "engines": sorted(engine_docs)},
    }
