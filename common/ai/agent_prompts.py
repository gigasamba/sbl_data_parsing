"""dev/agents/<id>/prompt.md(또는 여러 개면 <prompt_id>.md) 로더 — 지시문 글자를 패키지 안에 두고, 호출
코드는 이 함수로 읽어 지금과 같은 모듈 상수를 만든다. 글자는 파일 그대로(바이트 동일, newline="" 로 쓴 LF 전용 파일) —
.format() 자리표시(`{question}` 등)는 지금처럼 호출부가 채운다. 글자를 바꾸면 프롬프트 지문이
바뀜 — 캐시 열쇠(prompt_id·VLM det_key)는 글자 해시라 안전(글자가 같으면 불변).

찾는 순서: ① 패키지에 지시문 1개뿐이면 `prompt.md`(prompt_id 무관) ② 여러 개면
`<prompt_id>.md`(research_decompose 등) ③ `prompts/<prompt_id>.md`(폴백). 글자는
바이트 그대로 읽는다(캐시 열쇠가 글자 해시).

공용 꼬리(인젝션 방어) — 템플릿 글자 **맨 끝**(자리표시를 아직 안 채운 상태, 호출부의 `.format()`은
이 함수가 돌려준 뒤에 호출부가 함)에 `dev/agents/_common/tail.md`(또는 `agent.json`의 `common_tail`에 따라
`tail_free.md`·생략)를 붙여서 돌려준다. 꼬리 글자에는 중괄호가 없어 `.format()`과 충돌하지 않는다. 이 꼬리가
붙은 뒤의 글자가 곧 패키지 지문·LLM 캐시 열쇠에 들어가는 실제 글자(지시문 글자 변경 = 결정성 변경, 재빌드+재평가 필요).

대부분의 호출부는 `load()` 하나만 쓴다(템플릿 안의 `.format()` 자리표시가 자료가 들어갈 자리라 꼬리는 그
자리표시보다 뒤에 남는다 — 자리표시는 값만 바뀌고 글자 위치는 안 바뀌므로). **문자열 이어붙이기로 자료를
템플릿 뒤에 붙이는 소수의 호출부**(value_choice·figure_judge·parse_agent — 자리표시가 아니라 `+` 연결)는
`load()`를 쓰면 안 된다 — 꼬리가 이미 템플릿 끝에 붙어 있어 그 뒤에 자료를 또 이어붙이면 꼬리가 자료보다
**앞**에 와 버려 샌드위치(자료 → 꼬리) 순서가 깨진다. 이 호출부는 대신 `template()`(꼬리 없음) + 자기
자료 + `tail(agent_id)`(맨 끝)를 직접 쓴다.

프로세스 캐시(파일을 매 호출 때 다시 읽지 않음) — 지금 모듈 상수와 같은 생애주기(프로세스 재시작 전엔 안 바뀜).
사용: python common/agent_prompts.py (자기 점검)
"""

import json
import threading

from common.core.paths import RES_ROOT, resolve_agent_dir

_cache: dict = {}
_lock = threading.Lock()


def _resolve(agent_id, prompt_id):
    base = resolve_agent_dir(agent_id)
    single = base / "prompt.md"
    if single.exists():
        return single
    named = base / f"{prompt_id}.md"
    if named.exists():
        return named
    return base / "prompts" / f"{prompt_id}.md"  # 폴백 경로


def _template_locked(agent_id, prompt_id):
    key = ("template", agent_id, prompt_id)
    text = _cache.get(key)
    if text is None:
        text = _cache[key] = _resolve(agent_id, prompt_id).read_text(encoding="utf-8")
    return text


def _tail_variant_locked(agent_id):
    """agent.json의 common_tail 칸(기본 True)."""
    key = ("tail_variant", agent_id)
    if key in _cache:
        return _cache[key]
    manifest = json.loads((resolve_agent_dir(agent_id) / "agent.json").read_text(encoding="utf-8"))
    variant = _cache[key] = manifest.get("common_tail", True)
    return variant


def _tail_text_locked(variant):
    if not variant:
        return ""
    name = "tail_free.md" if variant == "free_text" else "tail.md"
    key = ("tail_text", name)
    text = _cache.get(key)
    if text is None:
        text = _cache[key] = (RES_ROOT / "prompts" / "common" / "_common" / name).read_text(encoding="utf-8")
    return text


def template(agent_id, prompt_id):
    """꼬리 없는 템플릿 글자만 — 문자열 이어붙이기로 자료를 붙이는 호출부 전용(위 모듈 설명). 자리표시로 자료를
    채우는 보통의 호출부는 이 함수 대신 load()를 쓴다."""
    with _lock:
        return _template_locked(agent_id, prompt_id)


def tail(agent_id):
    """해당 패키지의 공용 꼬리 글자(agent.json common_tail 칸에 따라 tail.md·tail_free.md·빈 글자) — template()과
    짝 호출(위 모듈 설명)."""
    with _lock:
        return _tail_text_locked(_tail_variant_locked(agent_id))


def load(agent_id, prompt_id):
    """dev/agents/<agent_id>/prompt.md(1개) 또는 <prompt_id>.md(여러 개)의 글자 + 공용 꼬리(위 설명) —
    둘 다 없으면 prompts/<prompt_id>.md로 폴백(한 번 읽으면 프로세스 안에서 재사용)."""
    key = ("load", agent_id, prompt_id)
    with _lock:
        text = _cache.get(key)
        if text is None:
            text = _cache[key] = _template_locked(agent_id, prompt_id) + _tail_text_locked(_tail_variant_locked(agent_id))
        return text
