"""복합 질문 분해 — 묻는 것이 여러 개인 질문을 LLM 가이드로 독립 하위 질문으로 나눠, 하위 질문마다
근거를 따로 찾게 한다(벡터 1개가 여러 주제의 평균이 돼 셋 다 놓치는 '의미 희석' 방지).
분해는 검색·집계에만 쓰고 답변 LLM에는 원 질문 + 하위 질문 체크리스트를 같이 준다.
원본: 메인 저장소 src/qa_chat/decompose.py(2026-10-01, qa_chat용) — pipeline.py ask에 맞춰 이식(같은 프롬프트·규칙).
LLM은 내부 엔드포인트만(common/llm.py 가드). 낮 질의 전용 — 야간 배치는 LLM_BASE_URL을 지워 자동으로 꺼짐.
DECOMPOSE=0이면 끈다(평가 대조용). 사용: python modules/search/decompose.py (자기 점검)"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]  # dev/
from common.ai.agent_prompts import load as _load_prompt  # noqa: E402
from mcp_server import config as mc  # noqa: E402 — 설정 객체(S7d)

_MAX_SUBS = 5
# 값싼 1차 신호 — 걸린 질문만 LLM을 부른다(모든 질문에 호출 1회 추가를 막음)
_MULTI_ASK_RE = re.compile(r"그리고|및|또한|함께|각각|와 |과 |하고 |[,·/]|\?.+\?")
_MIN_LEN = 40

_PROMPT = _load_prompt("query_decompose", "split_question")  # AD33 — 글자는 dev/agents/query_decompose/prompt.md(ADK14 P2 경로 평탄화 이후)


def enabled() -> bool:
    d = mc.given("DECOMPOSE")  # 옛 `get("DECOMPOSE", 별칭) != "0"` — 준 값(빈 글자 포함 켬)이 우선
    return True if d is None else d  # S7e2 — 옛 별칭 QA_CHAT_DECOMPOSE는 읽지 않음(C-35, 사용자 10-28 — 기본 켬)


def needs_split(question: str) -> bool:
    return len(question) >= _MIN_LEN or bool(_MULTI_ASK_RE.search(question))


def split_question(question: str, llm_complete) -> tuple:
    """(하위 질문 목록, LLM 호출 수). 분해 불필요·실패면 ([], 호출 수) — 호출자는 원 질문 하나로 검색."""
    if not enabled() or not needs_split(question):
        return [], 0
    try:
        raw = llm_complete(_PROMPT.format(question=question))
    except Exception:
        return [], 1  # 분해 실패는 답변을 막지 않는다 — 원 질문 검색으로 폴백
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        subs = json.loads(m.group()).get("subs", []) if m else []
    except (json.JSONDecodeError, AttributeError):
        return [], 1
    subs = [s.strip() for s in subs if isinstance(s, str) and s.strip() and s.strip() != question.strip()]
    return (subs[:_MAX_SUBS] if len(subs) >= 2 else []), 1


def keep_context(subs: list, clients: list, find_clients) -> list:
    """LLM이 하위 질문에서 고객명을 빠뜨려도 원 질문의 고객 맥락을 잃지 않게 — 고객이 하나도 안 잡히는
    하위 질문 앞에 원 질문의 고객명을 붙인다(가이드만 믿지 않는 결정적 보정)."""
    if not clients:
        return subs
    prefix = ", ".join(clients)
    return [s if find_clients(s) else f"{prefix} — {s}" for s in subs]


def gather(question: str, subs: list, search, base: int, per: int) -> list:
    """원 질문은 search(q, base), 하위 질문은 search(q, per)로 찾아 라운드로빈으로 합친다(중복 제거) —
    원 질문 근거는 분해 전과 같은 개수를 유지하고, 어느 하위 질문도 근거가 0개로 밀려나지 않게 한다.
    search는 청크 키 목록을 돌려준다. 반환: [(키, 출처 질문 번호 0=원 질문)]."""
    lists = [search(question, base)] + [search(q, per) for q in subs]
    out, seen = [], set()
    for rank in range(max(base, per)):
        for qi, lst in enumerate(lists):
            if rank < len(lst) and lst[rank] not in seen:
                seen.add(lst[rank])
                out.append((lst[rank], qi))
    return out


def checklist(subs: list) -> str:
    if not subs:
        return ""
    lines = "\n".join(f"{i}. {s}" for i, s in enumerate(subs, 1))
    return f'[하위 질문 체크리스트 — 각 항목에 빠짐없이 답하라. 근거가 없는 항목은 그 항목만 "근거 없음"으로 표시하라]\n{lines}\n\n'
