"""mcp_server.services.search.evidence_shape 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.evidence_shape`."""

import json

from mcp_server.services.search.evidence_shape import cap


def _cap_bytes(obj):
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _selftest_cap_ranked():
    """AR5 — 랭크 인지 cap(): 1위 보호·aggregate 보호·꼬리부터 뺌.
    독립 검토 BLOCK(10-12) 뒤 — 랭크 경로의 모든 사례에 바이트 상한 assert 추가(truncation 칸이 루프 끝난 뒤
    붙어 그 칸만큼 limit을 넘기던 결함 재발 방지) + non-str text(int·list·None) 복원력 사례."""
    # 1) 1위(index 0) 보호 — 꼬리(가장 낮은 순위)만 줄여도 한도 안이면 1위는 안 건드림
    o = {"evidence": [{"text": "A" * 400}, {"text": "B" * 50}, {"text": "C" * 5000}]}
    cap(o, 1000)
    assert o["evidence"][0]["text"] == "A" * 400 and o["truncated"] is True
    assert len(o["evidence"][2]["text"]) < 5000 + len(" …(잘림)")  # 꼬리(C)가 줄어듦
    assert o["truncation"]["trimmed"] >= 1
    assert _cap_bytes(o) <= 1000

    # 2) via=aggregate 보호(index 0이 아니어도) — index 1이 aggregate면 그대로, index 2(꼬리)만 줄어듦
    o = {"evidence": [{"text": "a" * 50}, {"text": "G" * 300, "via": "aggregate"}, {"text": "C" * 5000}]}
    cap(o, 2000)
    assert o["evidence"][1]["text"] == "G" * 300  # aggregate 항목은 안 건드림(다른 항목이 남아있는 동안)
    assert len(o["evidence"][2]["text"]) < 5000
    assert _cap_bytes(o) <= 2000

    # 3) 바닥(300자) 아래로는 못 줄이는 항목들 — 꼬리부터 통째로 뺌
    o = {"evidence": [{"text": "x" * 80}, {"text": "y" * 250}, {"text": "z" * 250}]}
    cap(o, 120)
    assert "z" * 250 not in [e.get("text") for e in o["evidence"]]  # 꼬리(z)가 먼저 빠짐
    assert o["truncation"]["dropped"] >= 1
    assert _cap_bytes(o) <= 120

    # 5) 독립 검토 BLOCK 재현 — truncation 칸을 루프 끝난 뒤 붙이면 그 칸 바이트가 limit 비교에 안 들어가
    # 최종 결과가 limit을 넘길 수 있었다(수정 전 111바이트 > limit 100). text가 int([{"text": 12345}])인 경우도 같이 확인.
    o = {"question": "q", "evidence": [{"text": 12345}, {"text": "y" * 500}]}
    cap(o, 100)
    assert _cap_bytes(o) <= 100

    # 6) non-str text(int·list·None) — 죽지 않고 str()로 다뤄짐
    o = {"evidence": [{"text": 12345}, {"text": ["a", "b"]}, {"text": None}, {"text": "z" * 5000}]}
    cap(o, 1000)
    assert _cap_bytes(o) <= 1000

    print("[selftest] cap() AR5 — 1위·aggregate 보호·꼬리 drop 통과")


def _selftest_cap_fuzz():
    """AR7 — 랜덤 모양 200개: evidence 유무·길이·text 자료형(str·int·list·None)을 무작위로 섞어도 cap()이 안 죽고,
    한도를 넘겼으면 반드시 "더 줄일 게 없을 때"(근거가 다 비었을 때)뿐이다 — truncation 칸 자체의 바이트(오버헤드)만으로
    아주 작은 한도를 못 맞추는 경우도 이 조건으로 걸러진다. S5(10-26, D-025) — research() 모양(requirements[i].evidence·
    answer)은 cap()에서 뺐으므로 그 모양 생성·판정도 뺐다."""
    import copy
    import random

    rng = random.Random(20261012)

    def rand_text():
        pick = rng.random()
        if pick < 0.08:
            return None
        if pick < 0.16:
            return rng.randint(0, 999999)
        if pick < 0.22:
            return ["a", "b"]
        return "T" * rng.choice([0, 1, 50, 300, 999, 3000, 9000])

    def rand_evidence(n_max):
        out = []
        for _ in range(rng.randint(0, n_max)):
            e = {"text": rand_text()}
            if rng.random() < 0.15:
                e["via"] = "aggregate"
            out.append(e)
        return out

    def rand_obj():
        o = {"question": "q" * rng.randint(0, 20)}
        if rng.random() < 0.7:
            o["evidence"] = rand_evidence(rng.randint(0, 10))
        return o

    for _ in range(200):
        obj = rand_obj()
        limit = rng.choice([80, 500, 2000, 20000])
        result = cap(copy.deepcopy(obj), limit)
        size = _cap_bytes(result)
        if "truncation" in result:
            assert result["truncation"]["trimmed"] >= 0 and result["truncation"]["dropped"] >= 0
        if size > limit:  # 더 줄일 게 없을 때만 허용(근거가 다 비었을 때)
            assert not (result.get("evidence") or []), (obj, limit, size)
    print("[selftest] cap() AR7 — 랜덤 모양 200개 fuzz(더 줄일 게 없을 때만 한도 초과 허용) 통과")


def test_main():  # 옛 main.py selftest가 부르던 순서(이 모듈 몫만) — evidence_shape.py(옛 shaping)엔 __main__이 없었음
    _selftest_cap_ranked()
    _selftest_cap_fuzz()
