"""확장자 묶음 한 곳 — 여러 단계(prepare·secure_docs·parse_qa·represent·figures·vlm_page·parse MCP)가 같은 목록을 쓴다.
엔진 구성(resources/config/pipeline_stack.json)의 `parse` 키와 맞춘다. p1 code_fp에 든다(common.core.artifacts.LAYER_CODE)."""

IMG_EXTS = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"})  # 단독 이미지 문서(쪽 VLM 대상)
OOXML_EXTS = frozenset({".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm"})  # ZIP 컨테이너 Office(암호면 OLE로 싸임)
