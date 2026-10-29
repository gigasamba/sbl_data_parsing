"""pipeline — 문서 → 파싱 → 구조화 → 적재 → 게시(refactor_plan 4-1 · S4 10-26, 옛 data_etl/ + 단계 4 도구).
일부러 비워 둔다: 여기서 common을 import하면 옛 data_etl(패키지 입구 없음) 모듈들이 옵션 카탈로그를 더 일찍 받아 import 때 읽는
env 기본값이 바뀐다(S4 상태 비교 — output/orca/S4-impl.md). common_tools/cli·evaluation에서 옮긴 단계 4 도구는 파일 첫 줄에서
`import common`을 한다(옛 common_tools/__init__.py가 하던 것).
"""
