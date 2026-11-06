"""common.ai.llm — 실패 출구에서 호출 수 장부와 예산 선차감(LLM_BUDGET_USD 장부)이 늘 돌아오는지(허브 A — #106 뒤 누수 3건).
가짜 주소·가짜 _once만 — 네트워크 없음."""

import tempfile
from pathlib import Path
from unittest import mock

from common.ai import guard as G
from common.ai import llm as L
from common.config.settings import COMMON

MSGS = [{"role": "user", "content": "hello"}]
ENV = dict(
    RUN_ENV="local",
    LLM_BUDGET_USD="10",
    LLM_SPEND_FILE=str(Path(tempfile.mkdtemp()) / "spend.txt"),  # 하루 장부는 임시 자리 — 개발자 장부에 안 섞이게
    LLM_BASE_URL="https://llm.example.com/v1",
    LLM_MODEL="m-llm",
    LLM_PRICE_IN="1",
    LLM_PRICE_OUT="1",
    VLM_BASE_URL="https://vlm.example.com/v1",
    VLM_MODEL="m-vlm",
    VLM_ALLOW_EXTERNAL="1",
)


def _state():
    return L._stats["calls"], round(G.spend_total(), 9)


def _raise(ex):
    def f(*a, **k):
        raise ex

    return f


def test_leaks():
    def guard_refusal():  # 1 — require_internal 거부(LLM 외부·허용 없음), chat()처럼 이미 예약한 자리(call_reserved=True)
        L.reserve_call()
        L.complete("llm", MSGS, call_reserved=True)

    def unexpected(ex):  # 2 — _Retryable·ModelUnavailable이 아닌 예외(응답 JSON 깨짐 등) — VLM 외부 flat 선차감 + 예약 자리
        def run():
            L.reserve_call()
            with mock.patch.object(L, "_once", _raise(ex)):
                L.complete("vlm", MSGS, call_reserved=True)

        return run

    def do_call(ex):  # 3 — chat()의 _do_call: complete 실패면 토큰 기준 선차감을 환불(자리는 complete가 돌려줌)
        def run():
            with COMMON.env(LLM_ALLOW_EXTERNAL="1"), mock.patch.object(L, "_once", _raise(ex)):
                L._do_call(MSGS, 0.0, 10, False, ENV["LLM_BASE_URL"], ENV["LLM_MODEL"], None, 5)

        return run

    cases = [  # (이름, 실행, 기대 예외)
        ("guard refusal + call_reserved", guard_refusal, L.GuardBlocked),
        ("non-retryable unexpected exception", unexpected(KeyError("choices")), KeyError),
        ("ModelUnavailable (HTTP 400)", unexpected(L.ModelUnavailable("400")), L.ModelUnavailable),
        ("_do_call failure refund (ModelUnavailable)", do_call(L.ModelUnavailable("400")), RuntimeError),
        ("_do_call failure refund (unexpected)", do_call(ValueError("bad json")), ValueError),
    ]
    with COMMON.env(**ENV):
        L._model_down_reset(ENV["LLM_BASE_URL"])
        L._model_down_reset(ENV["VLM_BASE_URL"])
        for name, run, want in cases:
            start = _state()
            try:
                run()
                raise AssertionError(f"{name}: 예외가 안 남")
            except want:
                pass
            assert _state() == start, (name, start, _state())
        # 성공은 그대로 — 자리 1개·지출이 남는다
        start = _state()
        with (
            COMMON.env(LLM_ALLOW_EXTERNAL="1"),
            mock.patch.object(L, "_once", lambda *a, **k: ("ok", {"prompt_tokens": 1, "completion_tokens": 1})),
        ):
            assert L._do_call(MSGS, 0.0, 10, False, ENV["LLM_BASE_URL"], ENV["LLM_MODEL"], None, 5)[0] == "ok"
        calls, spent = _state()
        assert calls == start[0] + 1 and spent > start[1], (start, (calls, spent))
    print(f"[시험] llm 누수 — 실패 출구 {len(cases)}가지에서 호출 자리·예산 장부가 처음으로 · 성공은 그대로 통과")
