"""원천 Object Storage 접근 가능 여부 — 검색 MCP 근거 그림(get_evidence_image)만 씀(사용자 10-14·15 모듈별 분리, common/store/objectstore.py에서 이전, 로직 동일)."""

from common.config import settings as C  # 설정 객체(S7d — OS_* 는 common 칸)


def configured():
    """이 서버가 원천 Object Storage에 접근할 수 있는지 — 접속 정보(OS_ACCESS_KEY·OS_SECRET_KEY)와 boto3 패키지
    둘 다 있어야 한다(OP21). boto3는 requirements-core.txt에 명시돼 있어 rag-core·rag-parse 둘 다 받는다 —
    즉 OS_ACCESS_KEY를 설정하면 rag-core(검색 MCP)도 원천 Object Storage에서 원본을 받아올 수 있다.
    접속 정보가 비어 있을 때(또는 boto3가 없는 더 작은 이미지 변형일 때)만 get_evidence_image가 '사용 불가'로
    명확히 응답하도록 여기서 미리 가려냄(import 자체를 시도하지 않음)."""
    if C.given("OS_ACCESS_KEY") is None or C.given("OS_SECRET_KEY") is None:  # 빈 비밀 = 준 값 아님(옛 truthy 판정과 같음)
        return False
    import importlib.util

    return importlib.util.find_spec("boto3") is not None
