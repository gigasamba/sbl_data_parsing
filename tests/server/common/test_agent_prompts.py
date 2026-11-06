"""common.ai.agent_prompts 자기 점검 — 파일 읽기·프로세스 캐시·공용 꼬리."""

from common.ai.agent_prompts import load, tail, template


def selftest():
    text = load("nested_figure", "bbox")  # JSON 출력 지시서
    assert text.startswith("이 쪽(전체 이미지) 안에서"), text[:50]
    assert text.rstrip().endswith("코드블록 없이)."), text[-120:]  # 공용 꼬리가 맨 끝에 붙음
    assert "[규칙 — 끝까지 지킴]" in text and "자료" in text
    assert load("nested_figure", "bbox") is text  # 프로세스 캐시 — 두 번째는 같은 객체(재읽기 없음)

    free = load("page_transcribe", "page")  # common_tail: "free_text" — 3번째 줄(JSON 형식) 빠짐
    assert "코드블록 없이" not in free and "[규칙 — 끝까지 지킴]" in free, free[-200:]

    # 문자열 이어붙이기 호출부용 짝 함수 — template()에는 꼬리가 없고, tail()을 맨 끝에 붙이면
    # load()와 같은 글자가 된다(이 prompt_id는 .format() 자리표시가 없어 load() == template()+tail() 그대로).
    t, tl = template("nested_figure", "bbox"), tail("nested_figure")
    assert tl and not t.endswith(tl)
    assert t + tl == load("nested_figure", "bbox")
    print("[selftest] agent_prompts.load() — 파일 읽기·프로세스 캐시·공용 꼬리(ADK14 P1, 기본·free_text·template/tail 짝) 통과")


def test_main():
    selftest()
