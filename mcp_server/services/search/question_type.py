"""집계 질문 단서 — 규칙만(LLM 0회), 질문 글자만 보고 건수·합계·최대/최소·평균을 묻는지 가린다.

호출자: rank_rules.py weights()(집계 질문이면 bm25 가중 조정).
ponytail: 정규식 하나 — 겹치는 단서(총액이 들어간 비교 질문 등)는 집계로 오분류할 수 있다. 더 정확해야 하면 작은 LLM 분류로.
"""

import re

_AGG_VOCAB = {  # 지표 판별 단서어(건수·합계)
    "count": ["건수", r"몇\s*건", "개수", r"몇\s*개(?!월)", r"how\s+many", r"number\s+of", r"\bcount\b"],
    # ↑ "몇\s*개(?!월)" — "몇 개월"(기간)이 건수 질문으로 걸리지 않게
    "sum": ["합계", "합", "총", "전체", r"모두\s*더", "total", "sum"],
}
_MAXMIN = r"가장\s*(많은|적은|큰|작은)|최대|최소|\bmax\b|\bmin\b|\bmost\b|\bleast\b"
_AVG = r"평균|average|\bavg\b"

AGGREGATE_RE = re.compile("|".join([*_AGG_VOCAB["count"], *_AGG_VOCAB["sum"], _MAXMIN, _AVG]), re.I)
