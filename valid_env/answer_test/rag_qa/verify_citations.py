"""결정적 인용 검증 — 답의 모든 수치가 citations 중 하나의 quote(정규화 비교)로 뒷받침되는지, 그리고(evidence가
주어지면, be-qa 10-11 R2-d) 그 quote가 실제로 검색이 돌려준 근거 text 안에 있는지. 숫자 커버 규칙은
옛 rfi_answer/office_text.py(_norm·_num_tokens·_spelled_to_digits)와 같은 원리를 자족형으로 복제한 것(옛 agent_platform
빌드가 agent 폴더 단위로 격리해 묶던 때의 흔적 — S10부터는 validation/e2e/answer_gen.py가 import해 씀).

evidence 교차검증(R2-d) — 전엔 숫자가 quote 문자열 안에 있나만 봤다(자기참조: quote를 LLM이 지어내도 통과).
evidence(list[dict], S10부터 validation/e2e/answer_gen.py의 search 도구 함수가 이번 질문에 실제로 돌아온 근거를 모아 준다)가 주어지면
각 citation의 quote가 evidence 중 하나의 text에 포함되는지도 본다 — kind="aggregate"면 via가
aggregate/aggregate_llm인(또는 kind="aggregate") evidence의 text에서, 그 외(평소 인용)는 doc_key·chunk_key가
같은 evidence의 text에서 찾는다. evidence=None(기본값)이면 이 교차검증은 건너뛴다(evidence를 못 모으는 호출자와
그대로 호환)."""

import json
import re
import unicodedata

_NUM_RE = r"\d+(?:,\d{3}(?!\d))*(?:\.\d+)*"   # 천 단위 쉼표만 숫자 일부
_NUM_WORDS = {w: i for i, w in enumerate(("zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
                                          "nine", "ten", "eleven", "twelve"))}
_SPELLED_RE = re.compile(r"(?<![0-9a-z])(" + "|".join(w for w in _NUM_WORDS if w != "one") + r")(?![0-9a-z])", re.I)
_ELLIPSIS_RE = re.compile(r"…|\.{3,}")   # "…" 또는 "..." — 생략 표시, 조각마다 포함 확인
_AGGREGATE_VIA = {"aggregate", "aggregate_llm"}
_SHORT_PIECE_LEN = 6   # be-qa 10-11 ② — 이보다 짧은 조각은 토큰 경계까지 봐야 "1"이 "15" 속에서 안 걸림


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text))   # 전각/반각(영문·숫자·공백) 통일 — R2-d
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text).replace(",", " ")
    return re.sub(r"\s+", " ", text).casefold().strip()


def _spelled_to_digits(text: str) -> str:
    return _SPELLED_RE.sub(lambda m: str(_NUM_WORDS[m[1].lower()]), text)


def _num_tokens(text: str) -> set:
    """수치 토큰(쉼표 제거, 정수는 선행 0 제거 — '06'='6')."""
    out = set()
    for n in re.findall(_NUM_RE, text):
        n = n.replace(",", "")
        out.add(n if "." in n else (n.lstrip("0") or "0"))
    return out


def _quote_pieces(quote: str) -> list:
    """"…"/"..." 로 끊긴 quote는 조각마다(생략된 가운데는 안 보고) 포함 확인 — 조각이 없으면 quote 전체 한 조각."""
    pieces = [p for p in _ELLIPSIS_RE.split(quote) if p.strip()]
    return pieces or [quote]


def _boundary_ok(text: str, start: int, end: int) -> bool:
    """start:end 자리의 일치가 토큰 경계인지 — 앞뒤(있으면)에 글자·숫자가 안 붙어야 한다(②, "15" 속 "1" 거부)."""
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    return not before.isalnum() and not after.isalnum()


def _find_piece(text: str, piece: str, start_pos: int) -> int:
    """text[start_pos:]에서 piece를 찾아 끝 인덱스를 돌려준다(짧은 조각은 토큰 경계까지 맞는 자리만, ②) —
    없으면 -1. "…"로 끊긴 다음 조각은 이 끝 인덱스부터 찾아 순서를 강제한다(③)."""
    need_boundary = len(piece) < _SHORT_PIECE_LEN
    pos = text.find(piece, start_pos)
    while pos != -1:
        if not need_boundary or _boundary_ok(text, pos, pos + len(piece)):
            return pos + len(piece)
        pos = text.find(piece, pos + 1)
    return -1


def _quote_in_text(quote: str, text) -> bool:
    """quote 전체(또는 "…"로 끊긴 조각마다, 앞 조각이 끝난 자리보다 뒤에서만 — ③)가 text 안에 있는지. 정규화 후
    6자 미만인 조각은 토큰 경계까지 맞아야 한다(②)."""
    if not text:
        return False
    norm_text = _norm(text)
    pos = 0
    for piece in _quote_pieces(quote):
        p = _norm(piece)
        if not p:
            continue
        pos = _find_piece(norm_text, p, pos)
        if pos == -1:
            return False
    return True


def _is_aggregate_evidence(e: dict) -> bool:
    return e.get("kind") == "aggregate" or e.get("via") in _AGGREGATE_VIA


def _citation_supported(c: dict, evidence: list) -> bool:
    """c["quote"]가 evidence(이번 턴에 실제로 돌아온 근거) 중 하나의 text 안에 있는지 — kind="aggregate"면 그
    evidence도 집계 근거(kind="aggregate" 또는 via가 aggregate/aggregate_llm)여야, 평소 인용은 doc_key·chunk_key가
    그 evidence와 같아야 한다(위조한 quote·엉뚱한 evidence에 끼워맞춘 doc_key·chunk_key를 걸러낸다)."""
    quote = str(c.get("quote", ""))
    if not quote.strip():
        return False
    is_agg = c.get("kind") == "aggregate"
    for e in evidence:
        if not isinstance(e, dict) or not _quote_in_text(quote, e.get("text")):
            continue
        if is_agg:
            if _is_aggregate_evidence(e):
                return True
        elif c.get("doc_key") == e.get("doc_key") and c.get("chunk_key") == e.get("chunk_key"):
            return True
    return False


def verify_citations(answer_json: str, evidence: list = None) -> dict:
    """호출: 출력 후보 전체 {answer, status, citations:[{doc_key, chunk_key, page, quote}]}의 JSON 문자열.
    answer 속 모든 수치가 citations 중 하나의 quote에(정규화 비교, 영문 철자 수 포함) 있어야 한다 — 없으면
    problems에 그 수치를 적어 반환. status가 found/partial인데 citations가 비어 있어도 problems에 적는다.

    evidence(R2-d, 선택) — 이번 턴에 실제로 호출된 rag_search 도구들의 결과에서 모은 근거 항목 list[dict]
    (적어도 "text", 평소 근거는 "doc_key"·"chunk_key"도). 주어지면 각 citation의 quote가 그 안에 실제로 있는지도
    검사한다(없으면 problems에 적음 — LLM이 quote·숫자를 지어내도 통과하던 결함). None이면(기본값) 건너뛴다.

    problems가 비어 있으면(ok=true) 그대로 출력해도 된다."""
    try:
        data = json.loads(answer_json)
        assert isinstance(data, dict)
    except (ValueError, AssertionError):
        return {"ok": False, "problems": ["answer_json must be a JSON object"]}
    answer = str(data.get("answer", ""))
    citations = data.get("citations")
    if not isinstance(citations, list):
        return {"ok": False, "problems": ["citations must be a list"]}
    problems = []
    if data.get("status") != "not_found" and not citations:
        problems.append("found/partial 답에는 citations가 최소 1건 필요")
    quotes = " ".join(_norm(str(c.get("quote", ""))) for c in citations if isinstance(c, dict))
    covered = _num_tokens(_spelled_to_digits(quotes))
    claimed = _num_tokens(_spelled_to_digits(_norm(answer)))
    uncovered = sorted(claimed - covered)
    if uncovered:
        problems.append("인용으로 뒷받침되지 않은 수치: " + ", ".join(uncovered))
    if evidence is not None:
        fake = [str(c.get("quote", "")) for c in citations
                if isinstance(c, dict) and not _citation_supported(c, evidence)]
        if fake:
            problems.append("검색 근거에서 확인되지 않은 인용: " + " / ".join(q[:60] for q in fake))
    return {"ok": not problems, "problems": problems, "citations_checked": len(citations)}
