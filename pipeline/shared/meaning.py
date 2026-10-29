"""pipeline 전용 유의미 텍스트 보조(10-14 함수별 분리 — common/core/meaning.py에서 이전, 로직 바이트 동일).
canon_num_key는 parse_qa.build_token_consensus·postprocess/reread.py만 쓴다(common.core.meaning.tokens는
check_modules.py의 CONTRACT_FUNCS라 공통에 그대로 남아 있음 — 거기서 쓰는 값과 섞이지 않게 여기서 순수 함수로)."""

import re


def canon_num_key(tok):
    """AD25(a) 충돌 탐지 전용(tokens()는 이 값으로 합치지 않는다 — 모호해서) — 430.000과 430,000처럼 천 단위
    구분자로 보이는 자리를 모두 지운 정규값. parse_qa.build_token_consensus가 같은 계열 사이에서 표기가 갈리는
    숫자(conflicts)를 찾을 때만 쓴다. 3자리 묶음 모양(쉼표·마침표)이 아니면 None(충돌 비교 대상 아님 — 4,30,000은
    묶음이 무효라 여기도 안 걸린다)."""
    core = tok.rstrip(".,:/-")
    if not re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", core):
        return None
    return re.sub(r"[,.]", "", core)
