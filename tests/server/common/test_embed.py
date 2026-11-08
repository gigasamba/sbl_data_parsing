"""common.ai.embed 자기 점검 — 질의 임베딩 캐시(프로세스 안 LRU)."""

from unittest import mock

import numpy as np

import common.ai.embed as M


def test_main():  # 같은 질문은 다시 안 부름 · 적중 벡터 같음 · 모델이 바뀌면 다른 열쇠 · 문서 청크('passage')는 캐시 안 함
    from common.config.settings import COMMON  # 시험이 읽는 값은 설정 객체(COMMON.env — os.environ은 안 바뀜)

    calls = []

    def fake(embed, texts, kind, timeout=None):
        calls.append((tuple(texts), kind, timeout))
        return np.array([[float(len(t)), float(i)] for i, t in enumerate(texts)], dtype=np.float32)

    cases = [  # (모델, 질문 목록, kind, 이 줄에서 늘어날 호출 수)
        ("m-a", ["계약 금액은?"], "query", 1),  # 처음 — 부름
        ("m-a", ["계약 금액은?"], "query", 0),  # 같은 질문 — 캐시
        ("m-a", ["계약 금액은?", "새 질문"], "query", 1),  # 새 질문만 부름
        ("m-b", ["계약 금액은?"], "query", 1),  # 모델이 바뀜 — 다른 열쇠
        ("m-a", ["청크"], "passage", 1),
        ("m-a", ["청크"], "passage", 1),  # passage는 캐시 안 함
    ]
    M._query_vec.cache_clear()
    try:
        with mock.patch.object(M, "_embed_uncached", fake):
            first = None
            for model, texts, kind, more in cases:
                before = len(calls)
                with COMMON.env(EMBED_MODEL=model):
                    got = M.embed_texts("api", texts, kind, timeout=25)
                assert len(calls) - before == more and got.shape == (len(texts), 2), (model, texts, kind, calls)
                if first is None:
                    first = got
            with COMMON.env(EMBED_MODEL="m-a"):  # 적중 벡터 = 처음 결과(결정성)
                assert np.array_equal(M.embed_texts("api", ["계약 금액은?"], "query", timeout=25), first)
            assert all(t == 25 for _, _, t in calls), calls  # 부르는 쪽 제한 시간이 그대로 감
    finally:
        M._query_vec.cache_clear()
    print("[selftest] 질의 임베딩 LRU — 같은 질문 재사용·모델별 열쇠·passage는 캐시 안 함 통과")
