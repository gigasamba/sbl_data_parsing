"""common.ai.agent_prompts 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.ai.agent_prompts`."""

from common.ai.agent_prompts import load, tail, template


def selftest():
    text = load("research_judge", "judge")
    assert text.startswith("너는 근거 판정자다"), text[:50]
    assert "{ask}" in text and "{snippets}" in text
    assert text.rstrip().endswith("코드블록 없이)."), text[-120:]  # 공용 꼬리(ADK14 P1)가 맨 끝에 붙음
    assert "[규칙 — 끝까지 지킴]" in text and "자료" in text
    assert load("research_judge", "judge") is text  # 프로세스 캐시 — 두 번째는 같은 객체(재읽기 없음)

    free = load("doc_summary", "summary")  # common_tail: "free_text" — 3번째 줄(JSON 형식) 빠짐
    assert "코드블록 없이" not in free and "[규칙 — 끝까지 지킴]" in free, free[-200:]

    # 문자열 이어붙이기 호출부(value_choice 등)용 짝 함수 — template()에는 꼬리가 없고, tail()을 맨 끝에 붙이면
    # load()와 같은 글자가 된다(이 prompt_id는 .format() 자리표시가 없어 load() == template()+tail() 그대로).
    t, tl = template("value_choice", "choose"), tail("value_choice")
    assert tl and not t.endswith(tl)
    assert t + tl == load("value_choice", "choose")
    print("[selftest] agent_prompts.load() — 파일 읽기·프로세스 캐시·공용 꼬리(ADK14 P1, 기본·free_text·template/tail 짝) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
