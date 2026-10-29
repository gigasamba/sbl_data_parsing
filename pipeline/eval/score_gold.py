#!/usr/bin/env python3
"""사람이 적은 파싱 정답(실문서 몇 건)으로 엔진별·대표 결과 정답률 — 개발 서버에서 실행(LLM 0회, 원문은 밖으로 안 나감).

정답 폴더(--gold) 형식 — 문서 이름은 파싱한 원본 파일 이름과 같게(확장자 빼도 됨, 대소문자·공백 무시로 맞춤):
  <문서>.txt / <문서>.md   쪽 전체 정답 글자 — 숫자는 자동으로 '값'이 됨 · md의 `| a | b |` 줄은 표로 읽음(구분선 `|---|` 무시)
  <문서>.json              {"text": "...", "values": ["430,000", {"label": "단가", "value": "430,000"}], "tables": [[["행", "칸"], …], …]}
  values.csv               문서,라벨,값 (머리글 있으면 건너뜀) — 같은 문서의 .txt와 합쳐짐
지표(문서×엔진, 그리고 대표 결과 _rep): 글자 정확도 = 1 − CER(글자·숫자만 비교) · 값 재현율(정답 값이 출력에 있나, 쉼표·공백 무시)
  · 숫자 환각률(출력 숫자 중 정답에 없는 비율) · 표 칸/행 재현율 · 읽기 순서 — 계산은 modules/parse/parse_qa.py와 같은 함수.
  · table_struct_recall(TS1) — 정답 markdown 표의 각 행이 출력 **본문**의 markdown 표(엔진 tables[]/grid 아님)에
    같은 행으로 있나(정답에 표 없으면 None) · mermaid_edge_recall — 정답 ```mermaid``` 블록 edge 재현율(정답에 없으면
    None). SCORE_TABLE_JUDGE=llm이면 경계(행 30~90% 일치) 표만 LLM 판정자(prompts/table_struct_judge)로 승격 가능
    (기본 0=판정자 없음, NO_PAID_CALLS·LLM_FAKE는 common.ai.llm.chat이 그대로 집행).
추가 점검: 대표 엔진이 정답 기준 최고 엔진이었나(선택 일치율) · 교차 재현율(정답 없을 때 쓰는 대리 지표)과 정답 기준 정확도의 순위 상관.

비교 전 정규화(기본 켬, --raw면 끔 — 서버 실측 10-06: 기호·첨자·대시·%·공백 차이로 표 칸 재현율이 17.7%까지 낮게 나옴):
  NFKC(전각·윗/아래첨자 숫자 ²·₂ → 2, ％ → %) · Symbol 글꼴 사용자 영역 글자(\uf0b3 → ≥, \uf0b1 → ± 등) · 대시 종류(‐‑‒–—―−－) → '-' ·
  첨자 표기 ^·_ 제거(10^6 = 10⁶ = 106) · 특수 공백 → 공백. 정규화 전 값 재현율·표 칸 재현율도 raw_*로 함께 남김(정규화 효과 확인).
산출(--out, 기본 output/eval/gold_score): score.json(전체) · summary.md·summary.html(숫자만 — PC로 가져가도 되는 요약, 문서 이름은 기본으로 해시 —
  --plain-names면 원래 이름) · names.json(해시 ↔ 이름, 서버에만 둘 것).
주의: rapidfuzz가 없으면 parse_qa의 줄 비교가 difflib 대체로 느려져 큰 문서에서 멈춘 것처럼 보임(서버 실측) → 없으면 읽기 순서는 건너뜀.
사용: python cli/score_gold.py --gold <정답 폴더> [--parse output/parse] [--src output/prepared] [--out output/eval/gold_score] [--plain-names]
      python cli/score_gold.py --selftest
"""

import argparse
import csv
import hashlib
import json
import re
import statistics
import sys
import tempfile
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

from common.core.paths import APP_ROOT
from common.core.text import no_digit_boundary_hit, supsub_mark  # 첨자 정규화(AD37·SI17·SI20)·금지 값 경계 검사(W20b) 공용
from pipeline import config as pc  # pipeline 칸(S7c — 설정 객체: SCORE_TABLE_JUDGE·GOLD_DIR)
from pipeline.shared.text import DASH_CHARS as _DASH
from pipeline.shared.text import SPACE_CHARS as _SPACE
from pipeline.shared.text import SYMBOL_PUA  # 기호 정규화 맵(10-16 파싱 전용으로 분리)

HERE = Path(__file__).resolve().parent
ROOT = APP_ROOT  # output/ 등 런타임 경로용(옛 dev/)
from pipeline.transform.represent import parse_qa as Q  # noqa: E402 — 채점 함수 재사용(규칙 한 곳)

_KEY = re.compile(r"[\s_\-]+")
HAS_RAPIDFUZZ = hasattr(Q, "_process")  # parse_qa가 rapidfuzz를 불러왔나(없으면 줄 비교가 difflib — 느림)
_TAG_BR = re.compile(r"<\s*br\s*/?\s*>", re.I)
_TAG = re.compile(r"</?\s*[a-zA-Z][a-zA-Z0-9]*(\s[^<>]*)?/?>")  # 그 밖의 태그(<td>·<span> 등)는 지움
_SUPSUB_MARK = re.compile(
    r"(?<=[0-9A-Za-z)])[\^_](?=[0-9A-Za-z(+\-])"
)  # 10^6·CO_2의 표기 기호만(밑줄 든 ID 대부분은 글자 사이라 영향 적음)


# SI47(사용자 10-08 서버 보고) — 사람 정답은 텍스트를 끌어 복사한 뒤 ASCII로 고쳐 씀: 따옴표 생략 · × → x · → → -> · • → * 또는 생략.
# 정답은 그대로 두고 비교할 때 양쪽을 같은 ASCII 꼴로 접는다(파싱 결과 원문은 불변).
_QUOTES = str.maketrans(
    {
        **{c: None for c in "“”„‟‘’‚‛`´"},
        "×": "x",
        "✕": "x",
        "✖": "x",
        "≤": "<=",
        "≦": "<=",
        "≥": ">=",
        "≧": ">=",
        "±": "+/-",
        "µ": "u",
        "μ": "u",
    }
)  # 유사 패턴(10-08 측정)
_PM = re.compile(
    r"\+-(?=\s*\d)|\+\s*/\s*-(?=\s*\d)"
)  # 정답 쪽 +- · + / - → +/- (숫자 앞만, '+ -5' 같은 음수 더하기는 그대로 — engine-qa 2차)
_DEG = re.compile(r"(?<=\d)\s*(?:deg|[°˚])\s*(?=[CF]\b)", re.I)  # 온도만: 37 °C · 37 degC → 37 C (각도 90°는 그대로 — engine-qa 2차)
# ASCII ' "는 짝지은 따옴표·글자 사이 소유격만 지움 — 짝 없는 숫자 뒤 프라임(피트·인치 5'2", 100')은 남김(engine-qa CONCERN 10-08)
_ASCII_PAIR = re.compile(r"([\"'])([^\"'\n]*)\1")
_APOS = re.compile(r"(?<=[A-Za-z])'(?=[A-Za-z])")
_ARROW = re.compile("[→⇒➔➙➜⟶⟹]")
_BULLET = re.compile(
    r"(?:(?<=^)|(?<=\s))[•●▪◦‣∙*]+\s*", re.M
)  # 줄·칸 앞·공백 뒤 목록 표시만(붙여 쓴 곱셈 2*3은 그대로 — 띄어 쓴 "5 * 2"의 * 는 지워짐, 양쪽 대칭이라 같은 원문끼리는 무해)
# 글자 사이 나열 구분(사용자 10-09: 가운뎃점은 정답에서 콤마로 씀 — 유연하게): 원료·부자재 = 원료, 부자재 = 원료/부자재 = 원료 부자재.
# 한글 사이 · , . / → 공백 하나 · 영문 사이는 가운뎃점만 콤마로(AB.CD·AB/CD 같은 ID는 그대로) · 숫자 1.5·1,000 그대로
# 같은 줄 안에서만([ \t]) — 줄바꿈을 지우면 문단이 합쳐져 읽기 순서(order) 지표가 깎임(engine-qa 3차 BLOCK 10-09)
_LISTSEP = re.compile(r"(?<=[가-힣])[ \t]*[·・‧∙,./][ \t]*(?=[가-힣])")
_MIDDOT_EN = re.compile(r"(?<=[A-Za-z])[ \t]*[·・‧∙][ \t]*(?=[A-Za-z])")


def ascii_fold(s):
    """SI47 — 따옴표 지움 · 곱셈 기호 → x · 화살표 → -> · 목록 표시(• ● ▪ *) 지움."""
    if not s:
        return s
    s = _ASCII_PAIR.sub(r"\2", _APOS.sub("", s.translate(_QUOTES)))
    s = _DEG.sub(" ", _PM.sub("+/-", s))
    return _MIDDOT_EN.sub(", ", _LISTSEP.sub(" ", _BULLET.sub("", _ARROW.sub("->", s))))


def canon(s):
    """비교용 정규화 — 원문은 그대로 두고 비교할 때만 쓴다."""
    if not s:
        return s
    import html as _html

    s = supsub_mark(s, plain=True)  # AD37·SI17 — <sup>·<sub>·⁶·₂ 등을 내용만(마커 없이, 독립 검토 MAJOR 2 — 옛 동작과 바이트 동일)
    s = _TAG_BR.sub(" ", s)
    s = _html.unescape(_TAG.sub(" ", s))
    s = "".join(SYMBOL_PUA.get(ord(c), c) for c in s)
    s = unicodedata.normalize("NFKC", s)
    s = _DASH.sub("-", s)
    s = _SPACE.sub(" ", s)
    return ascii_fold(_SUPSUB_MARK.sub("", s))


def canon_gold(g):
    cut = lambda x: x.rstrip(". ") if x else x  # SI47: 정답 칸·값 끝 온점은 비교에서 뺌(출력은 부분 문자열 대조라 영향 없음)
    vals = [{**v, "value": cut(canon(str(v.get("value"))))} if isinstance(v, dict) else cut(canon(str(v))) for v in g["values"]]
    return {"text": canon(g["text"]), "values": vals, "tables": [[[cut(canon(str(c))) for c in row] for row in t] for t in g["tables"]]}


def canon_out(d):
    return {
        **d,
        "text": canon(d.get("text") or ""),
        "tables": [{**t, "text": canon(t.get("text") or "")} for t in (d.get("tables") or []) if isinstance(t, dict)],
    }


def _k(name):
    return _KEY.sub("", Path(name).stem.lower()) if "." in name else _KEY.sub("", name.lower())


def _kfull(name):
    """확장자까지 포함한 이름 열쇠 — 같은 이름의 .docx·.pdf를 구분(synth-realpat에서 발견된 충돌)."""
    return _KEY.sub("", name.lower())


def md_tables(text):
    """`| a | b |` 줄 묶음 → [[행 칸…]…] 목록(구분선 제외)."""
    tables, cur = [], []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("|") and s.count("|") >= 2:
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                cur.append(cells)
        elif cur:
            tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)
    return tables


TABLE_STRUCT_FUZZ = 90  # TS1 — 표 구조 재현율 칸 비교 허용 오차(rapidfuzz ratio 문턱, 글자 칸에만 — 숫자 칸은 정확 일치, 독립 검토 1)
TABLE_JUDGE_LO, TABLE_JUDGE_HI = 0.3, 0.9  # TS1 — 경계 표(판정자에게 물어볼 범위) — 표 하나 단위 행 일치율
# 독립 검토 2 — 표 사이에 흔히 겹치는 꼬리 라벨(합계·Total 등)은 숫자 없이 글자만으로는 매칭 근거로 안 씀(_row_is_label_only).
# 열쇠는 _tcell() 결과(소문자·공백 없음)와 비교하므로 여기도 그 모양으로.
_LABEL_WORDS = {"합계", "총합계", "소계", "계", "total", "subtotal", "grandtotal"}
_NUM_CELL = re.compile(r"^(?P<junk1>[^\d+\-]*)(?P<num>[+-]?\d[\d,]*(?:\.\d+)?)(?P<pct>\s*%)?(?P<junk2>[^\d+\-]*)$")


def _num_key(c):
    """TS1 독립 검토 1 — 칸이 숫자 하나로만 보이면(쉼표 천단위·소수점·부호·%·앞뒤 화폐기호/단위는 무시) (Decimal, %있나)
    키, 아니면 None. 숫자가 아닌 글자가 섞여 있으면(예: 두 숫자가 따로 있거나 글자 라벨) None — 그런 칸은 글자
    비교(퍼지)로 넘어간다. Decimal 사용(🔒 금액·정밀값은 float 금지) — "1,000"과 "1000"은 같다, "1.20"과
    "1.25"는 다르다, 쉼표만 다른 두 긴 숫자는 같지만 한 자리라도 다른 숫자는 다르다(rapidfuzz ratio로 통과하던
    1234567890123 vs ...124 문제)."""
    s = str(c).strip()
    if not s:
        return None
    m = _NUM_CELL.fullmatch(s)
    if not m:
        return None
    num = m.group("num").replace(",", "")
    if num in ("", "+", "-", "."):
        return None
    try:
        val = Decimal(num)
    except InvalidOperation:
        return None
    return (val, bool(m.group("pct")))


def _tcell(c):
    """TS1 — 표 구조 재현율 칸 열쇠(글자 쪽) — 값 재현율과 같은 정규화(Q._key 재사용, 쉼표·공백 제거)."""
    return Q._key(str(c))


def _tcell_pair(c):
    """TS1 — 칸 하나 → (글자 열쇠, 숫자 열쇠 또는 None). 매칭·라벨 판정에 공용으로 쓴다."""
    return (_tcell(c), _num_key(c))


def _trow_eligible(row):
    """TS1 — 정답 칸 2개 미만인 행(제목·구분 줄)은 행 비교에서 뺀다(사용자 명세)."""
    return sum(1 for c in row if str(c).strip()) >= 2


def _row_is_label_only(gold_cells):
    """TS1 독립 검토 2 — 이 정답 행의 글자 칸(숫자가 아닌 칸) 전부가 흔한 꼬리 라벨(합계·Total 등)뿐이면 True.
    이런 행은 라벨 글자만으로 다른(무관한) 표의 같은 라벨 행과 우연히 맞아떨어질 수 있어(재현: 표 A의 합계 행이
    표 B의 무관한 합계 행과 매칭), table_struct()에서 같은 표 안 다른(라벨 아닌) 행이 같은 출력 표에서 이미
    매칭됐다는 근거(corroboration)가 없으면 이 행 혼자서는 매칭으로 안 침."""
    text_cells = [gt for gt, gn in gold_cells if gn is None]
    return bool(text_cells) and all(gt in _LABEL_WORDS for gt in text_cells)


def _tcell_match(g, o):
    """TS1 — 정답 칸 하나가 출력 칸 하나와 같은 칸인지. g·o = (글자 열쇠, 숫자 열쇠) 쌍. 빈 정답 칸은 항상 맞음
    (표 칸 재현율의 기존 규칙과 같음). 둘 중 하나라도 숫자로 보이면(_num_key) 정확한 수치(+% 여부) 일치만
    요구한다(독립 검토 1 — fuzzy는 글자 칸에만, 숫자 칸에 rapidfuzz ratio를 쓰면 자릿수 하나 다른 큰 수도
    통과함). 둘 다 글자면 완전 일치 또는(rapidfuzz 있으면) ratio>=TABLE_STRUCT_FUZZ."""
    gt, gn = g
    ot, on = o
    if not gt:
        return True
    if gn is not None or on is not None:
        return gn is not None and on is not None and gn == on
    if gt == ot:
        return True
    if HAS_RAPIDFUZZ:
        from rapidfuzz import fuzz as _fz

        return _fz.ratio(gt, ot) >= TABLE_STRUCT_FUZZ
    return False


def _trow_match(gold_cells, out_rows):
    """TS1 — 정답 행의 칸 전부가 출력의 '어떤 한 행'(md 표 행 — 본문 한 줄로 안 풀림)에 다 있으면 그 행은 맞음.
    출력에 표가 없으면(out_rows 빈 목록) 항상 거짓 — 표가 한 칸씩 줄로 풀려 사라진 TA1류 회귀를 그대로 0으로 잡는다."""
    return any(all(any(_tcell_match(g, o) for o in row) for g in gold_cells) for row in out_rows)


def table_struct(gold_text, out_text, judge=None):
    """TS1 — 표 구조 재현율: 정답 markdown 표(md_tables(정답 글자))의 각 행이 출력 **본문**의 markdown 표
    (md_tables(출력 글자) — 엔진 자신의 tables[]/grid/tables_std는 절대 안 봄, 표 칸·행 재현율의 C3 구제와는
    다른 길) 안에 같은 행으로 있는지. 정답에 표가 없으면 전부 None(평균에서 빠짐) — 정답에 표가 있는데 출력
    본문에 markdown 표가 하나도 없거나(0.0), 표는 있지만 비교할 행이 하나도 없으면(전부 제목·구분 줄, 독립
    검토 3) 0.0 — None으로 평균에서 빠지지 않는다. 출력 표의 모든 행을 한 풀로 모아 비교하므로, 2단 머리글처럼
    출력에 머리글 역할 줄이 하나 더 있어도 데이터 행 매칭은 깨지지 않는다.
    라벨 행(독립 검토 2) — `_row_is_label_only`인 행은 같은 표 안 다른(라벨 아닌) 행이 같은 출력 표에서 이미
    매칭됐다는 근거가 있을 때만 매칭으로 친다(무관한 표의 우연한 합계/Total 겹침을 막음).
    judge(gold_table_rows, out_table_rows) -> bool — 경계 구간(TABLE_JUDGE_LO~HI, 표 하나 단위 일치율)인 표만
    한 번 물어 통과시킬 수 있다(선택, SCORE_TABLE_JUDGE — 결정적 결과는 그대로, 승격만)."""
    gold_tables = md_tables(gold_text or "")
    if not gold_tables:
        return {"table_struct_recall": None, "table_struct_tables": None, "table_struct_judged": 0}
    out_tables = md_tables(out_text or "")
    out_table_rows = [[[_tcell_pair(c) for c in row] for row in t] for t in out_tables]
    out_rows = [row for rows in out_table_rows for row in rows]
    total, hit, tbl_n, tbl_hit, judged = 0, 0, 0, 0, 0
    for t in gold_tables:
        rows = [r for r in t if _trow_eligible(r)]
        if not rows:
            continue
        gold_rows = [[_tcell_pair(c) for c in r if str(c).strip()] for r in rows]
        is_label = [_row_is_label_only(gr) for gr in gold_rows]
        matched = [False if lbl else _trow_match(gr, out_rows) for gr, lbl in zip(gold_rows, is_label)]
        for i, gr in enumerate(gold_rows):  # 라벨 행 — 2차 통과(비라벨 행 매칭이 다 끝난 뒤라 순서 무관)
            if not is_label[i]:
                continue
            for ot_rows in out_table_rows:
                if not _trow_match(gr, ot_rows):
                    continue
                if any(not is_label[j] and matched[j] and _trow_match(gold_rows[j], ot_rows) for j in range(len(gold_rows))):
                    matched[i] = True
                    break
        n_hit, ratio = sum(matched), sum(matched) / len(rows)
        if judge is not None and out_tables and TABLE_JUDGE_LO <= ratio < TABLE_JUDGE_HI:
            judged += 1
            best_i = max(range(len(out_tables)), key=lambda i: sum(1 for gr in gold_rows if _trow_match(gr, out_table_rows[i])))
            if judge(t, out_tables[best_i]):
                n_hit, ratio = len(rows), 1.0
        total += len(rows)
        hit += n_hit
        tbl_n += 1
        if ratio >= 0.5:
            tbl_hit += 1
    if total == 0:  # 정답에 표는 있지만(위에서 걸러지지 않음) 쓸 수 있는 행이 하나도 없음(독립 검토 3) — None 대신 0.0
        return {"table_struct_recall": 0.0, "table_struct_tables": 0.0, "table_struct_judged": judged}
    return {
        "table_struct_recall": round(hit / total, 4),
        "table_struct_tables": round(tbl_hit / tbl_n, 4) if tbl_n else None,
        "table_struct_judged": judged,
    }


def mermaid_recall(gold_text, out_text):
    """TS1 c) — 정답 ```mermaid``` 블록 vs 출력 ```mermaid``` 블록의 edge 재현율(방향까지 맞은 edge ÷ 정답 edge — 옛 diagram_edges_score.edge_score의 recall, 10-30 그 채점기를 지우며 여기로) ·
    gold_draft.parse_mermaid 재사용(같은 패키지 pipeline.eval 안, 작은 접착만). 정답에 mermaid 블록이
    없으면 None(평균에서 빠짐)."""
    import re

    from pipeline.eval.gold_draft import MERMAID_BLOCK_RX, parse_mermaid
    from pipeline.transform.figures.diagram_edges import norm_node

    gold_blocks = re.findall(MERMAID_BLOCK_RX, gold_text or "", re.S)
    if not gold_blocks:
        return None
    gold_edges = [e for b in gold_blocks for e in parse_mermaid(b)]
    out_blocks = re.findall(MERMAID_BLOCK_RX, out_text or "", re.S)
    out_edges = [e for b in out_blocks for e in parse_mermaid(b)]

    def pairs(edges):
        return {(norm_node(e.get("from")), norm_node(e.get("to"))) for e in edges if e.get("from") and e.get("to")}

    gold = pairs(gold_edges)
    return round(len(pairs(out_edges) & gold) / len(gold), 4) if gold else 1.0


def _table_judge_fn():
    """SCORE_TABLE_JUDGE(env) — "0"(기본) 판정자 없음 · "llm" 경계 표만 LLM 판정자(prompts/table_struct_judge)에게
    물어 통과시킬 수 있음(NO_PAID_CALLS·LLM_FAKE·내부망 가드는 common.ai.llm.chat이 그대로 집행,
    여기선 allow_external을 안 줘 내부망 LLM만) · "vlm"은 TODO — 기존 vlm judge 경로에 더 얹는 작업이 작은
    확장이 아니라 이번 범위 밖(결정적 결과로 대체, 문서화)."""
    mode = (pc.cfg().eval.score_table_judge or "0").strip().lower()  # S7c — 설정 객체(칸 기본값 "0" — 빈 값도 "0")
    if mode != "llm":
        return None

    def _judge(gold_rows, out_rows):
        try:  # 판정자는 선택 승격 기능일 뿐 — 실패(프롬프트·모델 미설정·네트워크·형식 오류)는 모두 "승격 안 함"으로(결정적 결과 보존, research.py _chat_json과 같은 경계)
            from common.ai import llm as _llm
            from common.ai.agent_prompts import load as _load_prompt

            gold_md = "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in gold_rows)
            out_md = "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in (out_rows or []))
            prompt = _load_prompt("table_struct_judge", "judge").format(gold_table=gold_md, out_table=out_md)
            raw = _llm.chat(
                [{"role": "user", "content": prompt}], temperature=0.0, max_tokens=300, json_mode=True, agent="table_struct_judge"
            )
            return bool(_llm.parse_json(raw).get("pass"))
        except Exception:
            return False

    return _judge


def load_gold(gold_dir, doc_names):
    """정답 폴더 → (truth{문서: {text, values, tables}}, 못 맞춘 정답 파일 목록)."""
    full = {_kfull(d): d for d in doc_names}  # 1순위: 확장자까지 같은 이름(`a.docx.md` → a.docx)
    by_stem = {}
    for d in doc_names:
        by_stem.setdefault(_k(d), []).append(d)
    truth, unmatched = {}, []
    for f in sorted(gold_dir.iterdir()):
        if f.name.lower() == "values.csv" or f.suffix.lower() not in (".txt", ".md", ".json"):
            continue
        stem = f.name[: -len(f.suffix)]
        doc = full.get(_kfull(stem))
        if not doc:  # 2순위: 확장자 없는 이름 — 같은 이름의 문서가 하나일 때만
            cands = by_stem.get(_k(stem)) or by_stem.get(_k(stem + ".x")) or []
            if len(cands) == 1:
                doc = cands[0]
            elif len(cands) > 1:
                unmatched.append(f"{f.name}(같은 이름 {len(cands)}개 — 확장자까지 적어 주세요: {', '.join(sorted(cands))})")
                continue
        if not doc:
            unmatched.append(f.name)
            continue
        if f.suffix.lower() == ".json":
            g = json.loads(f.read_text(encoding="utf-8"))
            t = {"text": g.get("text") or "", "values": g.get("values") or [], "tables": g.get("tables") or []}
        else:
            text = f.read_text(encoding="utf-8")
            t = {"text": text, "values": [], "tables": md_tables(text)}
        if t["text"] and not t["values"]:
            t["values"] = [{"value": n} for n in sorted(Q.out_nums(t["text"]))]
        truth[doc] = t
    vf = gold_dir / "values.csv"
    if vf.exists():
        with vf.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.reader(fh):
                if len(row) < 3 or row[0].strip() in ("문서", "doc", "file"):
                    continue
                nm = row[0].strip()
                doc = full.get(_kfull(nm))
                if not doc:
                    cands = by_stem.get(_k(nm)) or by_stem.get(_k(nm + ".x")) or []
                    doc = cands[0] if len(cands) == 1 else None
                if not doc:
                    unmatched.append(f"values.csv:{row[0]}")
                    continue
                truth.setdefault(doc, {"text": "", "values": [], "tables": []})["values"].append(
                    {"label": row[1].strip(), "value": row[2].strip()}
                )
    return truth, sorted(set(unmatched))


def metrics(gold, out, judge=None):
    """정답 하나 × 출력 글자 하나 → 지표 dict(parse_qa와 같은 함수). judge — TS1 표 구조 경계 판정자(선택)."""
    text, stext = out.get("text") or "", Q.scoring_text(out)
    m = {"chars": len(text)}
    if gold["text"]:
        c, _ = Q.cer(gold["text"], text)
        m["char_acc"] = round(1 - c, 4)
        cov = gold_coverage(gold["text"], text)
        if cov is not None:  # 부분 정답(SI24): 출력에만 있는 글자는 오류로 안 셈 — 정답 글자가 출력에 얼마나 맞게 있나
            m["char_acc_full"], m["char_acc"], m["gold_partial"] = m["char_acc"], cov, True
        if HAS_RAPIDFUZZ:  # 없으면 줄마다 difflib 전수 비교 — 큰 문서에서 멈춘 것처럼 보임(서버 실측)
            order, _diff = Q.order_diff(gold["text"], text)  # 차이 예시(원문)는 남기지 않음 — 요약을 밖으로 가져가도 되게
            if order is not None:
                m["order"] = round(order, 4)
    if gold["values"]:
        m["value_recall"] = round(Q.value_recall(gold["values"], Q.clean_commas(Q.norm_nows(stext))), 4)
        m["num_halluc"] = round(Q.num_halluc(Q.numeric_values(gold["values"]) | Q.out_nums(gold["text"]), stext), 4)
    if gold["tables"]:
        lines = [Q.clean_commas(Q.norm_nows(ln)) for ln in text.splitlines() if ln.strip()]
        rr, rc = Q.table_recall(gold["tables"], Q.clean_commas(Q.norm_nows(stext)), lines)
        if rr is not None:
            m["table_row_recall"] = round(rr, 4)
        if rc is not None:
            m["table_cell_recall"] = round(rc, 4)
        out_toks = _toks(stext)
        cells = [c for t in gold["tables"] for row in t for c in row if _toks(str(c))]
        if cells:
            m["table_cell_token_recall"] = round(sum(1 for c in cells if _toks(str(c)) <= out_toks) / len(cells), 4)
    ts = table_struct(gold.get("text"), text, judge=judge)  # TS1 — tables[]/grid 아닌 본문 markdown 표만(C3 구제와 다른 길)
    if ts["table_struct_recall"] is not None:
        m["table_struct_recall"] = ts["table_struct_recall"]
        if ts["table_struct_tables"] is not None:
            m["table_struct_tables"] = ts["table_struct_tables"]
    if ts["table_struct_judged"]:
        m["table_struct_judged"] = ts["table_struct_judged"]
    mm = mermaid_recall(gold.get("text"), text)  # TS1 c) — 정답에 mermaid 없으면 None(평균에서 빠짐)
    if mm is not None:
        m["mermaid_edge_recall"] = round(mm, 4)
    return m


PARTIAL = 0.6  # 정답 글자 수 < 출력 × 0.6 이면 사람이 일부만 옮겨 쓴 정답으로 봄(서버 실정답은 앞부분·표만인 경우가 많음 — SI24)


def gold_coverage(ref_text, out_text):
    """부분 정답일 때만 1 − (정답 글자 중 틀리거나 빠진 수 ÷ 정답 글자 수) — 출력의 나머지(정답이 안 옮긴 부분)는 벌점 없음.
    편집 거리에서 '출력에만 있는 글자 끼워 넣기'를 0으로(가중 Levenshtein). 부분 정답 아니거나 rapidfuzz 없으면 None."""
    r, o = Q._CONTENT.sub("", Q.norm(ref_text)), Q._CONTENT.sub("", Q.norm(out_text))
    if not r or len(r) >= PARTIAL * len(o) or not HAS_RAPIDFUZZ:
        return None
    from rapidfuzz.distance import Levenshtein

    r, o = r[: Q.CER_CAP], o[: Q.CER_CAP * 4]
    return round(1 - min(1.0, Levenshtein.distance(r, o, weights=(0, 1, 1)) / len(r)), 4)


def scored(gold, out, normalize=True, judge=None):
    """정규화한 지표 + 정규화 전 값·표 칸 재현율(raw_*). judge — TS1(선택, 경계 표 판정자)."""
    if not normalize:
        return metrics(gold, out, judge=judge)
    m = metrics(canon_gold(gold), canon_out(out), judge=judge)
    raw = metrics(
        {**gold, "text": ""}, {**out}
    )  # 글자 정확도·순서·표 구조는 다시 안 셈(정답 글자를 비웠으니 표 구조도 자연히 None) — 값·표 칸만
    for k in ("value_recall", "table_cell_recall", "table_row_recall"):
        if raw.get(k) is not None:
            m["raw_" + k] = raw[k]
    return m


def value_hits(gold, out, normalize=True):
    """맞힌 정답 값의 번호 집합 — 엔진별 '그 엔진만 맞힌 값'(구제) 집계용(value_recall과 같은 비교)."""
    g, o = (canon_gold(gold), canon_out(out)) if normalize else (gold, out)
    stext = Q.clean_commas(Q.norm_nows(Q.scoring_text(o)))
    return {i for i, v in enumerate(g["values"]) if Q._key_hit(Q._key(v), stext)}  # C2 — value_recall과 같은 비교(_key_hit)


def load_spec_must_not(spec_dir):
    """W20① — 합성 세트 spec.json documents[].must_not(그 문서에 없어야 할 값 — 다른 문서 값 섞임·VLM 지어냄 검출) →
    {문서 파일명: [금지 값…]}. 생성기마다 모양이 다름(plain 문자열 — gen_synth_wmf.py 등, 또는 {"kw", "why"} —
    gen_synth_confuse.py의 N())이라 둘 다 받아 kw(또는 문자열 그대로)만 꺼낸다. spec.json 없거나 spec_dir 안 주면
    빈 dict(기존 호출·데이터셋은 영향 없음)."""
    if not spec_dir:
        return {}
    f = Path(spec_dir) / "spec.json"
    if not f.exists():
        return {}
    sp = json.loads(f.read_text(encoding="utf-8"))
    out = {}
    for d in sp.get("documents", []):
        texts = [m.get("kw") if isinstance(m, dict) else m for m in (d.get("must_not") or [])]
        texts = [t for t in texts if t]
        if texts:
            out[d["file"]] = texts
    return out


def must_not_hits(musts, out, normalize=True):
    """W20① — musts(금지 값) 중 출력에 나온 것 — value_recall과 같은 정규화(canon_out + Q._key)까지는 공유하지만,
    맞음 판정은 Q._key_hit이 아니라 no_digit_boundary_hit(W20b) — 숫자 금지 값이 더 긴 숫자 안에 끼어 있으면
    (예: "3,360"이 "3,360,000" 안) 거짓 양성으로 안 침(독립 검토). value_recall 자체는 안 건드림. musts 비면 []."""
    if not musts:
        return []
    o = canon_out(out) if normalize else out
    stext = Q.clean_commas(Q.norm_nows(Q.scoring_text(o)))
    return [raw for raw in musts if no_digit_boundary_hit(Q._key({"value": canon(str(raw)) if normalize else str(raw)}), stext)]


def _toks(text):
    """느슨한 비교용 토큰 — 쉼표 뺀 글자·숫자 덩어리(1자도 셈, 대소문자 무시)."""
    return {t.replace(",", "") for t in re.findall(r"[0-9A-Za-z가-힣%.,≥≤±×°μαβγ-]+", (text or "").lower()) if t.strip(".,-")}


def headline(m):
    """문서 하나의 대표 정답률 = 값 재현율(있으면) → 글자 정확도."""
    return m.get("value_recall", m.get("char_acc"))


def _spearman(xs, ys):
    if len(xs) < 3:
        return None
    rank = lambda v: {x: i for i, x in enumerate(sorted(set(v)))}  # 동점은 같은 순위(간단)
    rx, ry = rank(xs), rank(ys)
    a, b = [rx[x] for x in xs], [ry[y] for y in ys]
    try:
        return round(statistics.correlation(a, b), 3)
    except statistics.StatisticsError:
        return None


def score(parse_dir, src_dir, gold_dir, normalize=True, spec_dir=None):
    docs = sorted({json.loads(ln)["doc"] for ln in (parse_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()})
    truth, unmatched = load_gold(gold_dir, docs)
    must_not = load_spec_must_not(spec_dir)  # W20① — 비면 {}(기존 호출과 동일 동작)
    judge_fn = _table_judge_fn()  # TS1 — SCORE_TABLE_JUDGE, 프로세스 안에서 한 번만 읽음
    with tempfile.TemporaryDirectory() as td:  # 교차 재현율(대리 지표)은 정답 없이 계산해야 비교가 됨
        qa, _ = Q.run(parse_dir, src_dir, Path(td) / "none.json", None)
    out = {"docs": {}, "unmatched_gold": unmatched, "normalized": normalize, "order_skipped": not HAS_RAPIDFUZZ}
    hits = {}  # 문서 → 엔진 → 맞힌 값 번호(구제 집계)
    for doc, gold in truth.items():
        row = {"engines": {}, "rep": None}
        musts = must_not.get(doc)  # W20① — 사람 정답이 있는 문서에 금지 값도 있으면 같이(없으면 None — 칸 비움)
        for eng, m0 in (qa["docs"].get(doc, {}).get("engines") or {}).items():
            f = parse_dir / eng / f"{doc}.json"
            if not m0.get("ok") or not f.exists():
                continue
            eo = json.loads(f.read_text(encoding="utf-8"))
            m = scored(gold, eo, normalize, judge=judge_fn)
            m["cross_recall"] = m0.get("cross_recall")
            if musts is not None:
                m["must_not_violations"] = must_not_hits(musts, eo, normalize)
            row["engines"][eng] = m
            if gold["values"]:
                hits.setdefault(doc, {})[eng] = value_hits(gold, eo, normalize)
        rf = parse_dir / "_rep" / f"{doc}.json"
        if rf.exists():
            rep = json.loads(rf.read_text(encoding="utf-8"))
            r = scored(gold, rep, normalize, judge=judge_fn)  # 값·표 = 후보정 블록까지 포함한 최종 대표 결과
            r["engine"] = (rep.get("rep") or {}).get("engine")
            ef = parse_dir / str(r["engine"]) / f"{doc}.json"
            if ef.exists():  # 글자 정확도는 대표 엔진 원문으로 — 후보정 블록(첨자 표기본 등)이 본문을 다시 붙여 CER이 부풀기 때문
                eng_txt = json.loads(ef.read_text(encoding="utf-8"))
                body = scored({**gold, "values": [], "tables": []}, eng_txt, normalize)
                if body.get("char_acc") is not None:
                    r["char_acc_post"], r["char_acc"] = r.get("char_acc"), body["char_acc"]
                r["rep_len_ratio"] = round(
                    len(rep.get("text") or "") / max(1, len(eng_txt.get("text") or "")), 2
                )  # 2 가까우면 본문이 두 번 들어감
            if musts is not None:
                r["must_not_violations"] = must_not_hits(musts, rep, normalize)
            row["rep"] = r
        if row["engines"]:
            best = max(row["engines"], key=lambda e: headline(row["engines"][e]) or -1)
            row["best_engine"] = best
            row["rep_is_best"] = bool(row["rep"]) and (
                row["rep"]["engine"] == best or headline(row["engines"].get(row["rep"]["engine"], {})) == headline(row["engines"][best])
            )
            pairs = [
                (m["cross_recall"], headline(m))
                for m in row["engines"].values()
                if m.get("cross_recall") is not None and headline(m) is not None
            ]
            row["proxy_spearman"] = _spearman([p[0] for p in pairs], [p[1] for p in pairs]) if pairs else None
        out["docs"][doc] = row
    # W20① — 금지 값은 있지만 사람 정답은 없는 문서(합성 세트 대부분)는 기존 out["docs"](사람 정답 집계용) 바깥에 따로 —
    # eng_avg·out["rep"] 같은 기존 평균 계산(n_docs 등)에 안 섞이게 수술적으로 분리.
    must_not_docs = {}
    for doc in sorted(set(must_not) - set(truth)):
        musts = must_not[doc]
        row = {"engines": {}, "rep": None}
        for eng, m0 in (qa["docs"].get(doc, {}).get("engines") or {}).items():
            f = parse_dir / eng / f"{doc}.json"
            if not m0.get("ok") or not f.exists():
                continue
            eo = json.loads(f.read_text(encoding="utf-8"))
            row["engines"][eng] = {"must_not_violations": must_not_hits(musts, eo, normalize)}
        rf = parse_dir / "_rep" / f"{doc}.json"
        if rf.exists():
            rep = json.loads(rf.read_text(encoding="utf-8"))
            row["rep"] = {"engine": (rep.get("rep") or {}).get("engine"), "must_not_violations": must_not_hits(musts, rep, normalize)}
        if row["engines"] or row["rep"]:
            must_not_docs[doc] = row
    if must_not:  # W20① — spec 안 줬으면 칸 자체를 안 둠(기존 호출 바이트 불변)
        out["must_not_docs"] = must_not_docs
        out["must_not_violations_total"] = sum(
            len((r.get("rep") or {}).get("must_not_violations") or []) for r in list(out["docs"].values()) + list(must_not_docs.values())
        )
    eng_avg = {}
    for row in out["docs"].values():
        for e, m in row["engines"].items():
            eng_avg.setdefault(e, []).append(m)
    out["engines"] = {
        e: {
            k: round(statistics.mean([m[k] for m in ms if m.get(k) is not None]), 4)
            for k in (
                "char_acc",
                "value_recall",
                "raw_value_recall",
                "num_halluc",
                "table_cell_recall",
                "raw_table_cell_recall",
                "table_cell_token_recall",
                "table_row_recall",
                "table_struct_recall",
                "table_struct_tables",
                "mermaid_edge_recall",
                "order",
            )  # TS1 — 표 구조·흐름도 평균도 같은 자리에
            if any(m.get(k) is not None for m in ms)
        }
        | {"n_docs": len(ms)}
        for e, ms in eng_avg.items()
    }
    uniq, resc = {}, {}  # 엔진별 '그 엔진만 맞힌 값' · '대표가 놓친 걸 이 엔진이 맞힌 값' — 엔진을 남길지 판단(사용자 10-07)
    for doc, by in hits.items():
        rep_e = (out["docs"][doc].get("rep") or {}).get("engine")
        for e, h in by.items():
            if len(by) < 2:  # 엔진이 하나뿐인 문서(예: docx는 office만)는 비교 대상이 없어 '그 엔진만'에 안 셈
                continue
            others = set().union(*[x for k, x in by.items() if k != e])
            uniq[e] = uniq.get(e, 0) + len(h - others)
            if rep_e and rep_e != e and rep_e in by:
                resc[e] = resc.get(e, 0) + len(h - by[rep_e])
    for e in out["engines"]:
        out["engines"][e]["unique_values"] = uniq.get(e, 0)
        out["engines"][e]["rescue_vs_rep"] = resc.get(e, 0)
    reps = [r["rep"] for r in out["docs"].values() if r.get("rep")]
    out["rep"] = {
        k: round(statistics.mean([r[k] for r in reps if r.get(k) is not None]), 4)
        for k in (
            "char_acc",
            "char_acc_post",
            "rep_len_ratio",
            "value_recall",
            "raw_value_recall",
            "num_halluc",
            "table_cell_recall",
            "raw_table_cell_recall",
            "table_cell_token_recall",
            "table_struct_recall",
            "table_struct_tables",
            "mermaid_edge_recall",
        )
        if any(r.get(k) is not None for r in reps)
    } | {"n_docs": len(reps)}  # TS1
    sel = [r["rep_is_best"] for r in out["docs"].values() if "rep_is_best" in r]
    out["rep"]["selection_match"] = round(sum(sel) / len(sel), 4) if sel else None
    judged_total = sum(
        r.get("table_struct_judged") or 0 for r in reps
    )  # TS1 — 판정자를 실제로 불렀던 경계 표 수(승격 여부 무관), 0이면 칸 자체를 안 둠(기존 출력 바이트 불변)
    if judged_total:
        out["rep"]["table_struct_judged"] = judged_total
    return out


def summary_md(res, names):
    h = lambda d: names.get(d, d)
    L = [
        "# 파싱 정답률 — 사람 정답 기준(실문서)",
        "",
        f"정답 문서 {len(res['docs'])}건 · 못 맞춘 정답 파일 {len(res['unmatched_gold'])}개",
        "",
        "## 대표 결과(_rep, 후보정 포함)",
        "",
        "| 지표 | 값 |",
        "|---|---|",
    ]
    L += [f"| {k} | {v} |" for k, v in res["rep"].items()]
    L += [
        "",
        "## 엔진별 구제 — 남길지 판단(그 엔진만 맞힌 정답 값 · 대표가 놓친 값을 이 엔진이 맞힌 수)",
        "",
        "| 엔진 | 문서 | 그 엔진만 맞힌 값 | 대표가 놓친 값 맞힘 |",
        "|---|---|---|---|",
    ]
    L += [
        f"| {e} | {m['n_docs']} | {m.get('unique_values', 0)} | {m.get('rescue_vs_rep', 0)} |"
        for e, m in sorted(res["engines"].items(), key=lambda kv: -(kv[1].get("unique_values") or 0))
    ]
    L += [
        "",
        "## 엔진별 평균",
        "",
        "| 엔진 | 문서 | 글자 정확도 | 값 재현율 | (정규화 전) | 숫자 환각 | 표 칸 | (정규화 전) | 표 칸(느슨) | 표 행 | 표 구조(TS1) | 표 구조(표 단위) | 흐름도 edge | 읽기 순서 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for e, m in sorted(res["engines"].items(), key=lambda kv: -(kv[1].get("value_recall") or kv[1].get("char_acc") or 0)):
        L.append(
            f"| {e} | {m['n_docs']} | {m.get('char_acc', '—')} | {m.get('value_recall', '—')} | {m.get('raw_value_recall', '—')} | {m.get('num_halluc', '—')} | {m.get('table_cell_recall', '—')} | {m.get('raw_table_cell_recall', '—')} | {m.get('table_cell_token_recall', '—')} | {m.get('table_row_recall', '—')} | {m.get('table_struct_recall', '—')} | {m.get('table_struct_tables', '—')} | {m.get('mermaid_edge_recall', '—')} | {m.get('order', '—')} |"
        )
    has_mnv = "must_not_violations_total" in res  # W20① — --spec 줬을 때만 칸을 둠(안 주면 표 모양 바이트 불변)
    mnv_head = " 금지 값 위반 |" if has_mnv else ""
    mnv_sep = "---|" if has_mnv else ""
    L += [
        "",
        "## 문서별",
        "",
        f"| 문서 | 대표 엔진 | 대표 값 재현율 | 대표 글자 정확도 | 정답 기준 최고 엔진 | 선택 일치 | 교차 재현율↔정답 순위 상관 |{mnv_head}",
        f"|---|---|---|---|---|---|---|{mnv_sep}",
    ]
    for d, r in sorted(res["docs"].items()):
        rep = r.get("rep") or {}
        mnv_cell = f" {len(rep['must_not_violations'])} |" if has_mnv and "must_not_violations" in rep else (" n/a |" if has_mnv else "")
        L.append(
            f"| {h(d)} | {rep.get('engine', '—')} | {rep.get('value_recall', '—')} | {rep.get('char_acc', '—')} | {r.get('best_engine', '—')} | {'O' if r.get('rep_is_best') else 'X'} | {r.get('proxy_spearman', '—')} |{mnv_cell}"
        )
    for d, r in sorted((res.get("must_not_docs") or {}).items()):  # W20① — 사람 정답 없는 합성 세트 문서(금지 값만)
        rep = r.get("rep") or {}
        mnv_cell = f" {len(rep['must_not_violations'])} |" if "must_not_violations" in rep else " n/a |"
        L.append(f"| {h(d)} | {rep.get('engine', '—')} | — | — | — | — | — |{mnv_cell}")
    if has_mnv:
        L += ["", f"금지 값 위반 총 {res['must_not_violations_total']}건(대표 결과 기준, spec.json must_not — W20①)."]
    if res.get("order_skipped"):
        L += ["", "⚠ rapidfuzz 없음 — 읽기 순서는 건너뜀(`pip install rapidfuzz`)."]
    L += [
        "",
        "읽는 법: 표 칸(엄격) = 칸 글자가 출력에 이어져 있음 · 표 칸(느슨) = 칸의 토큰이 모두 출력에 있음(줄바꿈·다열 섞임·`{, , }`/`| |` 형식 차이 무시) — 둘의 차이가 크면 표 구조·줄바꿈 문제, 둘 다 낮으면 글자 자체 누락 · "
        "표 구조(TS1) = 정답 markdown 표의 각 행이 출력 **본문의 markdown 표**(엔진 자신의 tables[]/grid 아님)에 같은 행으로 있는 비율 — 표 칸·행 재현율이 높아도 이게 낮으면 표가 한 칸씩 줄로 풀려 markdown 구조를 잃었다는 뜻 · "
        "값 재현율 = 정답 값 중 출력에 있는 비율(쉼표·공백 무시) · 글자 정확도 = 1 − CER · 선택 일치 = 대표 엔진이 정답 기준 최고 엔진과 같은 점수 · "
        "순위 상관이 낮으면 교차 재현율(정답 없을 때 대표를 고르는 기준)이 실문서에서 믿을 만하지 않다는 뜻 → AD29·AD26 근거.",
    ]
    return "\n".join(L) + "\n"


def summary_html(md):
    """summary.md → 단일 HTML(표·제목만, 외부 자원 없음)."""
    import html as H

    out, rows = [], []

    def flush():
        if rows:
            head, body = rows[0], [r for r in rows[2:]]
            out.append(
                "<table><thead><tr>"
                + "".join(f"<th>{H.escape(c)}</th>" for c in head)
                + "</tr></thead><tbody>"
                + "".join("<tr>" + "".join(f"<td>{H.escape(c)}</td>" for c in r) + "</tr>" for r in body)
                + "</tbody></table>"
            )
            rows.clear()

    for ln in md.splitlines():
        if ln.startswith("|"):
            rows.append([c.strip() for c in ln.strip().strip("|").split("|")])
            continue
        flush()
        if ln.startswith("## "):
            out.append(f"<h2>{H.escape(ln[3:])}</h2>")
        elif ln.startswith("# "):
            out.append(f"<h1>{H.escape(ln[2:])}</h1>")
        elif ln.strip():
            out.append(f"<p>{H.escape(ln)}</p>")
    flush()
    css = (
        "body{font-family:'Malgun Gothic',sans-serif;margin:24px;color:#222}table{border-collapse:collapse;margin:8px 0 20px}"
        "th,td{border:1px solid #ccc;padding:4px 8px;font-size:13px;text-align:right}th{background:#f0f3f5}td:first-child,th:first-child{text-align:left}"
    )
    return f"<!doctype html><meta charset='utf-8'><title>파싱 정답률</title><style>{css}</style>" + "".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gold", default=pc.gold_dir() or None, help="사람 정답 폴더(기본 env GOLD_DIR — 서버는 .env 한 곳에, env-guide 1-2)")
    ap.add_argument("--parse", default=str(ROOT / "output" / "parse"))
    ap.add_argument("--src", default=str(ROOT / "output" / "prepared"))
    ap.add_argument("--out", default=str(ROOT / "output" / "eval" / "gold_score"))
    ap.add_argument("--plain-names", action="store_true", help="요약에 원래 문서 이름(기본은 해시 — 밖으로 가져가도 되게)")
    ap.add_argument("--raw", action="store_true", help="비교 전 정규화 끔(기호·첨자·대시·공백)")
    ap.add_argument(
        "--spec",
        default="",
        help="W20① — spec.json 있는 합성 세트 폴더(예 valid_env/unstructured/synth-confuse) — must_not 금지 값 위반을 같이 보고(비우면 기존과 동일)",
    )
    a = ap.parse_args(argv)
    if not a.gold:
        ap.error("--gold 필요(또는 .env GOLD_DIR)")
    res = score(Path(a.parse), Path(a.src), Path(a.gold), normalize=not a.raw, spec_dir=Path(a.spec) if a.spec else None)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    all_docs = list(res["docs"]) + list(res.get("must_not_docs") or {})
    names = {} if a.plain_names else {d: "doc-" + hashlib.sha256(d.encode()).hexdigest()[:8] for d in all_docs}
    (out / "score.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = summary_md(res, names)
    (out / "summary.md").write_text(md, encoding="utf-8")
    (out / "summary.html").write_text(summary_html(md), encoding="utf-8")
    if names:
        (out / "names.json").write_text(json.dumps({v: k for k, v in names.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[score_gold] 문서 {len(res['docs'])}건 · 대표 {res['rep']} · 못 맞춘 정답 {res['unmatched_gold']} → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
