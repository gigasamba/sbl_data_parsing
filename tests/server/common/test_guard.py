"""common.ai.guard 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.ai.guard --selftest`."""

import os
import socket

from common.ai.guard import (
    BudgetExceeded,
    external_allowed,
    fake_llm,
    is_internal,
    precheck,
    require_internal,
    spend_reserve,
    spend_settle,
    spend_total,
)


def selftest():
    # S7b — 시험이 읽는 값은 설정 객체(COMMON.env — os.environ은 안 바뀜). 바깥 env의 값이 시험에 새지 않게 비워 두고 시작
    from common.config.settings import COMMON

    with COMMON.env(
        LLM_SPEND_FILE=None,
        LLM_BUDGET_USD=None,
        INTERNAL_HOST_SUFFIXES=None,
        INTERNAL_IP_RANGES=None,
        EMBED_ALLOW_EXTERNAL=None,
        RUN_ENV="local",
    ):
        _selftest_body(COMMON)


def _selftest_body(COMMON):
    assert is_internal("http://10.0.0.5:8000/v1") and is_internal("http://127.0.0.1:1/v1") and is_internal("http://localhost:8765/v1")
    assert not is_internal("https://openrouter.ai/api/v1") and not is_internal("http://internal.evil.com/v1")
    assert not is_internal("http://8.8.8.8/v1")
    socket_getaddrinfo = socket.getaddrinfo
    try:  # 점 없는 별칭이 공인 주소로 풀리면 외부
        socket.getaddrinfo = lambda h, *a, **k: [(0, 0, 0, "", ("8.8.4.4", 0))]
        assert not is_internal("http://proxy/v1") and not is_internal("http://glm.internal/v1")
        socket.getaddrinfo = lambda h, *a, **k: [(0, 0, 0, "", ("10.1.2.3", 0))]
        assert is_internal("http://glm-serve:8000/v1")

        def _fail(*a, **k):
            raise OSError("no name")

        socket.getaddrinfo = _fail  # 풀리지 않는 이름 → 외부로 봄
        assert not is_internal("http://nowhere-serve:8000/v1")

        assert not is_internal("http://llm.mycompany.co.kr/v1")  # INTERNAL_HOST_SUFFIXES 비어있음 → 미등록 FQDN은 그대로 거부(불변)
        with COMMON.env(INTERNAL_HOST_SUFFIXES=".mycompany.co.kr,.corp.example"):
            socket.getaddrinfo = lambda h, *a, **k: [(0, 0, 0, "", ("10.1.2.3", 0))]
            assert is_internal("http://llm.mycompany.co.kr/v1")  # 접미사 일치 + 전부 사설 → 내부
            socket.getaddrinfo = lambda h, *a, **k: [(0, 0, 0, "", ("8.8.8.8", 0))]
            assert not is_internal("http://llm.mycompany.co.kr/v1")  # 접미사 일치 + 공인 → 내부 아님
            socket.getaddrinfo = lambda h, *a, **k: [(0, 0, 0, "", ("10.1.2.3", 0)), (0, 0, 0, "", ("8.8.8.8", 0))]
            assert not is_internal("http://llm.mycompany.co.kr/v1")  # 사설+공인 혼재 → 내부 아님
            socket.getaddrinfo = lambda h, *a, **k: [(0, 0, 0, "", ("10.1.2.3", 0))]
            assert not is_internal("http://evil.com/v1")  # 접미사 미일치 → 영향 없음
        assert not is_internal("http://147.46.10.10:8000/v1")  # SI21: 사설 밖 사내 대역 — 설정 없으면 외부(불변)
        with COMMON.env(INTERNAL_IP_RANGES="147.46.10.0/24, not-a-cidr, 0.0.0.0/0, 2600::/8"):
            assert is_internal("http://147.46.10.10:8000/v1")  # 대역 안 주소 직접 → 내부
            assert not is_internal("http://147.46.11.10:8000/v1")  # 대역 밖 → 외부
            assert not is_internal("http://8.8.8.8/v1")  # 0.0.0.0/0(너무 넓음)·잘못된 CIDR·IPv6 /8은 무시 → 여전히 외부
            assert not is_internal("http://[2600:1f18::1]/v1")
            socket.getaddrinfo = lambda h, *a, **k: [(0, 0, 0, "", ("147.46.10.7", 0))]
            assert is_internal("http://glm-serve:8000/v1")  # 점 없는 별칭이 대역 안으로 풀림 → 내부
            assert not is_internal("http://llm.example.com/v1")  # 미등록 FQDN은 대역 안으로 풀려도 그대로 거부(규칙 불변)
            socket.getaddrinfo = lambda h, *a, **k: [(0, 0, 0, "", ("147.46.10.7", 0)), (0, 0, 0, "", ("8.8.8.8", 0))]
            assert not is_internal("http://glm-serve:8000/v1")  # 대역 안+공인 혼재 → 외부
        with COMMON.env(INTERNAL_HOST_SUFFIXES="mycompany.co.kr"):  # 점 없이 적어도 자동으로 ".mycompany.co.kr"로 정규화
            socket.getaddrinfo = lambda h, *a, **k: [(0, 0, 0, "", ("10.1.2.3", 0))]
            assert not is_internal("http://evilmycompany.co.kr/v1")  # 접두어 뒤 점 없이 붙은 가짜 접미사는 안 걸림
            assert is_internal("http://llm.mycompany.co.kr/v1")
    finally:
        socket.getaddrinfo = socket_getaddrinfo
    # 외부 허용(스위치 + RUN_ENV=local) — 옛 시험은 가짜 접두 X(X_ALLOW_EXTERNAL=1)였으나 설정 객체에는 가짜 접두 칸이 없어 진짜 접두 EMBED로 같은 것을 시험
    import tempfile

    EXTU = "https://openrouter.ai/api/v1"
    with COMMON.env(EMBED_ALLOW_EXTERNAL=None):  # 허용 없음 → 거부
        try:
            require_internal(EXTU, "EMBED")
            raise AssertionError("허용 없이 외부 허용됨")
        except RuntimeError:
            pass
    with COMMON.env(RUN_ENV="local", EMBED_ALLOW_EXTERNAL="1"):
        require_internal(EXTU, "EMBED")  # 허용 + RUN_ENV=local → 허용(합성 문서 선언 잠금은 사용자 10-29에 삭제)
        assert external_allowed("EMBED") and not external_allowed("X")  # 칸 없는 접두는 허용 안 됨
    for env in (
        None,
        "dev",
        "stage",
        "prd",
        "prod",
        "PRD",
        "Local",
        " local",
    ):  # D-028 ⑧ — 서버 환경은 허용이 열려도 거부(내부 주소는 영향 없음) · 없음·모르는 글자도 서버로(VS7b U-1 b)
        with COMMON.env(RUN_ENV=env, EMBED_ALLOW_EXTERNAL="1"):
            try:
                require_internal(EXTU, "EMBED")
                raise AssertionError(f"RUN_ENV={env}인데 외부 허용됨")
            except RuntimeError as e:
                assert ("RUN_ENV 없음" if env is None else f"RUN_ENV={env}") in str(e), str(e)
            assert not external_allowed("EMBED")
            require_internal("http://10.0.0.5:8000/v1", "EMBED")
    # op-02(사용자 10-29) — 가짜 LLM 응답은 local 전용: 서버·모르는 값에서 켜져 있으면 거부, RUN_ENV 없음(selftest)·local은 허용, 꺼져 있으면 늘 False
    for env, want in (("local", True), (None, True), ("dev", "거부"), ("prd", "거부"), ("prod", "거부")):
        with COMMON.env(RUN_ENV=env, LLM_FAKE="1"):
            try:
                got = fake_llm()
            except RuntimeError as e:
                got = "거부" if "local 전용" in str(e) else str(e)
        assert got == want, (env, got)
    with COMMON.env(RUN_ENV="dev", LLM_FAKE=None):
        assert fake_llm() is False
    print(
        "[selftest] 내부망 가드 — 외부 허용 잠금·점 없는 이름 주소 확인·리다이렉트 가드·RUN_ENV(없음·dev·prd·모르는 글자 거부, local만 허용) 통과"
    )
    # 비용 관문(10-05 독립 검토) — 공유 장부 선차감이 동시 호출에도 상한을 넘지 않음(옛 NO_PAID_CALLS 차단은 11-03에 지움)
    import threading

    with COMMON.env(LLM_SPEND_FILE=os.path.join(tempfile.mkdtemp(), "spend.txt"), LLM_BUDGET_USD="1.0"):
        passed = []

        def _w():
            try:
                spend_reserve(0.1, "T")
                passed.append(1)
            except BudgetExceeded:
                pass

        ts = [threading.Thread(target=_w) for _ in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert len(passed) == 10 and abs(spend_total() - 1.0) < 1e-6, (len(passed), spend_total())
        spend_settle(-0.3)
        assert abs(spend_total() - 0.7) < 1e-6
        # precheck — 외부 EMBED·VLM만 고정 예상액 선차감(LLM은 llm.chat이, 내부망은 0)
        assert precheck("https://api.example.com/v1", "EMBED") > 0 and abs(spend_total() - 0.701) < 1e-6, spend_total()
        assert precheck("https://api.example.com/v1", "LLM") == 0.0 and precheck("http://127.0.0.1:9/v1", "VLM") == 0.0
    with COMMON.env(LLM_SPEND_FILE=None, LLM_BUDGET_USD=None):
        assert precheck("https://api.example.com/v1", "EMBED") == 0.0  # 상한 없으면 선차감 없음
    print("[selftest] 비용 관문 — 공유 장부 선차감(동시 20건 중 상한까지 10건만)·정산·precheck 선차감 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
