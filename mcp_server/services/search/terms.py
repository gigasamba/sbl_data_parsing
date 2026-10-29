"""검색 전용 용어 사전·질의 확장 — match_concepts(X4)·expand_query(BM25 질의 확장, X3+SI43)·lookup_term(X4)·
vector_alias_text(SI43⑤ 벡터 질의 임베딩 별칭). 공용 로더(load_glossary·load_draft_glossary·_aliases)·공용 규칙
(_name_pat·_name_hit·split_terms·norm·related_concepts, 구조화 bundle.py와 같은 규칙)은 common.core.terms에서
그대로 가져다 쓴다(캐시·명부는 공용 쪽 한 곳 — 복제 금지)."""

import re

from common.core.terms import (
    _aliases,
    _name_hit,
    _name_pat,
    load_draft_glossary,
    load_glossary,
    norm,
    related_concepts,
    split_terms,
)
from common.core.text import tokens
from mcp_server import config as mc  # 설정 객체(S7d)

GLOSSARY_WEIGHTS = {"synonym": 1.0, "abbreviation": 0.8, "weak": 0.3}  # X3 — BM25 확장 가중치
ALIAS_EXPAND_MAX = 20  # SI43 — 질문 1건당 명부(roster)만 있는 별칭으로 추가하는 토큰 상한(명부가 커져도 확장이 폭주하지 않게)


# BR58 — common.core.text.tokens()의 일반 토큰 정규식(`[A-Za-z0-9가-힣][…]*`)은 "("·")"에서 끊긴다. "미르하제약(주)"처럼
# 법인 표기(한글 (주)·(유), 괄호 안 한 글자)가 낀 canonical이 그대로 tokens()에 들어가면 "주" 같은 한 글자가 독립
# 토큰으로 나온다 — 한글에서 극히 흔한 음절이라(요일·주식·매주 등) BM25 가중치 1.0으로 더해지면 그 글자가 든
# 무관 문서 전부가 끌어올라온다(실측 BR58 XL017/018 — 미르하 견적서·용량 질문이 '주'로 들러붙은 다른 미르하 관련
# 문서 수십 건에 밀려 doc_hit5 미스). "Inc."·"Corp." 같은 영문 법인 접미는 그대로 둔다 — 토큰 자체가 2자 이상이라
# 이 잡음이 안 생기고, 오히려 실제 분간 신호일 수 있다(실측: pfizer_global_supply_2026.txt는 본문에 "Pfizer Inc."를
# 두 번 쓰는데 한국지사 쌍둥이 문서(화이자_한국지사_계약_2026.txt)는 "Inc."가 전혀 없다 — 접미를 통째로 지우면
# XL012·XL014가 그 한국지사 문서에 밀려 새로 미스가 됐다, 되돌림). 그래서 문자열을 건드리지 않고 토큰화 뒤
# 결과만 거른다: 숫자가 아닌 한 글자 토큰만 뺀다(한 글자 한글/영문은 BM25에서 거의 항상 잡음, 2자 이상은 안 건드림).
def _exp_tokens(s):
    """glossary 문자열(canonical·synonym·alias) → BM25 확장 토큰 — QUERY_EXPAND_SHORTTOK(기본 켬, =0으로 끔)이면
    숫자가 아닌 한 글자 토큰(법인 표기 괄호에서 끊겨 나온 "주" 류)을 뺀다. expand_query 두 호출부 공용."""
    toks = tokens(s)
    if not mc.cfg().search.query_expand.shorttok:
        return toks
    return [t for t in toks if len(t) > 1 or t.isdigit()]


def _entry_hit(q, r):
    """사전 한 개념이 질문에 나왔는지 — 가장 긴 표기 우선. canonical·synonyms는 항상 대소문자 무시(경계는
    _name_pat의 `\\b`/한글 조사 lookaround가 맡아 "MSDS"·"words" 안의 "DS"처럼 단어 중간에서 안 걸림).
    abbreviations는 case_sensitive=Y면 저장된 대소문자 그대로만, 그 외(기본값, 10-14 바이오/CDMO 용어 대소문자
    무시 작업)는 대소문자 무시. weak_synonyms는 원래부터 대소문자 구분 칸이 없어 항상 대소문자 무시(예:
    BIZ.CDMO weak_synonyms의 "CMO"·"CDO" — 다른 개념의 약어를 관련어로 얹어둔 것).

    abbreviations·weak_synonyms 중 **3자 이하**(DS·DP·PM·CMO·CDO·CRO·DAR처럼 소문자·일반 단어와 겹쳐
    동음이의 위험이 큰 짧은 표기, 독립 검토 10-14②에서 2자→3자로 확대 + weak_synonyms까지 포함: "cmo"
    (BIZ.CDMO weak_synonym 경로로 새어나가던 것)·"cdo tranche"·"cro survey"·"dar window" 같은 소문자
    잡음 실측)인데 대소문자가 다르게(예: 소문자) 맞은 경우는 `context_required`(행 공통, 길이·출처 칸
    무관하게 적용되는 기존 조건)가 비어 있어도 **추가로** 문맥 단어가 있어야만 인정 — 저장된 대소문자
    그대로(보통 대문자) 맞았을 때는 이 추가 조건이 안 걸림(기존 동작과 바이트 동일). canonical·synonyms
    (항상 뜻이 분명한 정식 표기)는 짧아도 이 가드 대상이 아님(이 사전엔 짧은 strong synonym이 없음).
    context_required가 채워진 행은 길이·대소문자·출처와 무관하게 이미 그 조건을 타므로 별도 처리 불필요.
    없으면 None."""
    canon = r.get("canonical") or ""
    cs = (r.get("case_sensitive") or "").upper() == "Y"
    abbrs = split_terms(r.get("abbreviations"))
    weaks = split_terms(r.get("weak_synonyms"))
    cands = [(canon, False)] + [(s, False) for s in split_terms(r.get("synonyms"))] + [(s, False) for s in weaks] + [(s, cs) for s in abbrs]
    cands = sorted((x for x in cands if x[0]), key=lambda x: -len(x[0]))
    hit, exact_case = None, True
    for s, sc in cands:
        if _name_pat(s, 0 if sc else re.I).search(q):
            hit = s
            exact_case = sc or bool(_name_pat(s, 0).search(q))  # case_sensitive 행은 이미 정확한 대소문자만 걸림
            break
    if hit is None:
        return None
    ctx = split_terms(r.get("context_required"))
    if ctx and not any(_name_pat(c).search(q) for c in ctx):
        return None
    if hit in (abbrs + weaks) and len(hit) <= 3 and not exact_case and not ctx:
        return None  # 짧은 약어·약한 동의어(3자 이하)가 다른 대소문자로만 맞았고 문맥 단어도 없으면 기각(동음이의 사고 방지)
    return hit


def match_concepts(q, glossary=None):
    """질문에 나온 개념 ID 목록(X4 — lookup_term·search methods=concept)."""
    glossary = load_glossary() if glossary is None else glossary
    return [cid for cid, r in glossary.items() if _entry_hit(q, r)]


def expand_query(q, glossary=None, aliases=None, draft_glossary=None):
    """BM25 질의 확장(X3 용어 사전 + SI43 명부 별칭) — 벡터 질의는 바꾸지 않음(호출부가 원문 q를 따로 임베딩).
    {토큰: 가중치}, 적용 노트 목록. QUERY_EXPAND=0이면 원 토큰(가중치 1.0)만 — 끔 스위치(둘 다 끔).
    SI43(XL008): 용어집에 없는 순수 명부(roster, stack.json client_aliases·CLIENT_ROSTER) 전용 별칭도 — 질문에
    한쪽 표기가 나오면(SI43⑦ 조사 규칙 포함, _name_hit) 같은 고객의 다른 표기를 가중치 1.0으로(용어집 쪽은 위
    루프가 이미 처리, 겹치면 추가 토큰 없음 → 중복 note 없음) — ALIAS_EXPAND_MAX로 토큰 수 상한, 결정적 순서
    (길이 내림·이름 오름).
    SI43④ draft_glossary(기본 None → load_draft_glossary(), 즉 output/ 자동 draft CSV의 status=draft 행 — GLOSSARY_DIR/
    domain_terms.csv가 아님, 독립 검토 BLOCK 1) — 사람 승인 없이 쌓인 새 이름 후보도 BM25에 weak(0.3)로만(승격
    전엔 approved 취급 안 함 — match_clients·하드 필터에는 안 들어간다, _aliases()는 GLOSSARY_DIR approved
    org_client만 봄) · QUERY_EXPAND_DRAFT=0이면 draft 확장을 끔."""
    terms = {t: 1.0 for t in tokens(q)}
    notes = []
    if not mc.cfg().search.query_expand.enabled:
        return terms, notes
    glossary = load_glossary() if glossary is None else glossary
    for cid, r in glossary.items():
        hit = _entry_hit(q, r)
        if hit is None:
            continue
        canon = r.get("canonical") or ""
        groups = (
            [(canon, GLOSSARY_WEIGHTS["synonym"])]
            + [(s, GLOSSARY_WEIGHTS["synonym"]) for s in split_terms(r.get("synonyms"))]
            + [(s, GLOSSARY_WEIGHTS["abbreviation"]) for s in split_terms(r.get("abbreviations"))]
            + [(s, GLOSSARY_WEIGHTS["weak"]) for s in split_terms(r.get("weak_synonyms"))]
        )
        added = False
        for s, w in groups:
            if not s or s == hit:
                continue
            for t in _exp_tokens(s):
                if terms.get(t, 0.0) < w:
                    terms[t] = w
                    added = True
        if added:
            notes.append(f"{hit}→{canon}({cid})")
    aliases = _aliases() if aliases is None else aliases
    budget = ALIAS_EXPAND_MAX
    for canon in sorted(aliases, key=lambda c: (-len(c), c)):  # 결정적 순서(전순서) — 명부가 커져도 재현 가능
        if budget <= 0:
            break
        names = [canon] + list(aliases.get(canon, []))
        hit = next((n for n in names if _name_hit(n, q)), None)
        if hit is None:
            continue
        spellings = sorted(set(names) - {hit})
        new_tokens = sorted({t for s in spellings for t in _exp_tokens(s) if terms.get(t, 0.0) < 1.0})[:budget]
        if not new_tokens:
            continue
        for t in new_tokens:
            terms[t] = 1.0
        notes.append(f"{hit}→{canon}(alias)")
        budget -= len(new_tokens)
    if mc.cfg().search.query_expand.draft:
        draft_glossary = load_draft_glossary() if draft_glossary is None else draft_glossary
        for cid, r in sorted(draft_glossary.items()):  # 결정적 순서(concept_id 오름)
            hit = _entry_hit(q, r)
            if hit is None:
                continue
            canon = r.get("canonical") or ""
            weak = GLOSSARY_WEIGHTS["weak"]
            added = False
            for t in _exp_tokens(canon):
                if terms.get(t, 0.0) < weak:
                    terms[t] = weak
                    added = True
            if added or hit != canon:
                notes.append(f"{hit}→{canon}({cid}, draft)")
    return terms, notes


def lookup_term(term, glossary=None):
    """표기(정식명·동의어·약어) → 개념 정의·별칭·관련 개념(X4 lookup_term). 없으면 None."""
    glossary = load_glossary() if glossary is None else glossary
    tn = norm(term)
    hit = next(
        (
            item
            for item in glossary.items()
            if any(
                norm(s) == tn
                for s in [item[1].get("canonical")] + split_terms(item[1].get("synonyms")) + split_terms(item[1].get("abbreviations"))
                if s
            )
        ),
        None,
    )
    if hit is None:
        return None
    cid, r = hit
    aliases = set(split_terms(r.get("synonyms"))) | set(
        _aliases().get(r["canonical"], [])
    )  # SI43⑥ — 고객이면 명부(stack.json·CLIENT_ROSTER) 별칭도(비 고객 항목은 명부에 canonical이 없어 그대로)
    return {
        "concept_id": cid,
        "canonical": r["canonical"],
        "category": r.get("category"),
        "definition_ko": r.get("definition_ko"),
        "definition_en": r.get("definition_en"),
        "aliases": sorted(aliases),
        "abbreviations": split_terms(r.get("abbreviations")),
        "related": related_concepts(cid, glossary),
    }


_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _script(name):
    """G17 — 문자 체계 판별: 한글 포함='ko' · 그 외 라틴 알파벳 포함='lat' · 둘 다 없으면 None(판별 불가)."""
    if _HANGUL_RE.search(name):
        return "ko"
    if _LATIN_RE.search(name):
        return "lat"
    return None


def vector_alias_text(q, aliases=None):
    """SI43⑤ — 벡터 질의 임베딩 입력에만 명부 별칭의 다른 표기를 덧붙인다(원문 q는 그대로 돌려주지 않고, 호출부가
    표시·BM25에는 원문을 계속 쓰고 이 함수의 반환값은 임베딩 호출 한 곳에만 — retriever.py _search_ex). 설계 배경
    (server.md SI43⑤): 한글 질문 '셀트리온' ↔ 영어 문서 'Celltrion'처럼 BM25는 expand_query가 토큰을 맞춰 주지만
    벡터는 원문 그대로라 표기가 다르면 각 언어 임베딩이 멀어질 수 있다 — 질문에 나온 표기(명부 쪽, _name_hit로
    조사 포함 탐지)를 찾으면 같은 고객의 '다른 문자 체계' 표기만(_script — 한글 [가-힣] vs 라틴 [A-Za-z], 둘 다
    아니면 비교 불가로 건너뜀) 결정적 순서(이름 오름차순)로 괄호에 덧붙인다(같은 문자 체계 별칭은 BM25
    expand_query가 이미 커버해 여기선 뺀다). G17(10-14, 독립 검토 MAJOR 10-13 후속 실측, docs/backlog/search.md) —
    이 교차언어 전용 제한을 넣고도 synth-4clients 115문항 noise5가 여전히 0.01 넘게 오른다(0.438→0.45):
    고객 캐노니컬 표기 자체가 영문(Pfizer Inc. 등)이라 한글 별칭(화이자) 질문에서 그 캐노니컬이 이미 '교차
    언어'로 걸려 덧붙는다 — 같은 체계 별칭(화이자 본사·미르하 등)만 빠지고 회귀의 주 원인은 그대로 남음.
    synth-xling 이득(gold_top1 0.409→0.591)이 4clients 손실(doc_hit5 −0.009·gold_top1 −0.002·noise5 +0.012,
    noise5만 문턱 0.01을 0.002 넘김)보다 커서 **사용자 결정(10-14)으로 기본 켬** — 규칙 예외, 10-16 서버 실문서로
    켬/끔 재확인. SEARCH_VECTOR_ALIAS_EXPAND=0이면 끔(q 그대로, 바이트 동일)."""
    if not mc.cfg().search.vector_alias_expand:
        return q
    aliases = _aliases() if aliases is None else aliases
    extra = []
    for canon in sorted(aliases):  # 결정적 순서(이름 오름차순)
        names = [canon] + list(aliases.get(canon, []))
        hit = next((n for n in names if _name_hit(n, q)), None)
        if hit is None:
            continue
        hit_script = _script(hit)
        if hit_script is None:  # 판별 불가(한글·라틴 둘 다 아님) — 비교 기준 없음
            continue
        for n in sorted(set(names) - {hit}):
            if not _name_hit(n, q) and n not in extra and _script(n) not in (None, hit_script):
                extra.append(n)
    return q if not extra else f"{q} ({' / '.join(extra)})"
