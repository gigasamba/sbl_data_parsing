"""common.ai.llm 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.ai.llm`."""

from pathlib import Path

from common.ai.guard import is_internal
from common.ai.llm import LLMUnavailable, _cache_path, _stats, cache_key, chat


def test_main():  # 옛 `if __name__ == "__main__":` 몸통 — 자기점검: 내부 주소 판정 (S7b — 시험이 읽는 값은 설정 객체라 COMMON.env로 겹쳐 씀, os.environ은 안 바뀜)
    from common.config.settings import COMMON

    assert is_internal("http://10.0.0.5:8000/v1") and is_internal("http://localhost:8765/v1") and is_internal("http://[::1]:8000/v1")
    assert not is_internal("https://generativelanguage.googleapis.com/v1beta/openai")
    with COMMON.env(LLM_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai", LLM_MODEL="x"):
        try:
            chat([{"role": "user", "content": "x"}])  # allow_external 없음 → 호출 전에 거부
            raise AssertionError("외부 가드 실패")
        except LLMUnavailable:
            pass
    print("llm self-check OK")

    # RV12 — 빈 응답 안전망: 1차가 빈 응답(토큰은 썼음 — 생각이 max_tokens를 다 먹은 신호) → max_tokens×4로 딱 한 번
    # 재요청 · 성공한 응답만 원래 max_tokens 키로 캐시(다음 같은 호출은 재시도 없이 적중) · 두 호출 다 공유 장부(_stats)에.
    import shutil
    import tempfile

    import common.ai.adk as _adk

    _orig_complete = _adk.complete
    _tmp1 = tempfile.mkdtemp()
    _seen_mt = []

    def _stub_truncated(role, messages, **kw):
        _seen_mt.append(kw.get("max_tokens"))
        if len(_seen_mt) == 1:
            return "", {"prompt_tokens": 10, "completion_tokens": 50}  # 1차 — 생각이 다 먹음(빈 응답, 토큰 소모)
        return "실제 답", {"prompt_tokens": 10, "completion_tokens": 60}  # 2차(4배 max_tokens) — 성공

    _adk.complete = _stub_truncated
    try:
        with COMMON.env(LLM_BASE_URL="http://127.0.0.1:9/v1", LLM_MODEL="mock-reasoning", LLM_CACHE_DIR=_tmp1):
            before = dict(_stats)
            text = chat([{"role": "user", "content": "질문"}], max_tokens=500, agent="x")
            assert text == "실제 답", text
            assert _seen_mt == [500, 2000], _seen_mt  # 재요청 1회 · max_tokens 4배(상한 8000 안 걸림)
            after = dict(_stats)
            assert after["calls"] - before["calls"] == 2, (before, after)  # 두 호출 다 공유 장부(LLM_MAX_CALLS)에
            assert after["tokens_out"] - before["tokens_out"] == 110, after  # 50+60 — 재요청 비용도 집계
            _seen_mt.clear()
            text2 = chat([{"role": "user", "content": "질문"}], max_tokens=500, agent="x")  # 캐시 적중 — 재호출 없음
            assert text2 == "실제 답" and _seen_mt == [], _seen_mt
    finally:
        _adk.complete = _orig_complete
        shutil.rmtree(_tmp1, ignore_errors=True)
    print("[selftest] RV12 — 빈 응답(생각이 토큰 다 씀) 재요청 1회(4배)·캐시는 성공 응답만(원래 키)·공유 장부 2건 집계 통과")

    # LLM_EMPTY_RETRY=0 — 재요청 없이 빈 응답 그대로 · 빈 응답은 캐시에 안 씀(전에는 캐시에 고착돼 다음 호출도 계속 빈 응답 재생)
    _tmp2 = tempfile.mkdtemp()
    _hits = []

    def _stub_always_empty(role, messages, **kw):
        _hits.append(1)
        return "", {"prompt_tokens": 10, "completion_tokens": 50}

    _adk.complete = _stub_always_empty
    try:
        with COMMON.env(
            LLM_BASE_URL="http://127.0.0.1:9/v1",
            LLM_MODEL="mock-reasoning2",
            LLM_CACHE_DIR=_tmp2,
            LLM_EMPTY_RETRY="0",
        ):
            text = chat([{"role": "user", "content": "질문2"}], max_tokens=500, agent="x")
            assert text == "" and len(_hits) == 1, (text, _hits)  # LLM_EMPTY_RETRY=0 — 재요청 안 함
            key = cache_key("mock-reasoning2", [{"role": "user", "content": "질문2"}], 0.0, 500, False)
            assert not _cache_path(key).exists(), "빈 응답을 캐시에 쓰면 안 됨"
    finally:
        _adk.complete = _orig_complete
        shutil.rmtree(_tmp2, ignore_errors=True)
    print("[selftest] RV12 — LLM_EMPTY_RETRY=0(끔) 재요청 없음 · 빈 응답 캐시 안 씀 통과")

    _m = [{"role": "user", "content": "q"}]
    with COMMON.env(LLM_EXTRA_BODY=None):
        _k0 = cache_key("x", _m)
        with COMMON.env(LLM_EXTRA_BODY='{"reasoning": {"enabled": false}}'):
            _k1 = cache_key("x", _m)
        with COMMON.env(LLM_EXTRA_BODY="{}"):
            _k2 = cache_key("x", _m)  # 옛 `if eb`는 글자 "{}"도 참 — 빈 객체도 열쇠에 들어감
        assert _k0 != _k1 and _k0 == cache_key("x", _m), "LLM_EXTRA_BODY가 캐시 열쇠에 들어가야 함(미설정이면 기존 열쇠)"
        assert _k2 not in (_k0, _k1)
    print("[selftest] SEC-2 — LLM_EXTRA_BODY(생각 켬/끔)별 캐시 열쇠 분리 통과")

    # D-028 ⑧(S7b) — RUN_ENV가 dev·stage·prd면 외부 주소는 allow_external이 열려도 거부, local은 지금처럼 허용
    _tmp3 = tempfile.mkdtemp()
    _adk.complete = lambda role, messages, **kw: ("외부 답", {"prompt_tokens": 1, "completion_tokens": 1})
    try:
        _ext = dict(
            LLM_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai",
            LLM_MODEL="x-ext",
            LLM_CACHE_DIR=str(Path(_tmp3) / "cache"),
            LLM_BUDGET_USD=None,
        )
        for _env in (None, "dev", "stage", "prd", "prod", "Local"):  # 없음·모르는 글자도 서버로 보고 거부(allow_external=True여도)
            with COMMON.env(RUN_ENV=_env, **_ext):
                try:
                    chat([{"role": "user", "content": "q"}], allow_external=True, agent="x")
                    raise AssertionError(f"RUN_ENV={_env}인데 외부 LLM 허용됨")
                except LLMUnavailable as _e:
                    assert ("RUN_ENV 없음" if _env is None else f"RUN_ENV={_env}") in str(_e), str(_e)
        with COMMON.env(RUN_ENV="local", **_ext):
            assert chat([{"role": "user", "content": "q"}], allow_external=True, agent="x") == "외부 답"
    finally:
        _adk.complete = _orig_complete
        shutil.rmtree(_tmp3, ignore_errors=True)
    print("[selftest] RUN_ENV — dev·stage·prd는 외부 허용이 켜져도 외부 LLM 거부 · local은 허용 통과")
