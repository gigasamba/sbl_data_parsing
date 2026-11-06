"""common.ai.guard 자기 점검."""

import os
import socket
import tempfile

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
    # 시험이 읽는 값은 설정 객체(COMMON.env — os.environ은 안 바뀜). 바깥 env의 값이 시험에 새지 않게 비워 두고 시작
    from common.config.settings import COMMON

    with COMMON.env(
        LLM_SPEND_FILE=os.path.join(tempfile.mkdtemp(), "spend.txt"),  # 하루 장부는 임시 자리
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
        assert not is_internal("http://147.46.10.10:8000/v1")  # 사설 밖 사내 대역 — 설정 없으면 외부
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
    # 외부 허용(스위치 + RUN_ENV=local) — 설정 객체에는 가짜 접두 칸이 없어 진짜 접두 EMBED로 시험
    EXTU = "https://openrouter.ai/api/v1"
    with COMMON.env(EMBED_ALLOW_EXTERNAL=None):  # 허용 없음 → 거부
        try:
            require_internal(EXTU, "EMBED")
            raise AssertionError("허용 없이 외부 허용됨")
        except RuntimeError:
            pass
    with COMMON.env(RUN_ENV="local", EMBED_ALLOW_EXTERNAL="1"):
        require_internal(EXTU, "EMBED")  # 허용 + RUN_ENV=local → 허용
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
    ):  # 서버 환경은 허용이 열려도 거부(내부 주소는 영향 없음) · 없음·모르는 글자도 서버로
        with COMMON.env(RUN_ENV=env, EMBED_ALLOW_EXTERNAL="1"):
            try:
                require_internal(EXTU, "EMBED")
                raise AssertionError(f"RUN_ENV={env}인데 외부 허용됨")
            except RuntimeError as e:
                assert ("RUN_ENV 없음" if env is None else f"RUN_ENV={env}") in str(e), str(e)
            assert not external_allowed("EMBED")
            require_internal("http://10.0.0.5:8000/v1", "EMBED")
    # 가짜 LLM 응답은 local 전용: 서버·모르는 값에서 켜져 있으면 거부, RUN_ENV 없음(selftest)·local은 허용, 꺼져 있으면 늘 False
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
    # 비용 관문 — 공유 장부 선차감이 동시 호출에도 상한을 넘지 않음
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
    print("[selftest] 비용 관문 — 공유 장부 선차감(동시 20건 중 상한까지 10건만)·정산·precheck 선차감 통과")
    # 하루 상한(기본 0.1달러/하루/PC 사용자): (상한 칸, 날짜, 선차감, 통과?, 그날 합계)
    from pathlib import Path
    from unittest import mock

    from common.ai import guard as G
    from common.core.paths import SPEND_DIR

    rows = [
        (None, "2026-11-03", 0.06, True, 0.06),  # 기본 0.1 적용
        (None, "2026-11-03", 0.03, True, 0.09),  # 같은 날은 쌓임
        (None, "2026-11-03", 0.02, False, 0.09),  # 0.11 > 0.1 — 거부, 장부 그대로
        (None, "2026-11-04", 0.08, True, 0.08),  # 새 날짜는 0부터
        ("0.05", "2026-11-05", 0.06, False, 0.0),  # 적은 상한도 지킴
        ("0.5", "2026-11-05", 0.3, True, 0.3),  # 큰 상한도 지킴
    ]
    led = Path(tempfile.mkdtemp()) / "spend.txt"
    for budget, day, usd, ok, total in rows:
        with COMMON.env(LLM_SPEND_FILE=str(led), LLM_BUDGET_USD=budget), mock.patch.object(G.time, "strftime", return_value=day):
            assert G.budget_usd() == (float(budget) if budget else 0.1)
            try:
                spend_reserve(usd, "T")
                got = True
            except BudgetExceeded:
                got = False
            assert got is ok and abs(spend_total() - total) < 1e-9, (budget, day, usd, got, spend_total())
            assert G.ledger_file().name == f"spend-{day}.txt"
    # 자정을 넘긴 반환은 선차감한 날 장부로(다음 날 상한을 늘리지 않게)
    with COMMON.env(LLM_SPEND_FILE=str(led), LLM_BUDGET_USD=None):
        with mock.patch.object(G.time, "strftime", return_value="2026-11-06"):
            spend_reserve(0.09, "T")
        with mock.patch.object(G.time, "strftime", return_value="2026-11-07"):
            G.release_reserve(0.09)
            assert spend_total() == 0.0, spend_total()  # 새 날 장부는 그대로 0(-0.09가 안 들어옴)
        assert abs(G._ledger_sum(G.ledger_file("2026-11-06"))) < 1e-9
    with COMMON.env(LLM_SPEND_FILE=None), mock.patch.object(G.time, "strftime", return_value="2026-11-03"):
        assert G.ledger_file() == SPEND_DIR / "2026-11-03.txt"  # 장부 칸이 비면 PC 기본 자리(쓰지는 않음)
    print("[selftest] 하루 상한 — 기본 0.1·같은 날 누적·새 날짜 0부터·설정한 상한 통과")


def test_main():
    selftest()
