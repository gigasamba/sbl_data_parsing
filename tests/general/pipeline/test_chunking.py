"""pipeline.transform.structure.chunking 시험."""

import re

from pipeline import config as pc
from pipeline.transform.structure.chunking import chunk_structure


def selftest():
    import contextlib

    # S7c — 설정 객체(env 안 건드림): 겹쳐 쓴 값은 with가 끝나면 모두 풀림(옛 pop·복원 코드 대신)
    with contextlib.ExitStack() as env:
        env.enter_context(pc.PIPE.env(CHUNK_TABLE=None, CHUNK_TABLE_ROWS=None, CHUNK_SIZE=None))
        # 기본 경로(CHUNK_TABLE 없음) — 표는 통째로 한 청크(전과 바이트 동일)
        text = "# 제목\n본문 한 줄\n\n코드 | 수량\n" + "\n".join(f"A-{i:03d} | {i}" for i in range(1, 6))
        out = chunk_structure("d", text)
        assert len(out) == 2
        assert "코드 | 수량" in out[1]["text"] and "A-001 | 1" in out[1]["text"]

        # 그림 블록은 CHUNK_TABLE=rows에서도 절대 안 쪼갬(그림 속 표가 CHUNK_TABLE_ROWS보다 커도)
        env.enter_context(pc.PIPE.env(CHUNK_TABLE="rows", CHUNK_TABLE_ROWS="3"))
        fig_rows = "\n".join(f"코드{i} | 값{i}" for i in range(1, 10))
        out = chunk_structure("d", f"[그림 d#p1#i1] (표)\n요약: 테스트\n코드 | 값\n{fig_rows}\n\n본문")
        fig = next(c for c in out if c["text"].startswith("[그림 "))
        assert all(f"코드{i} | 값{i}" in fig["text"] for i in range(1, 10))

        # 60행 표 → 3청크(기본 CHUNK_TABLE_ROWS=25), 청크마다 머리글 반복 + '머리글: 값' 쌍
        env.enter_context(pc.PIPE.env(CHUNK_TABLE_ROWS=None))
        rows = "\n".join(f"코드-{i:03d} | {i} | USD {i * 10}" for i in range(1, 61))
        out = chunk_structure("d", f"## 계약 목록\n코드 | 수량 | 금액\n{rows}\n")
        tbl = [c for c in out if "코드 | 수량 | 금액" in c["text"]]
        assert len(tbl) == 3
        ids = {m for c in tbl for m in re.findall(r"코드-\d{3}", c["text"])}
        assert len(ids) == 60 and "코드-001" in ids and "코드-060" in ids
        assert "코드: 코드-001" in tbl[0]["text"]  # 머리글: 값 쌍(BM25·ID용)

        # 쪽 넘는 표: 머리글 없는 다음 조각(같은 열 수)을 앞 표에 이어 붙여 한 표로
        env.enter_context(pc.PIPE.env(CHUNK_TABLE_ROWS="20"))
        t1 = "\n".join(f"P-{i} | {i}" for i in range(1, 6))
        t2 = "\n".join(f"P-{i} | {i}" for i in range(6, 9))
        out = chunk_structure("d", f"코드 | 수량\n{t1}\n\n{t2}\n")
        assert len(out) == 1 and out[0]["text"].startswith("코드 | 수량")
        assert all(f"P-{i} | {i}" in out[0]["text"] for i in range(1, 9))

    print("[selftest] 표 행 쪼개기(W14)·그림 보호·쪽 넘김 이어붙이기·기본 경로 불변 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
