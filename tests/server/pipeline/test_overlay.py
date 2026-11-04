"""pipeline.transform.figures.overlay_groups 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.figures.overlay_groups`."""

from pipeline.transform.figures.overlay_groups import cluster_overlaps


def selftest():
    # cluster_overlaps — 핵심(순수) 로직: 겹침·포함 연결 요소, 그림+그외 섞인 묶음만
    objs = [
        {"id": "pic1", "kind": "picture", "bbox": (0, 0, 100, 100)},
        {"id": "text1", "kind": "other", "bbox": (50, 50, 150, 70), "text": "콜아웃 글자"},  # pic1과 겹침
        {"id": "pic2", "kind": "picture", "bbox": (500, 500, 600, 600)},  # 혼자(겹침 상대 없음)
        {"id": "text2", "kind": "other", "bbox": (700, 700, 750, 720), "text": "무관 글자"},  # 혼자
    ]
    got = cluster_overlaps(objs)
    assert len(got) == 1, got
    assert got[0]["members"] == ["pic1", "text1"]
    assert got[0]["picture_ids"] == ["pic1"] and got[0]["other_ids"] == ["text1"]
    assert got[0]["texts"] == ["콜아웃 글자"]
    assert got[0]["bbox"] == (0, 0, 150, 100)
    print("[selftest] cluster_overlaps — 겹친 그림+글상자만 묶고 혼자인 것은 뺌 통과")

    # 포함(containment) — 작은 화살표 도형이 그림 안에 완전히 들어간 경우도 묶여야 함
    contained = [
        {"id": "pic1", "kind": "picture", "bbox": (0, 0, 200, 200)},
        {"id": "arrow1", "kind": "other", "bbox": (80, 80, 120, 120)},
    ]
    got2 = cluster_overlaps(contained)
    assert len(got2) == 1 and got2[0]["members"] == ["arrow1", "pic1"], got2
    print("[selftest] cluster_overlaps — 포함(그림 안에 완전히 든 도형)도 묶임 통과")

    # 안 겹침(옆에 나란히) — 음성(negative) 사례, 묶이면 안 됨
    side_by_side = [
        {"id": "pic1", "kind": "picture", "bbox": (0, 0, 100, 100)},
        {"id": "text1", "kind": "other", "bbox": (150, 0, 250, 20), "text": "옆 글자"},
    ]
    assert cluster_overlaps(side_by_side) == []
    print("[selftest] cluster_overlaps — 겹치지 않으면(옆에 나란히) 묶지 않음 통과")

    # 그림끼리만 겹침(그 외 없음) — 묶음 대상 아님(F12는 그림+그 외 조합만)
    pics_only = [
        {"id": "pic1", "kind": "picture", "bbox": (0, 0, 100, 100)},
        {"id": "pic2", "kind": "picture", "bbox": (50, 50, 150, 150)},
    ]
    assert cluster_overlaps(pics_only) == []
    print("[selftest] cluster_overlaps — 그림끼리만 겹치면(그 외 없음) 묶음 아님 통과")

    # 독립 검토(10-14) — 전면 배경 그림(쪽의 90%) + 서로 안 겹치는 그림·글상자 여러 개: page_area 없이 부르면
    # 배경을 통해 전부가 한 거대 묶음으로 뭉치던 버그, page_area를 주면 배경이 후보에서 빠져 묶음이 아예 없어야 함
    bg = {"id": "bg", "kind": "picture", "bbox": (0, 0, 950, 950)}  # 1000x1000 쪽의 90.25%(>40%)
    small_pic = {"id": "pic2", "kind": "picture", "bbox": (0, 0, 100, 100)}  # 왼쪽 위 모서리
    small_text = {"id": "text1", "kind": "other", "bbox": (800, 800, 900, 900), "text": "구석 글자"}  # 오른쪽 아래, small_pic과 안 겹침
    overclustered = [bg, small_pic, small_text]
    assert len(cluster_overlaps(overclustered)) == 1, "page_area 없이는(단위 모름) 필터 안 함 — 배경 통해 뭉침 그대로"
    assert cluster_overlaps(overclustered, page_area=1000 * 1000) == [], (
        "배경(90%>40%)은 후보에서 빠지고 남은 둘은 서로 안 겹쳐 묶음 0개여야 함"
    )
    print("[selftest] cluster_overlaps — page_area 주면 전면 배경(>40%)이 빠져 과다 결합(모든 개체 한 묶음) 안 함 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
