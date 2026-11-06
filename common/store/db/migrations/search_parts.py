"""검색 갈래 판 파일이 함께 쓰는 "이 실행이 손대는 원천 스키마" 규칙(op-17) — 판 파일은 원천 목록을 직접 돌지 않고 sources()를 부른다
(시험 test_dev_source가 판 파일마다 확인 — 새 판이 DEV 원천 스키마를 조용히 건너뛰지 않게).
기준 실행(dbtool up — 기준 스키마): 판 파일이 굳혀 둔 고정 원천(5벌 등) 그대로. DEV 원천 실행(attributes sources = (dev_<n>,) — 판 기록 표는 그 스키마 안):
그 원천만, 기준 스키마 몫(옛 한 벌·시퀀스)은 건너뜀(dev_run)."""

from alembic import context


def dev_run():
    """DEV 원천 스키마 하나만 올리는 실행인가."""
    return bool(context.config.attributes.get("sources"))


def sources(fixed):
    """이 실행이 손대는 원천 — DEV 원천 실행이면 그 원천, 아니면 fixed(판 파일이 굳혀 둔 원천 목록, 순서 그대로)."""
    return tuple(context.config.attributes.get("sources") or fixed)
