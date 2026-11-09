"""확장자 묶음 한 곳 — 여러 단계(filter_and_rotate·parse_scoring·doc_represent·figures·vlmcall·parse MCP)가
같은 목록을 쓴다. 엔진 구성(resources/config/pipeline_stack.json)의 `parse` 키와 맞춘다."""

IMG_EXTS = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"})  # 단독 이미지 문서(쪽 VLM 대상)
OOXML_EXTS = frozenset({".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm"})  # ZIP 컨테이너 Office(암호면 OLE로 싸임)
OFFICE_EXTS = OOXML_EXTS | {".dotx", ".potx", ".ppsx", ".xltx"}  # 새 형식 오피스 전부(서식·쇼 파일 포함 — 개체 꺼내기 pl-63)
MAIL_EXTS = frozenset({".eml", ".msg"})  # 메일 원본(첨부 꺼내기·인용 스레드)
