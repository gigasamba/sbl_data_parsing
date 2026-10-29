# gold_human — 사람이 쓴 정답지 흉내(합성)

개발 서버 실문서 사람 정답(S17·ST7)과 같은 조건을 PC에서 시험: 8건 중 4건만 · 앞부분+표만 · 파일 이름 대소문자·공백 제멋대로 · 정규화가 흡수할 표기(전각 숫자·℃·특수 공백)와 흡수 못 할 진짜 차이 1건(symbol_spec.pdf 2~8°C) · 없는 문서 정답 1건(`없는문서.pdf.txt`).
생성: `python dev_tools/synthetic_data_gen/gen_synth_human_gold.py`(원천 = ../gold/*.md, 파싱 결과는 안 봄).
기대: score_gold 정답 문서 4건 · 못 맞춘 정답 1건(없는문서).
