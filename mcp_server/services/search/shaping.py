"""근거 모양 만들기 — 근거 칸·근거 상태(evidence_status)·결과 크기 상한(cap). 검색 중 ParsingMeta 조회(rep_uri)는 11-01에 지움(mc-15 — 적재 때 gold doc에 복사).
S5(10-26, refactor_plan 5-1·D-007 — 코디네이터 답 Q5 a)에 mcp_server/main.py(옛 data_retrieval/mcp_server.py)에서 옮김 — 내용 그대로
(설정 상수만 mcp_server/config.py의 CFG로).
"""

import json
import re
from pathlib import Path

from mcp_server.config import CFG


def _evidence(h, man=None):
    """검색 결과 한 건 → 근거 dict(안쪽 칸 chunk_id·score·via·rank 포함 — 응답에는 schemas.evidence.EVIDENCE_KEYS 13칸만 나감).
    man(AD44 rdb 수집 manifest, _manifest_by_name()): version은 그 문서(file_name)의 manifest 값만(없으면 null).
    mc-05(사용자 10-31·11-01): 본문 글자로 판·구판을 추정한 값은 내보내지 않는다 — 운영 계약에 칸은 남아 있어 version·superseded 칸은
    두되 superseded는 늘 null(원천에 구판 표시가 생기면 그 값으로). 추정값은 안쪽 최신성 순위(L3-1)에만 남음.
    11-01(mc-16) — manifest의 다른 칸·rep_uri는 계약 밖이라 붙이지 않는다."""
    out = {
        "chunk_id": h.get("chunk_ref"),
        "chunk_key": h.get("chunk_key"),
        "doc_id": h.get("doc_id"),
        "file_path": h.get("file_path"),
        "file_name": h.get("file_name") or Path(h.get("file_path") or "").name,
        "page": h.get("page"),
        "line": h.get("line"),
        "section": h.get("section"),
        "text": h.get("text"),
        "client": h.get("client"),
        "contract_no": h.get("contract_no"),
        "score": h.get("score"),
        "via": h.get("via"),
        "rank": h.get("rank"),
        "doc_date": h.get("doc_date"),
        "version": None,
        "superseded": None,
    }
    out["version"] = ((man or {}).get(out["file_name"]) or {}).get("version") or None
    return out


def _key_terms(question):
    """R3(AD42) — 질문의 핵심어(ID 모양·숫자·용어 사전 걸린 말, approved만) — evidence_status의 weak 판정용."""
    from common.core.terms import ID_LIKE, load_glossary, split_terms
    from mcp_server.services.search.terms import match_concepts

    ids = ID_LIKE.findall(question)
    nums = re.findall(r"\d+(?:[.,]\d+)?", question)
    gl = load_glossary()
    gloss = []
    for cid in match_concepts(question, gl):
        r = gl[cid]
        gloss += [x for x in [r.get("canonical")] + split_terms(r.get("synonyms")) + split_terms(r.get("abbreviations")) if x]
    return sorted({t for t in (ids + nums + gloss) if t})


def evidence_status(question, evidence):
    """R3(AD42) — 근거가 있나? 0건 → none · 질문 핵심어(ID·숫자·용어 사전)가 근거 원문에 하나도 없으면 weak · 그 외 found.
    근거 목록은 바꾸지 않음(표시만)."""
    if not evidence:
        return "none"
    kws = _key_terms(question)
    text = " ".join(e.get("text") or "" for e in evidence).lower()
    return "found" if (not kws) or any(str(k).lower() in text for k in kws) else "weak"


_CAP_FLOOR = 300  # AR5 — 랭크 인지 절삭의 글자 수 바닥(이 아래로는 더 줄이지 않고 다음 단계: 통째로 뺌)


def _cap_window(text, target_len, question):
    """AR5 — 질문 토큰(common.core.text.tokens, 재사용만·수정 안 함) 주변 창을 남기고 자름 — 못 찾으면 머리말(기존 동작).
    반환 길이는 반드시 target_len 이하(마커 길이도 포함) — 그래야 cap()의 바닥(_CAP_FLOOR) 비교가 매 단계 실제로
    줄고, target_len이 바닥에 고정돼도 다음 번엔 더 못 줄인다고 판단해 drop으로 넘어간다(전엔 마커를 target_len
    위에 덧붙여 바닥 근처에서 길이가 안 줄고 무한 루프)."""
    marker = " …(잘림)"
    if target_len >= len(text):
        return text
    slice_len = max(0, target_len - len(marker))
    if question:
        from common.core.text import tokens

        pos = None
        for t in {str(t).lower() for t in tokens(question)}:
            i = text.lower().find(t) if t else -1
            if i != -1 and (pos is None or i < pos):
                pos = i
        if pos is not None:
            start = max(0, min(pos - slice_len // 2, len(text) - slice_len))
            return text[start : start + slice_len] + marker
    return text[:slice_len] + marker


def _text_str(e):
    """AR5 — e['text']가 str이 아니어도(int·list·None 등) 안 죽게 길이·자름 계산용 문자열로(원본은 shrink할 때만 바꿔치움)."""
    t = e.get("text")
    if t is None:
        return ""
    return t if isinstance(t, str) else str(t)


def _evidence_groups(obj):
    """cap()이 랭크 인지 절삭을 적용할 근거 목록 — 최상위 evidence 하나(비었으면 없음). S5(10-26, D-025·C-25 ②) — research()의
    요건별 requirements[i]["evidence"] 그룹(AR7)은 research.py 삭제와 함께 뺐다(MCP 도구 응답에 그 칸이 없어 search 응답은 같음)."""
    groups = []
    ev = obj.get("evidence")
    if isinstance(ev, list) and ev:
        groups.append(ev)
    return groups


def _shrink_group(g, question, trimmed_ids):
    """그룹 하나에서 가장 낮은 순위(비보호) 항목 하나를 반으로 줄이거나(가능하면) 통째로 뺌 — AR5의 단일 목록
    루프를 그룹 하나에 적용하는 부분만 뽑음(동작 동일, 전과 바이트 동일 유지)."""
    protected = {i for i, e in enumerate(g) if i == 0 or (isinstance(e, dict) and e.get("via") == "aggregate")}
    candidates = [i for i in range(len(g)) if i not in protected] or list(range(len(g)))  # 보호 대상만 남으면 그것도 줄임
    shrink_i = next((i for i in sorted(candidates, reverse=True) if len(_text_str(g[i])) > _CAP_FLOOR), None)
    if shrink_i is not None:
        t_str = _text_str(g[shrink_i])
        g[shrink_i]["text"] = _cap_window(t_str, max(_CAP_FLOOR, len(t_str) // 2), question)
        trimmed_ids.add(id(g[shrink_i]))
        return True
    g.pop(max(candidates))  # 바닥 아래로는 못 줄이는 가장 낮은 순위 항목을 통째로 뺌
    return False


def cap(obj, limit=None):
    """결과 크기 상한 — JSON 전체가 limit바이트(UTF-8 인코딩 기준) 이하가 되게(잘렸으면 truncated 표시).
    GH1-13: 글자 수 대신 UTF-8 바이트로 셈(멀티바이트 텍스트가 글자 수 상한을 통과해도 실제 전송 바이트는 넘기던 문제) —
    MCP_MAX_CHARS 이름·기본값(20000)은 그대로 두고 단위만 바이트로 바꿈(SDK 봉투까지 포함한 실측·재조정은 서버에서).
    AR5(k-sweep) — 예전엔 목록에서 가장 긴 text부터 반씩 잘랐기 때문에
    1위 근거·집계 근거(via=aggregate, 늘 index 0)가 먼저 깎였다(synth-r2 k=10 80% 잘림). 이제는 순위(index, 0이 1위) 기준
    **가장 낮은 순위부터** 줄인다 — index 0과 via=aggregate 항목은 그것들만 남을 때까지 보호. 한 항목씩: (1) 글자수가
    _CAP_FLOOR(300) 넘는 가장 낮은 순위 항목을 반으로(질문 토큰 주변 창 유지, 비싸지 않으면, text가 str 아니면 str()로) ·
    (2) 더 줄일 게 없으면 가장 낮은 순위 항목을 통째로 뺌. 잘렸으면 truncated=True + truncation:{trimmed, dropped}(몇
    건 줄였는지/뺐는지).
    독립 검토 BLOCK 수정(10-12) — truncation 칸을 루프가 끝난 뒤에 덧붙이면 그 칸 자체의 바이트가 limit 비교에
    안 들어가 최종 결과가 limit을 넘길 수 있었다(예: {"question":"q","evidence":[{"text":12345},{"text":"y"*500}]},
    limit=100 → 예전엔 111바이트). 이제 루프 시작 전에 trimmed=0,dropped=0으로 넣어 매 비교에 포함하고, 끝났는데도
    둘 다 0이면(=한 번도 안 줄었으면) 지운다(바이트 동일 유지).
    그룹(_evidence_groups)마다 같은 1위·aggregate 보호 규칙, 그룹 사이에서는 항목이 가장 많이 남은 그룹의 꼬리부터(동률이면
    라운드로빈) — AR7(research()의 요건별 근거 그룹·answer 마지막 수단)에서 온 틀이고, S5(10-26, D-025)부터 그룹은 최상위
    evidence 하나뿐이라 AR5와 같은 단일 목록 동작이다(search 응답 바이트 그대로)."""
    limit = limit or CFG.MAX_CHARS
    question = obj.get("question")
    obj["truncation"] = {"trimmed": 0, "dropped": 0}  # BLOCK 수정 — limit 비교에 이 칸 바이트도 매번 들어가게 먼저 넣음
    trimmed_ids = set()
    groups = _evidence_groups(obj)  # [최상위 evidence] 또는 [] (S5 — AR7 요건 그룹 뺌)
    rr = 0  # 그룹 크기가 같을 때 순서를 고정(한 그룹만 계속 비지 않게)
    while len(json.dumps(obj, ensure_ascii=False).encode("utf-8")) > limit and any(groups):
        sizes = [len(g) for g in groups]
        mx = max(sizes)
        tied = [i for i, s in enumerate(sizes) if s == mx]
        g = groups[tied[rr % len(tied)]]
        rr += 1
        if not _shrink_group(g, question, trimmed_ids):
            obj["truncation"]["dropped"] += 1
        obj["truncation"]["trimmed"] = len(trimmed_ids)
        obj["truncated"] = True
    if obj["truncation"]["trimmed"] == 0 and obj["truncation"]["dropped"] == 0:
        del obj["truncation"]  # 한 번도 안 줄었으면 칸 자체를 없앰(바이트 동일 유지)
    return obj
