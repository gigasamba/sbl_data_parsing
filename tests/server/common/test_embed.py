"""common.ai.embed 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.ai.embed`."""

from pathlib import Path

import numpy as np

import common.ai.embed as M
from common.ai.embed import ROOT, _embed_uncached, _query_cache, embed_texts


def test_main():  # 옛 `if __name__ == "__main__":` 몸통 — 자기점검: RV1 — 질의 임베딩 캐시 기본 켬·해시 키만 저장·캐시 적중 바이트 동일·용량 상한·=0 끔
    import sqlite3
    import tempfile

    from common.config.settings import COMMON  # S7b — 시험이 읽는 값은 설정 객체(COMMON.env — os.environ은 안 바뀜)

    calls = []

    def _fake_uncached(embed, texts, kind):
        calls.append(len(texts))
        return np.array([[float(len(t)), float(i)] for i, t in enumerate(texts)], dtype=np.float32)

    _orig_uncached = _embed_uncached
    M._embed_uncached = _fake_uncached
    try:
        with tempfile.TemporaryDirectory() as td:
            cache_path = str(Path(td) / "q.sqlite")
            with COMMON.env(EMBED_QUERY_CACHE=cache_path, EMBED_QUERY_CACHE_MAX=None):
                v1 = embed_texts("e5-small", ["계약 금액은?"], "query")
                assert len(calls) == 1, "첫 호출은 미적중이라 _embed_uncached를 불러야 함"
                v2 = embed_texts("e5-small", ["계약 금액은?"], "query")
                assert len(calls) == 1, "같은 질문 재질의는 캐시 적중 — 다시 부르면 안 됨"
                assert np.array_equal(v1, v2), "캐시 적중 벡터가 미적중 결과와 바이트 동일해야 함(결정성)"

                db = sqlite3.connect(cache_path)
                k = db.execute("SELECT k FROM q").fetchone()[0]
                assert len(k) == 64 and all(c in "0123456789abcdef" for c in k), "평문 질문 저장 금지 — sha256(64자 16진) 해시만"
                db.close()

            with COMMON.env(EMBED_QUERY_CACHE=cache_path, EMBED_QUERY_CACHE_MAX="2"):
                for i in range(5):
                    embed_texts("e5-small", [f"질문{i}"], "query")
                db = sqlite3.connect(cache_path)
                n = db.execute("SELECT COUNT(*) FROM q").fetchone()[0]
                db.close()
                assert n <= 2, f"용량 상한(EMBED_QUERY_CACHE_MAX=2) 안 지켜짐: {n}행"

            bad = Path(td) / "bad.sqlite"
            bad.write_bytes(b"not a sqlite file" * 100)
            with COMMON.env(EMBED_QUERY_CACHE=str(bad), EMBED_QUERY_CACHE_MAX=None):
                calls.clear()
                assert embed_texts("e5-small", ["손상"], "query").shape == (1, 2) and len(calls) == 1, (
                    "캐시 손상이면 캐시 없이 계산(질의 실패 금지)"
                )

            with COMMON.env(EMBED_QUERY_CACHE="0", EMBED_QUERY_CACHE_MAX=None):
                calls.clear()
                embed_texts("e5-small", ["다시"], "query")
                embed_texts("e5-small", ["다시"], "query")
                assert len(calls) == 2, "EMBED_QUERY_CACHE=0이면 캐시 없이 매번 호출"

        default_path = ROOT / "output" / "query_cache.sqlite"
        for label, val in (("미설정", None), ("빈 값", "")):  # D-028 ⑩ — 빈 값도 기본 경로(옛 코드는 sqlite3.connect('') 임시 DB)
            default_path.unlink(missing_ok=True)
            with COMMON.env(EMBED_QUERY_CACHE=val):
                default_db = _query_cache()
                assert default_db is not None
                assert default_path.exists(), f"{label} 기본값은 {default_path}에 켬(RV1)"
                default_db.close()
                default_path.unlink(missing_ok=True)
    finally:
        M._embed_uncached = _orig_uncached
    print(
        "[selftest] RV1 — 질의 임베딩 캐시 기본 켬(미설정·빈 값 모두 기본 경로) · 해시 키만 저장 · 캐시 적중 바이트 동일 · 용량 상한 · EMBED_QUERY_CACHE=0 끔 통과"
    )
