"""parse_document 도구 등록 — 서비스(do_parse_document)를 자체 예산 창구(_bg_long)로 부르기만.
S5(10-26, refactor_plan 5-1 routers/ — 코디네이터 답 Q5 a)에 mcp_server/main.py build() 안에서 옮김 — 함수 이름·독스트링·서명·
반환 형식은 MCP 도구 계약(🔒 CLAUDE.md 3절 — tools/list 바이트가 같아야 함)이라 글자 그대로 둔다(들여쓰기까지).
"""

from mcp_server.routers.dispatch import _bg_long
from mcp_server.services.parse_proxy import do_parse_document


def register(m):
    @m.tool()
    async def parse_document(
        path: str | None = None,
        content_b64: str | None = None,
        filename: str | None = None,
        time_out_threshold: int = 300,
        max_chars: int = 200000,
    ) -> dict:
        """비정형 파일(pdf·ppt·word 등) 1건을 text 파싱해 **문서별 대표 파싱 결과**를 돌려준다(2026-10-21).
        - 구조 없이 원문 중심: 구조화·임베딩·PostgreSQL·EDW/OS 적재(publish) 없음 · **그림[VLM] 이미지 파싱 없음** · **표 인식 포함**(엔진+대표 결과 표 합치기 기본 켬).
        - 입력 둘 중 하나: `path`= 수집 서버에서 보이는 컨테이너 경로(허용 루트 `/app/output/_mcp_parse/inbox` 하위만 —
          호스트 `<루트>/output/_mcp_parse/inbox/`에 파일을 놓고 그 안쪽 경로를 준다) ·
          `content_b64`+`filename` = 원격 개발 서버에서 파일 내용을 직접 전달(기본 100MB 상한).
        - `time_out_threshold`(기본 300초) 안에 끝나면 결과 즉시 반환 · 못 끝내면 `{"error": "시간 안에 수행 못했습니다", "job_id": …}`
          (작업은 계속 진행돼 결과 파일은 수집 서버에 만들어진다 — 재호출하면 새 작업이 등록되니 시간을 넉넉히).
        - 응답(완료): `text`(대표 본문·표 포함, `max_chars` 초과 시 잘리고 `text_truncated`) · `tables_std`·`tables`·`facts`·`fields` ·
          `engine`(대표 엔진) · `rep_path`(전체 대표 결과 JSON 컨테이너 경로) · `ms`.
        - 지원 확장자: pdf·docx·doc·pptx·ppt·xls·xlsx·xlsm·hwpx·txt·html·htm·mht·mhtml·eml·msg."""
        return await _bg_long(
            do_parse_document, float(time_out_threshold or 300), path, content_b64, filename, time_out_threshold, max_chars
        )
