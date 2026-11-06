"""common.check.checker ping 자기 점검."""

from common.check.checker import candidates, model_not_found, payload, ping, png_1x1


def selftest():
    png = png_1x1()
    assert png.startswith(b"\x89PNG") and b"IEND" in png
    assert payload("EMBED", "e")[0] == "/embeddings"
    assert payload("VLM", "v")[1]["messages"][0]["content"][1]["type"] == "image_url"
    assert payload("LLM", "l")[1]["max_tokens"] == 1
    # ping()은 설정 객체만 읽어 가짜 접두 ZZ_는 칸이 없다 → 같은 경로(어댑터 밖 — EMBED와 같은 /…로 보내는 쪽)를 타는
    # 진짜 접두 EMBED(같은 경로)로 같은 것을 시험: 미설정이면 None · 외부 주소는 보내기 전에 거부. os.environ은 안 바꿈(COMMON.env)
    from common.config.settings import COMMON

    with COMMON.env(EMBED_BASE_URL=None, EMBED_MODEL=None, EMBED_ALLOW_EXTERNAL=None):
        assert ping("EMBED") is None
    with COMMON.env(
        EMBED_BASE_URL="https://api.example.com/v1", EMBED_MODEL="x", EMBED_ALLOW_EXTERNAL=None
    ):  # 외부 주소는 보내기 전에 거부
        ok, _, _, why = ping("EMBED")
        assert not ok and "RuntimeError" in why, why

    # LLM도 ping()이 A.complete(preguarded 기본값 False)를 거쳐 외부 주소면 전송 전에 거부
    # (가드를 건너뛰면 외부에 키·요청이 나감).
    with COMMON.env(LLM_BASE_URL="https://api.example.com/v1", LLM_MODEL="x", LLM_ALLOW_EXTERNAL=None):
        ok2, ms2, _, why2 = ping("LLM")
        assert not ok2 and ms2 == 0 and "외부 주소" in why2, (ok2, ms2, why2)

    # 모델 없음 판정·이름 힌트 후보 추리기(외부 주소라 guard가 거부 → 후보는 빈 목록, 가드 경유만 확인)
    assert model_not_found("RuntimeError: 404 model not found") and model_not_found("Error: model_not_found")
    assert not model_not_found("ConnectionError: timeout")
    assert (
        candidates("ZZ", "https://api.example.com/v1") == []
    )  # 외부 주소 — require_internal이 던짐 → 빈 목록(base는 인자로 받음 — env 불필요)
    print("ping_models selftest OK")


def test_main():
    selftest()
