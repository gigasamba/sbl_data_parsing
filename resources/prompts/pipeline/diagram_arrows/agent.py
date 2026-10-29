"""diagram_arrows — F13: 래스터 그림(저해상도·래스터) 속 화살표 전부를 세어보고 edges로(규칙 기반 vector·glyph
추출이 못 미치는 래스터 전용 — 2~3배 확대한 크롭을 보냄, 호출부는 parse/postprocess/figures.py가 될 예정).
Caller: (예정) figures.py vlm_fig류 — 지금은 cases.json 가짜 모델로만 검증(실 VLM 호출 없음, F13 범위 — 비용
승인 전까지 서버 실측 보류). instruction은 ""로 둬 ADK가 identity 시스템 문구를 안 붙인다(figure_describe와 같은 관례)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "diagram_arrows: pipeline agent takes no tools(흐름은 호출부 파이썬 코드)"
    return LlmAgent(name="diagram_arrows", model=model, mode="single_turn", instruction="",
                     description="그림 속 화살표 전부를 세어보고 edges로 — 셀프체크(화살표 개수)")
