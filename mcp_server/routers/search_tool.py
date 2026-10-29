"""search 도구 등록 — 입력을 받아 서비스(do_search)를 스레드 창구(_bg)로 부르기만.
S5(10-26, refactor_plan 5-1 routers/ — 코디네이터 답 Q5 a)에 mcp_server/main.py build() 안에서 옮김 — 함수 이름·독스트링·서명·
반환 형식은 MCP 도구 계약(🔒 CLAUDE.md 3절 — tools/list 바이트가 같아야 함)이라 글자 그대로 둔다(들여쓰기까지).
"""

from mcp_server.routers.dispatch import _bg
from mcp_server.services.search.search_svc import do_search


def register(m):
    @m.tool()
    async def search(
        question: str | None = None,
        k: int = 8,
        methods: list[str] | None = None,
        decompose: bool | None = None,
        client: str | None = None,
        index_id: str | None = None,
        source_system: str | None = None,
        project_id: str | None = None,
        division: str | None = None,
        service_type: str | None = None,
        limit: int = 100,
        client_like: bool | None = None,
    ) -> dict:
        """자연어 검색 + 하드 필터 통합(2026-10-20) — 세 가지 쓰임:
        · question만: 하이브리드 근거 검색(원문·원본 경로·쪽·줄·bbox·요약·고객·계약 번호·점수·via). methods: vector·bm25·id(기본)·
          graph·image·openviking·concept. BM25는 용어 사전으로 질문을 확장(X3, QUERY_EXPAND=0이면 끔) — 적용되면 notes에 표시.
        · 하드 필터만(question 없이 조건만): 조건에 정확히 맞는 문서 전부와 그 청크 전부를 점수 계산 없이 돌려준다 —
          {total_docs, total_chunks, truncated, docs:[{doc_id, file_name, sf_acc_name, division, service_type, project_code__c,
          chunks:[{chunk_id, page, seq, section, chunk_text, ...}]}]} · 문서 수 상한 limit(기본 100, 0이면 무제한 — 넘으면 잘리고
          truncated=true) · 로컬 묶음(비PG) 저장소면 {"error": ...}.
        · question + 하드 필터: 조건에 정확히 맞는 문서 범위 **안에서만** 검색(응답에 filter·scope_docs) — 풀을 k×3로 넉넉히
          잡아 범위 필터 뒤 근거 k개로 재순위 · 집계 근거는 하드 필터 범위 밖 전체 집계라 이 결합에서는 생략.
        하드 필터 여러 개는 AND, 안 준 조건은 무시: client 고객명 전체
        (예: 'H. Lundbeck AS') · client_like=true면 client를 포함매칭(LIKE)으로 바꾼다('Daiichi' → 'Daiichi Sankyo Co Ltd'도 찾음) · source_system 'SFDC'/'CRMS'/'LAS' · project_id 프로젝트 코드(예: 'E29H') ·
        division 'DS'/'DP'/'CD'/'CM'/'AD'/'AS' · service_type 'CMO DS'/'CMO DP'/'CDO'/'ADC' 등.
        question도 조건도 주지 않으면 {"error": ...}.
        그 외(기존 search 그대로) — decompose: 복합 질문 분해(기본 켬, MCP_DECOMPOSE=0이면 끔, LLM 설정 시만) ·
        client(AD38): 하드 필터로도 쓰이고, SEARCH_CLIENT_HARD=1(기본 꺼짐)이면 저장소 질의 단계에서도 다른 고객을 뺌.
        기본 켬(env, AD42, =0으로 끔): SEARCH_EVIDENCE_GATE → evidence_status(found/weak/none)·low_score 표시만 ·
        SEARCH_AGG_ROUTE → 집계 질문이면 집계 결과를 근거 맨 앞에(via="aggregate") · SEARCH_AGG_LLM(기본 끔) 등 기존 동일.
        근거마다 doc_type·version·supersedes_doc_id·is_deleted·contract_id·updated_at·company: RDB 문서 위치 메타(AD44)에
        그 문서가 있을 때만. index_id(AD41): 설정이 다른 색인 중 하나를 고름 — 없으면 기본 색인, 모르는 id면 {"error", "indexes"}."""
        return await _bg(
            do_search,
            question,
            k,
            methods,
            decompose,
            client,
            index_id,
            source_system,
            project_id,
            division,
            service_type,
            limit,
            client_like,
        )
