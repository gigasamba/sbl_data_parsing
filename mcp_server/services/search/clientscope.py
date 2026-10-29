"""고객 범위(client scope) 단일 규칙(BR50) — "이 질문·호출이 어느 고객으로 제한되는가"와 "이 문서가 그 범위
안인가"를 한 곳에서. local.py(벡터·BM25·ID 후보 거르기)·pgsearch.py(_client_restrict, 문서 단위로 한 번
읽어 파이썬에서 판정 — 10-14부터 SQL 조건이 아니라 allows() 그대로, PG array/unnest 없이 AD41 sqlite
stand-in에도 동작)·retriever.py(저장소 질의 단계 제한·소프트 승격·그래프·개념 검색)·mcp_server.py(그래프
후처리·집계·그림·OpenViking·문서/그림/표 단건 조회)가 모두 이 모듈만 거친다 — 전에는 같은 규칙이 5곳에
따로 적혀 있었고(local.py `d.get("client") in client or (not client_strict and not d.get("client"))` ·
pgsearch.py SQL · retriever.py search_ex의 cl 계산 · mcp_server.py _graph_hits_for_client의 cl 계산 ·
그 밖엔 검사 자체가 없던 곳들), 그래프 확장이 한 번 비켜 간 적 있다(GH1-12).

10-14 다중 고객 라벨 — 문서 하나에 고객 여러 명(docs.jsonl `clients` 목록, 증거 강도순) 가능 · 검색·필터는
그중 ANY 하나라도 맞으면 매치(allows() 참고) · 옛 묶음(`clients` 없음)은 단일 `client`로 자동 낙하.

읽는 환경변수(단일 지점):
  SEARCH_CLIENT_FILTER(기본 켬) — question에서 고객명을 자동으로 잡을지(common.core.terms.match_clients).
  SEARCH_CLIENT_HARD(기본 꺼짐) — 켜지면 저장소 질의 단계에서 진짜 제한(hard) · 꺼지면 후보를 넓혀 앞으로만(soft, 제외 없음).
  SEARCH_CLIENT_STRICT(기본 꺼짐) — hard일 때 고객 미상 문서까지 뺄지(켜지면 미상도 제외)."""

import json

from common.core.terms import match_clients  # 고객 명부 자동 인식(모듈 계약, local.py·retriever.py와 같은 규칙)
from mcp_server import config as mc  # 설정 객체(S7d)


def doc_clients(client, clients):
    """독립 검토 CONCERN(10-14) — "clients(다중)가 있으면 그걸, 없으면 client(단일)로 낙하"를 한 곳에서.
    local.py·retriever.py(client_map·client_path_map·hit dict 둘 다)·aggregate.py(local)가 전부 이
    함수를 거친다(전에는 각자 `d.get("clients") or d.get("client")`를 따로 적어 그래프 후처리·그림·OV·집계
    범위가 `client`만 보고 다중 라벨을 놓치는 곳이 남았다). clients가 PG에서 읽은 그대로(JSON 인코딩 TEXT —
    pgstore.load()가 json.dumps로 적재, array·jsonb 아님 — AD41 sqlite stand-in은 array/unnest 미지원)면
    디코드한다 · 이미 파이썬 list(로컬 묶음 docs.jsonl)면 그대로 · 둘 다 없거나 비면 client(단일) 하나로.
    반환값은 allows()에 바로 넘길 수 있는 모양(list|str|None)."""
    if isinstance(clients, (list, tuple)):
        return clients or client
    if isinstance(clients, str) and clients:
        try:
            return json.loads(clients) or client
        except (TypeError, ValueError):
            return client
    return client


def client_scope(question, client, clients=(), client_only=False, strict_override=None):
    """question(검색 질의 글자, None 허용 — 자동 인식을 건너뜀) + client(명시 인자, str|list|None) + clients(전체
    명부, match_clients용) → (allowed: set|None, strict: bool, hard: bool).

    allowed=None이면 제한 없음(호출자는 그대로 무제한 검색 — 전과 바이트 동일, client도 clients도 안 준 기본 호출은
    항상 이 값). hard=False면 "범위가 있어도 저장소 단계에서 안 거름"(소프트 승격에만 씀, allows()는 strict=False로
    불러야 함) · hard=True면 저장소 질의 단계에서 진짜 제한.

    client_only=True(BR23 엔티티별 하위 검색)면 question의 자동 인식을 끄고 client 인자만 쓰며 항상 strict+hard
    (다른 고객 자동매칭이 새어 들어오지 않게).

    strict_override(BR43 FX 근거처럼 "같은 범위는 쓰되 고객 미상 문서는 늘 포함"이 필요할 때만) — None이면
    SEARCH_CLIENT_STRICT 환경값 그대로(기존 동작과 바이트 동일), True/False를 주면 그 값으로 강제(client_only일
    때는 그 의미가 더 강해 override를 안 받음 — 항상 strict)."""
    sc = mc.cfg().search.client  # S7d — 설정 객체(호출마다 한 번 묶어 읽음)
    cl = set() if (client_only or not question) else (set(match_clients(question, clients)) if sc.filter else set())
    if client:
        cl |= {client} if isinstance(client, str) else set(client)
    if not cl:
        return None, False, False
    if client_only or sc.hard:
        if client_only:
            strict = True
        else:
            strict = sc.strict if strict_override is None else bool(strict_override)
        return cl, strict, True
    return cl, False, False


def allows(doc_client, allowed, strict):
    """단일 규칙: allowed가 None이면 제한 없음(항상 허용) · doc_client의 라벨 중 하나라도 allowed 안에 있으면
    허용(ANY-match, 10-14 다중 고객 라벨) · 고객 미상(라벨이 전혀 없음)이고 strict가 아니면 허용 · 그 밖엔 거부.
    doc_client = 단일 이름(str, 옛 적재분·client 필드) 또는 다중 라벨 목록(list|tuple|set, docs.jsonl의 clients) ·
    None·빈 문자열도 "미상"으로 다룬다. 호출부는 d.get("clients") or d.get("client")로 다중이 있으면 그걸,
    없으면(옛 묶음) 단일 client로 자동 낙하(fall back) — 이 함수 쪽은 모양만 보고 그대로 처리.
    local.py의 벡터·BM25·ID 후보 거르기, pgsearch.py의 저장소 질의 단계 제한(_client_restrict, 문서 단위로
    한 번만 판정 — PG array/unnest 없이 순수 파이썬, AD41 sqlite stand-in에도 그대로 동작), retriever.py의
    소프트 승격·그래프·개념 검색, mcp_server.py의 그래프 후처리·그림·OpenViking·단건 조회(do_get_document 등)가
    전부 이 한 함수로 판정한다."""
    if allowed is None:
        return True
    names = doc_client if isinstance(doc_client, (list, tuple, set)) else ([doc_client] if doc_client else [])
    names = [n for n in names if n]
    if any(n in allowed for n in names):
        return True
    return not strict and not names
