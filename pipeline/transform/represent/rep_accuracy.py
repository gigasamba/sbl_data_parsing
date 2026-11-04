"""pipeline 전용 엔진 결과 정확도 정의(10-14 함수별 분리 — common/core/repfmt.py에서 이전, 로직 바이트 동일).
parse_scoring.py·build_rep.py·agent/agent_tools.py만 쓴다(AG11 2단계 착수 조건으로 pipeline.transform.represent.parse_qa에서
common/repfmt.py로 옮긴 뒤, 10-14에 다시 파싱 모듈 쪽으로(지금 pipeline/) — 결국 pipeline 바깥에서 부르는 곳이 없었음)."""

# 표/이미지 인식 보너스 가중치 — cross_recall에 더해 통합 점수 산출
# 표 1개당 0.01점, 이미지 1개당 0.02점 (이미지가 더 희귀·가치 있으므로)
# 최대 0.2점까지 (20개 표 또는 10개 이미지) — cross_recall 범위(0~1)를 크게 벗어나지 않게
TABLE_BONUS = 0.01
FIGURE_BONUS = 0.02
BONUS_CAP = 0.2


def doc_accuracy(m, ref=None):
    """엔진 결과 1건의 정확도(정의 한 곳 — 요약·선정·순위·도구 공용).
    **교차 재현율 + 구조 인식 보너스**: 텍스트 토큰 교차 재현율(base)에 표·이미지 인식 개수만큼 보너스 가산.
    — 표/이미지를 더 많이 인식한 엔진이 대표로 선택될 확률이 높아짐.
    base = cross_recall → consensus_recall → value_recall 순.
    보너스 = min(table_count * TABLE_BONUS + figure_count * FIGURE_BONUS, BONUS_CAP).
    교차 재현율이 없으면(성공 계열 1개) 보너스 없이 base만."""
    if not m.get("ok"):
        return None
    order = ("cross_recall", "consensus_recall", "value_recall")
    base = next((m[k] for k in order if m.get(k) is not None), None)
    if base is None:
        return None
    # 구조 인식 보너스 — cross_recall이 있을 때만 가산 (정답 기반 value_recall에는 가산 안 함)
    if m.get("cross_recall") is not None:
        n_tables = m.get("tables") or 0
        n_figures = m.get("figures") or 0
        bonus = min(n_tables * TABLE_BONUS + n_figures * FIGURE_BONUS, BONUS_CAP)
        return round(base + bonus, 4)
    return base
