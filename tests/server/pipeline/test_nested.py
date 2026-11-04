"""pipeline.transform.figures.nested_figures 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.figures.nested_figures`."""

import contextlib
import io
import json
from pathlib import Path

from common.ai import llm as A  # 모델 호출(0.2.0 — 옛 common.ai.adk, pl-46)
from common.config.settings import COMMON
from pipeline import config as pc
from pipeline.transform.figures.nested_figures import MAX_CHILDREN_TOTAL, _parse_regions, bbox_regions, child_crops, find_children


def selftest():
    import tempfile

    from PIL import Image

    d = Path(tempfile.mkdtemp())
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buf, "PNG")
    page_png = buf.getvalue()

    with pc.PIPE.env(PARSE_RAW_ROOT=str(d / "store")), COMMON.env(VLM_BASE_URL=None, VLM_MODEL=None):  # S7c — 설정 객체만 바꿔 끼움
        regions, prov = bbox_regions(page_png)
        assert regions == [] and "미설정" in prov["error"]
        crops, prov2 = child_crops(page_png)
        assert crops == [] and "미설정" in prov2["error"]
        assert find_children(page_png) == []
    print("[selftest] nested — VLM 미설정이면 자식 없이 빈 목록(파싱 계속) 통과")

    assert _parse_regions("아무 말") == []
    assert _parse_regions('{"regions": [{"bbox": [0.1, 0.1, 0.9, 0.9], "kind": "그래프"}, {"bbox": [1, 2]}]}') == [
        {"bbox": [0.1, 0.1, 0.9, 0.9], "kind": "그래프"}
    ]  # 모양이 안 맞는 둘째 항목은 버림
    print("[selftest] nested — _parse_regions: JSON 깨짐·모양 틀린 항목은 안전하게 버림 통과")

    _env = contextlib.ExitStack()  # S7c — 설정 객체만 바꿔 끼움(os.environ 안 건드림), finally에서 닫음
    _env.enter_context(pc.PIPE.env(PARSE_RAW_ROOT=str(d / "store2")))
    _env.enter_context(COMMON.env(VLM_BASE_URL="http://127.0.0.1:0", VLM_MODEL="test/model"))
    real_complete = A.complete
    calls = []

    def fake_find(role, messages, **kw):
        calls.append(("find", kw.get("agent")))
        return json.dumps({"regions": [{"bbox": [0.25, 0.25, 0.75, 0.75], "kind": "그래프"}]}, ensure_ascii=False), {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "cost": 0.0,
        }

    A.complete = fake_find
    try:
        crops, prov = child_crops(page_png)
        assert len(crops) == 1 and crops[0]["bbox_frac"] == [0.25, 0.25, 0.75, 0.75]
        img = Image.open(io.BytesIO(crops[0]["bytes"]))
        assert img.size == (200, 150)  # 400*0.5, 300*0.5(0.75-0.25) — 비율대로 자름
        crops2, prov2 = child_crops(page_png)  # 재호출 — P0 캐시로 호출 0
        assert len(calls) == 1 and prov2.get("cached")
        children = find_children(page_png, max_depth=2)
        assert [c["depth"] for c in children] == [1, 2]  # depth1 자식 + 그 자식 안에서 또 찾은 depth2 손자(같은 가짜 응답)
        assert children[0]["local_id"] == "c1" and children[0]["parent_local"] is None
        assert children[1]["local_id"] == "c1.c1" and children[1]["parent_local"] == "c1"  # 손자는 "c1" 뒤에 이어붙음
        assert len(calls) == 2  # depth1은 page_png와 같은 sha라 캐시 재사용(호출 0), depth2는 새 크롭 바이트라 호출 1건 추가

        def fake_find_1000(role, messages, **kw):  # G4 — Qwen-VL식 0~1000 좌표도 같은 비율로 읽어야 함
            return json.dumps({"regions": [{"bbox": [250, 250, 750, 750], "kind": "도면"}]}), {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "cost": 0.0,
            }

        A.complete = fake_find_1000
        other = io.BytesIO()
        Image.new("RGB", (400, 300), (250, 250, 250)).save(other, format="PNG")  # 다른 sha → 캐시 안 탐
        crops3, _ = child_crops(other.getvalue())
        assert len(crops3) == 1 and crops3[0]["bbox_frac"] == [0.25, 0.25, 0.75, 0.75], crops3
        print("[selftest] nested — 0~1000 정규화 좌표(Qwen-VL)도 비율로 환산 통과")
    finally:
        A.complete = real_complete
        _env.close()
    print("[selftest] nested — 가짜 VLM: bbox 비율대로 자름·P0 캐시 재사용(호출 0)·depth 2까지 재귀 통과")


def selftest_fanout_cap():
    """독립 검토(10-13) Minor — MAX_CHILDREN_TOTAL: 매 호출 MAX_REGIONS(4)개씩 돌려주는 가짜 VLM이라도 쪽 1장(손자 포함) 총합은 멈춘다."""
    import tempfile

    from PIL import Image

    d = Path(tempfile.mkdtemp())
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buf, "PNG")
    page_png = buf.getvalue()
    real_complete = A.complete
    calls2 = []

    def fake_always_four(role, messages, **kw):
        calls2.append(1)
        regions = [
            {"bbox": [0.1 * i, 0.1 * i, 0.1 * i + 0.25, 0.1 * i + 0.25], "kind": "그래프"} for i in range(4)
        ]  # 각 0.0625(≥MIN_AREA_RATIO) — 4개 다 살아남음
        return json.dumps({"regions": regions}, ensure_ascii=False), {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.0}

    A.complete = fake_always_four
    _env = contextlib.ExitStack()
    _env.enter_context(pc.PIPE.env(PARSE_RAW_ROOT=str(d / "store_fanout")))
    _env.enter_context(
        COMMON.env(VLM_BASE_URL="http://127.0.0.1:0", VLM_MODEL="test/model")
    )  # 옛 시험은 앞 시험이 둔 VLM env가 그대로 남은 채 돌았음 — 같은 상태 유지
    try:
        children = find_children(page_png, max_depth=2)
        # 깊이 제한 없이 그대로 두면 depth1에서 4개 × depth2에서 자식마다 또 4개(최대 20개)까지 나올 수 있었다 —
        # MAX_CHILDREN_TOTAL이 쪽 1장(손자 포함) 총합을 4로 막는다(depth1의 4개로 이미 다 차 depth2는 아예 안 돎).
        assert len(children) == MAX_CHILDREN_TOTAL, len(children)
        assert len(calls2) == 1  # 캡에 바로 걸려 depth2용 추가 호출은 한 번도 안 나감(호출 수도 같이 줄어듦)
    finally:
        A.complete = real_complete
        _env.close()
    print(
        "[selftest] nested — MAX_CHILDREN_TOTAL — 매 호출 MAX_REGIONS개씩 나와도 쪽 1장 자식(손자 포함) 총합 4로 멈춤(depth2 추가 호출 0) 통과"
    )


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
    selftest_fanout_cap()
