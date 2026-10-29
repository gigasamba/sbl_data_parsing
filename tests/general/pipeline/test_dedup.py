"""pipeline.extract.dedup 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.extract.dedup --selftest`."""

import difflib
import sys

from pipeline.extract.dedup import candidate_pairs


def selftest():
    """후보 쌍이 이름 유사(≥0.9) 쌍을 하나도 놓치지 않는지 — 무작위 이름(삽입·삭제·치환 변형)을 모든 쌍 비교와 대조."""
    import random

    random.seed(5)
    al, names = "abcde가나다라1234_", []
    for _ in range(300):
        b = "".join(random.choice(al) for _ in range(random.randint(2, 24)))
        x = list(b)
        k = random.randrange(len(x))
        [lambda: x.insert(k, "z"), lambda: x.__delitem__(k) if len(x) > 1 else None, lambda: x.__setitem__(k, "z")][random.randrange(3)]()  # noqa: B023 — 고른 하나를 바로 부름
        names += [b, "".join(x)]
    info = [{"sha": str(i), "ahash": None, "sketch": None, "name": nm} for i, nm in enumerate(names)]
    cand = candidate_pairs(info)["name"]
    true = {
        (i, j)
        for i in range(len(names))
        for j in range(i + 1, len(names))
        if difflib.SequenceMatcher(None, names[i], names[j]).ratio() >= 0.9
    }
    assert true and true <= cand, sorted(true - cand)[:5]
    assert len(cand) < len(names) ** 2 / 20  # 모든 쌍보다 훨씬 적음
    print(f"[selftest] 이름 후보 쌍 {len(cand)}개가 유사 쌍 {len(true)}개를 모두 포함 — 통과")


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    selftest()
    sys.exit()
