#!/usr/bin/env python3
"""실데이터(정답 없음)에서 질문·정답을 **문서로부터 거꾸로** 만든다 — 여러 파서가 교차 확인한 값만 정답으로(LLM 0회).

정답 만들기는 느려도 되고(모든 엔진 출력 대조), 대신 정답마다 근거(파일·쪽·줄·원문 한 줄)를 미리 붙여 둔다 →
답변 채점·근거 확인은 이 위치만 보면 되므로 빠르다(옛 run_answers·verify_key는 10-13 답변 경로 통일 4단계로
archive — 이 질문 세트를 쓰는 답변 평가는 dev_tools/perform_test/answer_stage/run.py, 서빙되는 Answer Agent rag_qa로).

규칙(교차 확인 = 서로 다른 인식 계열 파서 min_fams개 이상이 같은 것을 뽑음, 계열 = summarize.FAMILY):
  value  : '라벨: 값' 줄 · 표 셀(행 라벨/열 머리글 → 값)에서 숫자가 든 값. 같은 (라벨, 값)을 min_fams 계열이 뽑은 것만.
           문서 안에서 같은 라벨에 값이 둘 이상이면 모호 → 제외. 문서 식별은 교차 확인된 계약·견적·주문 번호(없으면 파일 구별 단어).
  client : 교차 확인된 고객사 + 계약 번호 + 단가·금액 → "고객사 X의 계약(번호 Y) 단가는?"
  count  : 고객사별 서로 다른 계약 번호 수(교차 확인된 것만, 같은 계약 번호 사본은 1건).
  sum    : 고객사별 표의 수량·용량 열 합계 — 계약 번호당 한 번, 수량 셀은 다른 계열 파서의 같은 줄(행 라벨+값)로 확인.
           고객사 문서 중 수량 표를 못 읽은 계약이 있으면 합계가 틀리므로 그 고객사는 만들지 않음.
  rfi    : 자동 생성 안 함(핵심 내용 판단 필요) — --rfi <RFI 예시·이력 jsonl>을 주면 그대로 합침.
모든 문항: auto=true · gold_source="자동(교차 확인 k계열)" · gold_evidence=[{file, page, line, section, snippet}] — 사람 확인 전 후보.
흐름(10-13 이전): auto_questions → run_answers(상위 조합 답·근거) → verify_key(확정·의심·충돌) — 그 둘은 archive,
이 질문 세트 자체는 그대로(dev_tools/perform_test/answer_stage/run.py가 --set로 직접 읾을 수 있음).

사용: python cli/auto_questions.py [--parse-dir output/parse] [--src output/prepared] [--out output/eval/questions.jsonl]
        [--per-category 20] [--min-fams 2] [--rfi <jsonl>] [--check-truth output/corpus/truth.json]
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)
from common.core.console import utf8_stdout

# isort: split
import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
from common.core import terms as T  # noqa: E402 — ID 모양(검색·구조화와 같은 규칙)
from common.core.repfmt import (  # noqa: E402,F401
    CLIENT_RE,
    CONTRACT_FIRST,
    CONTRACT_RE,
    EMPTY,
    NUM_RE,
    PRICE_RE,
    QTY_RE,
    SUPPLIER_RE,
    _pick,
    nlabel,
    num,
    pairs_of,
    pick,
    table_rows,
)  # 대표 결과 형식 읽기(common)
from pipeline.eval import stages as S  # noqa: E402
from pipeline.transform.represent.crosscheck import build, families, load_doc, locate_value  # noqa: E402,F401 — 교차 확인(파싱 모듈)
from pipeline.transform.represent.parse_qa import garbage_ratio  # noqa: E402 — 글자 깨짐 보조 판정 재사용(E12)

MAIL_FORMATS = {".eml", ".msg", ".mht", ".mhtml"}  # '글자 깨짐 → 미확인 문서' 판정 대상 형식만(E12 독립 검토 MAJOR)
# — 스캔 PDF 등 OCR 노이즈 문서는 다른 깨짐 원인이라 대상에서 뺀다.
MOJI_THRESHOLD = 0.1  # mojibake_ratio 문턱 — 잠정값(cp949/utf-8 오해석 합성 샘플 기준, clean 0.0 vs 깨짐 0.48 실측).
# 서버 실메일 샘플로 재보정 필요(E12 독립 검토 MODERATE).
GARBAGE_AUX_THRESHOLD = 0.3  # garbage_ratio(제어문자·한 글자짜리 줄) 보조 신호 — mojibake_ratio가 못 잡는 깨짐 보완용, 2차 판정.


def _mojibake_ratio(text):
    """메일 인코딩 오해석(mojibake) 1차 신호 — 대체문자(U+FFFD) 비율 + cp949/euc-kr 바이트가 utf-8·라틴-1로
    오해석될 때 흔히 몰리는 라틴 확장 대역(U+00C0~U+024F) 밀집 비율. garbage_ratio(제어문자·한 글자짜리 줄,
    OCR 노이즈 패턴)와는 다른 신호라 분리(E12 독립 검토 MODERATE — garbage_ratio는 보조로만)."""
    if not text:
        return 0.0
    repl = text.count("�")
    latin_ext = sum(1 for c in text if 0x00C0 <= ord(c) <= 0x024F)
    return round((repl + latin_ext) / max(1, len(text)), 4)


def _clean_engines(info):
    """mojibake_ratio·garbage_ratio 모두 문턱 미만인 계열 → 텍스트 — 읽을 수 있는(글자 안 깨진) 계열만(E12)."""
    out = {}
    for e, o in info["outs"].items():
        t = o.get("text") or ""
        if _mojibake_ratio(t) < MOJI_THRESHOLD and garbage_ratio(t) < GARBAGE_AUX_THRESHOLD:
            out[info["fam"].get(e, e)] = t
    return out


def _garbled_doc(info):
    """메일류 문서(MAIL_FORMATS)에서 여러 계열이 시도됐는데 읽을 수 있는 계열이 1개 이하 — 글자층이
    깨져 교차 확인이 애초에 안 되는 문서(메일 인코딩 오해석 등, 백로그 E12)."""
    if info.get("format") not in MAIL_FORMATS:  # 스캔 PDF 등 OCR 노이즈는 대상 아님(독립 검토 MAJOR)
        return False
    fams = {info["fam"].get(e, e) for e in info["outs"]}
    if len(fams) < 2:  # 계열이 하나뿐인 형식은 깨짐 여부와 무관(원래 교차 확인 대상 아님)
        return False
    return len(_clean_engines(info)) <= 1


def ev(doc, info, value, hint=None):
    loc = locate_value(info["text"], value, hint)
    return [{"file": doc, "engine": info["ref"], **loc}] if loc else []


def _confirmed_in_head(info, needle, head):
    """needle이 서로 다른 인식 계열 몇 개의 출력 머리(head자)에 나오는지 — 교차 확인 수(AD36 A)."""
    n = S.normalize_value(needle)
    return len({info["fam"].get(e, e) for e, o in info["outs"].items() if n and n in S.normalize_value((o.get("text") or "")[:head])})


SHEET_NAME = re.compile(r"^(?:#+\s*)?(?:sheet|시트)\s*\d*$", re.I)  # 엑셀 대표 결과 첫 줄은 시트 이름('Sheet1') — 제목이 아님


def _first_line(info):
    """대표 결과의 제목 줄 — 시트 이름 줄은 건너뛰고, 엑셀처럼 한 줄에 시트 전체가 붙어 나오면('RFP Deal Terms — … (v1, 2025)
    [가상 예시] … 항목 값 MTOP …') 첫 ' ['·두 칸 이상 공백·탭 앞까지만."""
    line = next((ln.strip() for ln in (info.get("text") or "").splitlines() if ln.strip() and not SHEET_NAME.match(ln.strip())), "")
    return re.split(r"\s\[|\s{2,}|\t", line)[0].strip()


_WARNED_NO_STRUCTURE = False


def title_client(info, min_fams):
    """AD36 A(10-14) — 고객 라벨이 없는 계약서(synth-4clients 실측: 'Supply Agreement — Pfizer Inc. / … (C-PFE-2024-03)')는 고객명이
    제목 줄에만 있다 → 제목 줄의 회사 이름(법인 접미사 규칙, SI43④ draft_terms 재사용)이 서로 다른 계열 min_fams개 이상의
    머리(300자)에 나오고 그런 이름이 하나뿐일 때만 고객으로. 실측 전: client·count·sum 0문항."""
    try:
        from pipeline.transform.structure.draft_terms import (
            extract_candidate_orgs,
        )  # ponytail: rag-parse 이미지엔 structure가 없음 → 그땐 이 규칙만 꺼짐
    except ImportError:
        global _WARNED_NO_STRUCTURE
        if not _WARNED_NO_STRUCTURE:
            print("[auto_questions] SI43④ 회사 이름 규칙 끔 — structure 없음(rag-parse 이미지): 제목 고객 판별 안 함", file=sys.stderr)
            _WARNED_NO_STRUCTURE = True
        return None
    hits = [o for o in extract_candidate_orgs(_first_line(info)) if _confirmed_in_head(info, o, 300) >= min_fams]
    return {"label": "고객사(제목)", "value": hits[0], "fams": min_fams} if len(hits) == 1 else None


# AD36 A — 질문으로 쓸 가치가 없는 라벨(실측: 'H3 / Our response'·'FY2028'·쪽 번호·버전) — 표 좌표·연도 칸·문서 관리 칸
TRIVIAL_LABEL = re.compile(
    r"^(?:[A-Z]{0,2}\d{1,3}|FY\s?\d{2,4}|\d{4}년?|Q[1-4]|H[12]|page|쪽|p\.?|ver(?:sion)?\.?|버전|rev(?:ision)?\.?|개정|no\.?|#)$", re.I
)


def trivial_label(label):
    return any(TRIVIAL_LABEL.match(seg.strip()) for seg in label.split(" / "))


def _contract(pairs):
    """계약·견적·주문 번호 쌍 — 값이 ID 모양(terms.ID_LIKE, structure/bundle.py와 같은 규칙)인 것만, 계약 라벨 먼저.
    pick(CONTRACT_RE)는 '계약' 글자만 있어도 먼저 골라('계약기간(년) = 3'·'계약금액 = 7,650,000,000 KRW'·'Contract value') 그 뒤의
    진짜 '계약ID'를 놓친다. AD36 A(10-14) 실측: RFP 엑셀 '계약기간(년)'이 계약으로 세여 건수 오답 2/4 · 스캔 계약서 '계약ID' 놓침."""
    ok = [p for p in pairs if " / " not in p["label"] and CONTRACT_RE.search(p["label"]) and T.ID_LIKE.fullmatch(p["value"].strip())]
    return next((p for p in ok if CONTRACT_FIRST.search(p["label"])), ok[0] if ok else None)


def gen(docs, n, seed, min_fams):
    rnd = random.Random(seed)
    out = {"value": [], "client": [], "count": [], "sum": []}
    corpus = {d: i["text"] for d, i in docs.items()}
    meta = {}
    for doc, info in sorted(docs.items()):
        ps = info["pairs"]
        meta[doc] = {
            "client": pick(ps, CLIENT_RE, SUPPLIER_RE) or title_client(info, min_fams),
            "contract": _contract(ps),
            "price": pick(ps, PRICE_RE),
            "client_any": pick(info["all"], CLIENT_RE, SUPPLIER_RE),
            "contract_any": _contract(info["all"]),
        }
    # value
    cands = []
    for doc, info in sorted(docs.items()):
        con = meta[doc]["contract"]
        title = _first_line(info)
        if con:
            ident = f"계약번호 {con['value']} 문서"
        elif (
            8 <= len(title) <= 80 and _confirmed_in_head(info, title, 400) >= min_fams
        ):  # AD36 A — TF-IDF 단어('of state' 문서) 대신 교차 확인된 제목
            ident = f"'{title}' 문서"
        else:
            ident = "'" + " ".join(S.tfidf_top_terms(doc, corpus, n=2)) + "' 문서"
        for p in info["pairs"]:
            if p is con or not NUM_RE.search(p["value"]) or (meta[doc]["price"] is p) or trivial_label(p["label"]):
                continue
            if S.normalize_value(p["value"]) in S.normalize_value(p["label"]):
                continue
            cands.append((doc, ident, p))
    answers = defaultdict(set)  # AD36 A — 같은 질문 글자에 정답이 둘 이상이면(문서 지칭이 겹침) 답이 하나로 안 정해짐 → 제외
    for _doc, ident, p in cands:
        answers[(ident, p["label"])].add(S.normalize_value(p["value"]))
    cands = [c for c in cands if len(answers[(c[1], c[2]["label"])]) == 1]
    rnd.shuffle(cands)
    for i, (doc, ident, p) in enumerate(cands[:n]):
        out["value"].append(
            {
                "id": f"auto-value::{i}",
                "category": "value",
                "question": f"{ident}에서 '{p['label']}'의 값은 얼마입니까?",
                "answer": p["value"],
                "docs": [doc],
                "doc": doc,
                "query": f"{p['label']} {ident.split(' ')[1] if con_of(meta, doc) else ''}".strip(),
                "families": p["fams"],
                "gold_evidence": ev(doc, docs[doc], p["value"], p["label"].split(" / ")[0]),
            }
        )
    # client
    cands = [(doc, m) for doc, m in sorted(meta.items()) if m["client"] and m["contract"] and m["price"]]
    rnd.shuffle(cands)
    for i, (doc, m) in enumerate(cands[:n]):
        out["client"].append(
            {
                "id": f"auto-client::{i}",
                "category": "client",
                "client": m["client"]["value"],
                "question": f"고객사 {m['client']['value']}의 계약(번호 {m['contract']['value']}) {m['price']['label']}은(는) 얼마입니까?",
                "answer": m["price"]["value"],
                "docs": [doc],
                "doc": doc,
                "query": f"{m['client']['value']} {m['contract']['value']} {m['price']['label']}",
                "families": min(m["client"]["fams"], m["price"]["fams"]),
                "gold_evidence": ev(doc, docs[doc], m["price"]["value"]),
            }
        )
    # count · sum (고객사별, 계약 번호당 한 번)
    by_client, weak, copies = (
        defaultdict(dict),
        defaultdict(set),
        defaultdict(list),
    )  # 고객사 정규화 → {계약번호: 문서} · 단일 엔진 후보가 섞인 고객사
    unverified = defaultdict(set)  # 고객사 정규화 → 글자 깨짐으로 교차 확인 자체가 안 된 문서(집계엔 안 넣음, '미확인 문서' 표시용, E12)
    names = {}
    # 확인된 계약 문서에 함께 나온 다른 번호(견적·주문 번호) → 그 계약 번호: 계약 번호를 못 읽은 사본이 견적 번호로 잡혀도 같은 계약으로
    alias = {}
    for doc, m in meta.items():
        if m["contract"]:
            for p in docs[doc]["pairs"]:
                if CONTRACT_RE.search(p["label"]) and " / " not in p["label"]:
                    alias[S.normalize_value(p["value"])] = m["contract"]["value"]
    known = {m["client"]["value"] for m in meta.values() if m["client"]}

    def text_client(doc):
        """고객 라벨이 없는 문서(메일 본문 'Northfield Biologics 담당자님') — 확인된 고객명이 서로 다른 계열 파서 min_fams개 이상의
        본문 머리(1,000자 — 메일은 앞에 헤더·문서 속성 잡음이 붙음)에 나오면 그 고객(정답 생성이 검색 대상 시스템과 독립이도록 파싱 결과만 씀, 백로그 E12)."""
        info = docs[doc]
        hits = [
            c
            for c in known
            if len(
                {
                    info["fam"].get(e, e)
                    for e, o in info["outs"].items()
                    if S.normalize_value(c) in S.normalize_value((o.get("text") or "")[:1000])
                }
            )
            >= min_fams
        ]
        return {"value": hits[0], "fams": min_fams} if len(hits) == 1 else None

    def maybe_client(doc):
        """'미확인 문서' 후보(E12) — 교차 확인(min_fams)은 못 됐지만 글자가 안 깨진(읽을 수 있는) 계열
        1개라도 본문 머리에 확인된 고객명이 있으면 후보로(집계엔 안 넣고 표시만). 깨진 계열의 텍스트는
        후보 찾기에도 안 씀 — 오해석된 글자가 우연히 다른 고객명과 겹쳐 보여도 근거로 안 삼는다
        (E12 독립 검토 MINOR)."""
        clean = _clean_engines(docs[doc])
        cands = [c for c in known if any(S.normalize_value(c) in S.normalize_value(t[:1000]) for t in clean.values())]
        return cands[0] if len(cands) == 1 else None

    for doc, m in sorted(meta.items()):
        cl, co = m["client"] or m["client_any"], m["contract"] or m["contract_any"]
        if co and not cl:
            cl = text_client(doc)
        if co and not cl and _garbled_doc(docs[doc]):
            mc = maybe_client(doc)
            if mc:
                unverified[S.normalize_value(mc)].add(doc)
        if co and not m["contract"] and S.normalize_value(co["value"]) in alias:
            co = {**co, "value": alias[S.normalize_value(co["value"])]}
        if cl and co:
            ck = S.normalize_value(cl["value"])
            if m["client"]:
                names[ck] = cl["value"]
            else:
                names.setdefault(ck, cl["value"])
            key = S.normalize_value(co["value"])
            if not m["contract"]:
                near = next((k for k in by_client[ck] if k != key and _lev1(k, key)), None)
                if near:  # OCR 오인식(한 글자 차이) → 같은 계약
                    weak[ck].add(doc)
                    continue
            if key not in by_client[ck] or m["contract"]:
                by_client[ck][key] = doc
            copies[(ck, key)].append(doc)
            if not (m["client"] and m["contract"]):
                weak[ck].add(doc)
    for ck in sorted(
        by_client, key=lambda k: len(by_client[k])
    ):  # OCR 한 글자 오탈자 고객명(같은 PP-OCR 계열 두 엔진이 같이 틀림 'Northfeld') → 문서 많은 쪽으로
        big = next((o for o in by_client if o != ck and len(by_client[o]) > len(by_client[ck]) and len(ck) >= 6 and _lev1(ck, o)), None)
        if big:
            for key, d in by_client.pop(ck).items():
                by_client[big].setdefault(key, d)
            weak[big] |= weak.pop(ck, set()) | set(by_client[big].values())
            unverified[big] |= unverified.pop(ck, set())
    counted = {d for ds in copies.values() for d in ds} | {d for ws in weak.values() for d in ws}
    uncounted = defaultdict(
        set
    )  # 고객 → 집계에 못 넣은 계약 문서(E12 unverified_docs '글자 깨짐'과 다른 이유라 칸을 따로 — E12 독립 검토 MAJOR)
    for doc, m in sorted(meta.items()):  # AD34(10-14) — 교차 확인 못 한 계약 문서(스캔 OCR 1계열뿐 등)가 고객명을 말하면 집계가 덜 셈
        if doc in counted or not m["contract_any"]:
            continue
        heads = [S.normalize_value((o.get("text") or "")[:1000]) for o in docs[doc]["outs"].values()]
        named = [ck for ck, name in names.items() if any(S.normalize_value(name) in h for h in heads)]
        for ck in named or names:  # 고객명도 못 읽은 계약(스캔 OCR이 제목을 놓침) → 어느 고객 것인지 몰라 모든 고객이 불완전
            uncounted[ck].add(doc)  # 실측: synth-4clients 스캔 갱신 계약 4건 → 건수 정답 2·5·3이 실제 3·7·4
    keys = sorted(by_client)
    rnd.shuffle(keys)
    for i, ck in enumerate(keys[:n]):
        cons = by_client[ck]
        row = {
            "id": f"auto-count::{i}",
            "category": "count",
            "client": names[ck],
            "question": f"고객사 {names[ck]}와 맺은 서로 다른 계약 건수는 몇 건입니까?",
            "answer": len(cons),
            "tolerance": 0,
            "docs": sorted(cons.values()),
            "query": f"{names[ck]} 계약",
            "families": 1 if weak[ck] else min_fams,
            "unconfirmed_docs": sorted(weak[ck]),
            "gold_evidence": [
                e for c, d in sorted(cons.items()) for e in ev(d, docs[d], (meta[d]["contract"] or meta[d]["contract_any"])["value"])
            ],
        }
        if unverified.get(ck):  # 글자 깨져 교차 확인 자체가 안 된 문서 — 집계엔 안 넣고 '미확인 문서'로만 표시(E12)
            row["unverified_docs"] = sorted(unverified[ck])
        if uncounted.get(ck):  # AD34 — 교차 확인 못 한 계약 문서(스캔 OCR 1계열 등): 건수가 실제보다 작을 수 있음
            row["incomplete_docs"] = sorted(uncounted[ck])
        out["count"].append(row)
    per_contract = {}  # (고객사, 계약) → (합계, 단위, 근거, 문서) — 수량 행을 전부 확인한 사본이 있을 때만
    for (ck, key), ds in copies.items():
        for d in ds:
            qs, n_rows = confirmed_qty(docs[d], min_fams, with_total=True)
            if qs and len(qs) == n_rows:
                per_contract[(ck, key)] = (
                    sum(num(v) for _, v, _ in qs),
                    next((u for *_, u in qs if u), None),
                    [e for label, v, _ in qs for e in ev(d, docs[d], v, label.split(" / ")[0])],
                    d,
                )
                break
    for ck in keys:  # 고객사 합계: 그 고객사의 모든 계약이 확인됐을 때만(하나라도 빠지면 합계가 틀림)
        if len(out["sum"]) >= n:
            break
        parts = [per_contract.get((ck, key)) for key in by_client[ck]]
        no_table = [
            key
            for key in by_client[ck]
            if (ck, key) not in per_contract and not any(QTY_RE.search(docs[d]["text"]) for d in copies[(ck, key)])
        ]
        parts = [x for x, key in zip(parts, by_client[ck]) if key not in no_table]  # 수량 표 자체가 없는 계약은 0
        if not parts or any(x is None for x in parts):
            continue
        unit = next((x[1] for x in parts if x[1]), "")
        out["sum"].append(
            {
                "id": f"auto-sum::client::{len(out['sum'])}",
                "category": "sum",
                "client": names[ck],
                "unit": unit,
                "question": f"고객사 {names[ck]}에 공급한 총 수량{f'({unit})' if unit else ''}은 얼마입니까?",
                "answer": round(sum(x[0] for x in parts), 3),
                "tolerance": 0.005,
                "docs": sorted(x[3] for x in parts),
                "query": f"{names[ck]} 수량 합계",
                "families": min_fams,
                "gold_evidence": [e for x in parts for e in x[2]],
            }
        )
    cands = sorted(per_contract.items(), key=lambda kv: kv[0])
    rnd.shuffle(cands)
    for (ck, _key), (tot, unit, evs, d) in cands:  # 계약별 합계(표 한 개 안의 행 합)
        if len(out["sum"]) >= n:
            break
        con = (meta[d]["contract"] or meta[d]["contract_any"])["value"]
        out["sum"].append(
            {
                "id": f"auto-sum::contract::{len(out['sum'])}",
                "category": "sum",
                "client": names[ck],
                "contract": con,
                "unit": unit or "",
                "question": f"계약번호 {con}의 품목 수량을 모두 더하면 총 수량{f'({unit})' if unit else ''}은 얼마입니까?",
                "answer": round(tot, 3),
                "tolerance": 0.005,
                "docs": [d],
                "doc": d,
                "query": f"{con} 수량",
                "families": min_fams,
                "gold_evidence": evs,
            }
        )
    out.update(
        multi_doc(docs, meta, names, n, rnd, min_fams, incomplete={ck for d in (unverified, uncounted, weak) for ck, ds in d.items() if ds})
    )
    for rows in out.values():
        for r in rows:
            k = r.get("families", min_fams)
            note = (
                f"자동(교차 확인 {k}계열 이상)"
                if k >= min_fams
                else f"자동(일부 단일 엔진 — 확인 필요: {', '.join(r.get('unconfirmed_docs', []))[:120]})"
            )
            if r.get(
                "unverified_docs"
            ):  # 글자 깨짐 등으로 교차 확인 자체가 안 된 문서 — 건수가 확정 값처럼 보이지 않게 표시가 따라가게(E12)
                note += f" · 미확인 문서 {len(r['unverified_docs'])}건(집계 제외): {', '.join(r['unverified_docs'])[:120]}"
            if r.get("incomplete_docs"):  # AD34 — 교차 확인 못 한 계약 문서가 있어 건수가 더 클 수 있음(사람 확인 대상)
                note += (
                    f" · 확인 못 한 계약 문서 {len(r['incomplete_docs'])}건(건수가 더 클 수 있음): {', '.join(r['incomplete_docs'])[:120]}"
                )
            r.update({"auto": True, "gold_source": note})
    return out


PRODUCT_RE = re.compile(r"^(?:product|제품|품목)(?:\s*(?:code|코드))?$", re.I)
SIGNED_RE = re.compile(r"^(?:signed|signed\s*date|체결일|계약일|signing\s*date)$", re.I)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CURRENCY = re.compile(r"[A-Z]{3}|원|달러")


def multi_doc(docs, meta, names, n, rnd, min_fams, incomplete=()):
    """AD34(10-14) — 여러 문서를 합쳐야 답할 수 있는 질문(LLM 0회, 정답은 교차 확인된 값으로 코드가 계산).
    대상 = 고객·계약 번호가 둘 다 교차 확인된 계약 문서(약한 사본은 안 씀 — 다문서 정답은 하나만 틀려도 틀림).
      compare: 같은 고객의 두 계약(같은 통화) 중 단가가 더 높은 계약 번호
      latest : 같은 고객·같은 제품 계약 2건 이상 → 체결일(YYYY-MM-DD)이 가장 늦은 계약의 단가
      list   : 같은 고객 계약 2건 이상 → 계약 번호 전부(answer_keywords — mcp_eval이 기존 키워드 채점으로 잼)
    incomplete = 교차 확인 못 한 계약 문서가 그 고객을 말하거나, 약하게(OCR 근사·본문 고객명) 센 계약이 있는 고객 → list·latest는 안 만듦(빠진 계약이 정답을 바꿈 — 목록에 빠지거나
    더 늦은 갱신 계약일 수 있음). compare는 두 계약만 보므로 그대로.
    정답마다 근거 문서 2개 이상. 문서↔계약 결합(RFI·견적 → 계약)·연도별 추이는 아직 안 함(근거 연결 규칙이 더 필요)."""
    out = {"compare": [], "latest": [], "list": []}
    rows = defaultdict(list)  # 고객 정규화 → [(계약 번호, 문서, 단가쌍, 제품, 체결일)]
    for doc, m in sorted(meta.items()):
        if not (m["client"] and m["contract"]):
            continue
        ps = docs[doc]["pairs"]
        prod, signed = _pick(ps, PRODUCT_RE), _pick(ps, SIGNED_RE)
        rows[S.normalize_value(m["client"]["value"])].append(
            (
                m["contract"]["value"],
                doc,
                m["price"],
                prod and prod["value"],
                signed and ISO_DATE.match(signed["value"].strip()) and signed["value"].strip(),
            )
        )
    ev2 = lambda d, v, hint=None: ev(d, docs[d], v, hint)
    for ck in sorted(rows):
        rs = sorted({r[0]: r for r in rows[ck]}.values())  # 같은 계약 번호 사본은 하나만
        name = names.get(ck) or meta[rs[0][1]]["client"]["value"]
        if len(rs) >= 2 and ck not in incomplete:
            ids = [r[0] for r in rs]
            out["list"].append(
                {
                    "id": f"auto-list::{len(out['list'])}",
                    "category": "list",
                    "client": name,
                    "question": f"고객사 {name}와 맺은 계약의 계약 번호를 모두 나열해 주세요.",
                    "answer": ", ".join(ids),
                    "answer_keywords": ids,
                    "docs": [r[1] for r in rs],
                    "query": f"{name} 계약 번호",
                    "families": min_fams,
                    "gold_evidence": [e for cid, d, *_ in rs for e in ev2(d, cid)],
                }
            )
        priced = [r for r in rs if r[2] and num(r[2]["value"]) is not None]
        pairs = [
            (a, b)
            for i, a in enumerate(priced)
            for b in priced[i + 1 :]
            if nlabel(a[2]["label"]) == nlabel(b[2]["label"])  # 같은 칸끼리만(단가 vs 계약금액 섞임 방지 — 독립 검토 10-14 MAJOR)
            and (CURRENCY.findall(a[2]["value"]) or [""])[0] == (CURRENCY.findall(b[2]["value"]) or [""])[0]
            and num(a[2]["value"]) != num(b[2]["value"])
        ]
        if pairs:
            a, b = rnd.choice(pairs)
            hi = max((a, b), key=lambda r: num(r[2]["value"]))
            out["compare"].append(
                {
                    "id": f"auto-compare::{len(out['compare'])}",
                    "category": "compare",
                    "client": name,
                    "question": f"고객사 {name}의 계약 {a[0]}와 {b[0]} 중 {a[2]['label']}이(가) 더 높은 계약은 어느 것입니까?",
                    "answer": hi[0],
                    "docs": [a[1], b[1]],
                    "query": f"{name} {a[0]} {b[0]} {a[2]['label']}",
                    "families": min_fams,
                    "gold_evidence": ev2(a[1], a[2]["value"]) + ev2(b[1], b[2]["value"]),
                }
            )
        by_prod = defaultdict(list)
        for r in priced:
            if r[3] and r[4]:
                by_prod[S.normalize_value(r[3])].append(r)
        for grp in by_prod.values():
            if (
                ck in incomplete or len(grp) < 2 or len({r[4] for r in grp}) < len(grp)
            ):  # 체결일이 같은 계약이 있으면 '최신'이 하나로 안 정해짐
                continue
            last = max(grp, key=lambda r: r[4])
            out["latest"].append(
                {
                    "id": f"auto-latest::{len(out['latest'])}",
                    "category": "latest",
                    "client": name,
                    "product": last[3],
                    "question": f"고객사 {name}의 제품 {last[3]} 계약 중 체결일이 가장 늦은 계약의 {last[2]['label']}은(는) 얼마입니까?",
                    "answer": last[2]["value"],
                    "docs": [r[1] for r in grp],
                    "query": f"{name} {last[3]} 최신 계약 {last[2]['label']}",
                    "families": min_fams,
                    "gold_evidence": [e for r in grp for e in ev2(r[1], r[4])] + ev2(last[1], last[2]["value"]),
                }
            )
    for k in out:
        rnd.shuffle(out[k])
        out[k] = out[k][:n]
    return out


def _lev1(a, b):
    """편집 거리 ≤ 1."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    return any(a == b[:i] + b[i + 1 :] for i in range(len(b)))


def con_of(meta, doc):
    return meta[doc]["contract"] is not None


def confirmed_qty(info, min_fams, with_total=False):
    """표의 수량·용량 열 셀 — 기준 엔진 표에서 읽고, 다른 계열 파서 텍스트의 같은 줄(행 라벨·값 함께)로 확인."""
    out, seen = [], set()
    ref = info["outs"][info["ref"]]
    for row, header, cells in table_rows(ref):
        qi = next((i for i, h in enumerate(header) if QTY_RE.search(h)), None)
        if qi is None or num(cells[qi]) is None or (row, cells[qi]) in seen:
            continue
        seen.add((row, cells[qi]))
        rn, vn = S.normalize_value(row), S.normalize_value(cells[qi])
        fams = {
            info["fam"].get(e, e)
            for e, d in info["outs"].items()
            if any(rn in S.normalize_value(ln) and vn in S.normalize_value(ln) for ln in d["text"].splitlines())
        }
        if len(fams) >= min_fams:
            unit = (re.search(r"\(([^)]+)\)", header[qi]) or [None, None])[1]
            out.append((f"{row} / {header[qi]}", cells[qi], unit))
    return (out, len(seen)) if with_total else out


def check_truth(qs, truth_path):
    """개발 PC: 자동 정답을 가상 문서 정답(truth.json)과 대조 — 유형별 맞은 수."""
    from pipeline.eval import make_questions as MQ  # 옛 맨 이름 import(make_questions)는 모듈을 못 찾았음(10-29)

    truth = json.loads(Path(truth_path).read_text(encoding="utf-8"))
    res = {}
    for cat, rows in qs.items():
        ok = 0
        for r in rows:
            if cat in ("value", "client"):
                vals = [S.normalize_value(v.get("value", "")) for v in (truth.get(r["doc"]) or {}).get("values", [])]
                ok += S.normalize_value(r["answer"]) in vals
            elif r.get("contract"):
                tt = (truth.get(r["doc"]) or {}).get("tables") or []
                g = sum(
                    MQ._num(row[MQ._qty_col(t[0])]) or 0
                    for t in tt
                    if len(t) > 1 and MQ._qty_col(t[0]) is not None
                    for row in t[1:]
                    if MQ._qty_col(t[0]) < len(row)
                )
                ok += abs(g - float(r["answer"])) <= max(1e-9, abs(g) * r.get("tolerance", 0))
            else:
                gen = MQ.gen_count_questions if cat == "count" else MQ.gen_sum_questions
                from pipeline.eval.anchors import content_groups

                tq = gen(truth, content_groups([d for d in truth if not d.startswith("_")], truth), 999, 0)
                gold = {S.normalize_value(t.get("client", "")): t["answer"] for t in tq if t.get("client")}
                g = gold.get(S.normalize_value(r["client"]))
                ok += g is not None and abs(float(g) - float(r["answer"])) <= max(1e-9, abs(float(g)) * r.get("tolerance", 0))
        res[cat] = (ok, len(rows))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--parse-dir", default="output/parse")
    ap.add_argument("--src", default="output/prepared")
    ap.add_argument("--out", default="output/eval/questions.jsonl")
    ap.add_argument("--per-category", type=int, default=20)
    ap.add_argument("--min-fams", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rfi", help="RFI 예시·이력 문항 jsonl(질문 스키마) — 그대로 합침")
    ap.add_argument("--check-truth", help="(개발 PC) truth.json과 대조해 유형별 정답 수 출력")
    a = ap.parse_args(argv)
    docs = build(a.parse_dir, a.src, a.min_fams)
    qs = gen(docs, a.per_category, a.seed, a.min_fams)
    rows = [r for cat in qs for r in qs[cat]]  # AD34 — compare·latest·list 포함(gen이 정한 순서)
    if a.rfi:
        rows += [
            {**json.loads(line), "gold_source": "RFI 예시·이력"}
            for line in Path(a.rfi).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_ev = sum(bool(r.get("gold_evidence")) for r in rows)
    n_unv = sum(len(r.get("unverified_docs") or []) for r in rows)
    print(
        f"문서 {len(docs)}개 · 교차 확인 쌍 {sum(len(i['pairs']) for i in docs.values())}개 → 문항 {len(rows)}개("
        + " · ".join(f"{c} {len(qs[c])}" for c in qs)
        + (" · rfi(예시) 포함" if a.rfi else "")
        + f") · 근거 위치 있는 문항 {n_ev}"
        + (f" · 미확인 문서 {n_unv}건(집계 제외, 건수 정답에 표시)" if n_unv else "")
        + f" → {a.out}"
    )
    if a.check_truth:
        for cat, (ok, n) in check_truth(qs, a.check_truth).items():
            print(f"  정답 대조 {cat}: {ok}/{n}")
    from common.core.runlog import note

    note(f"자동 문항 {len(rows)}개(" + " · ".join(f"{c} {len(qs[c])}" for c in qs) + f") → {a.out}")


if __name__ == "__main__":
    utf8_stdout()
    main()
