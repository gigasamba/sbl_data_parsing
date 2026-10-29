"""pipeline.transform.represent.parse_agent 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.represent.parse_agent --selftest`."""

import json
from pathlib import Path

from common.config.settings import COMMON
from pipeline.transform.represent.parse_agent import main


def selftest():
    import tempfile

    d = Path(tempfile.mkdtemp())
    doc_path = d / "a.txt"
    doc_path.write_text("고객: 홍길동\n계약 번호: A-1\n", encoding="utf-8")

    off1 = main([str(doc_path), "--mode", "off", "--out", str(d / "off1"), "--parse-dir", str(d / "parse")])
    off2 = main([str(doc_path), "--mode", "off", "--out", str(d / "off2"), "--parse-dir", str(d / "parse")])

    # 지금 규칙은 결정적 — 두 번 돌려도 같은 제안(설계 §0). 어느 엔진을 고르는지는 설치된 엔진 구성에 따라 다름
    # (10-15 — PC .venv=plaintext, 이미지=markitdown: 이미지에만 있는 엔진이 교차 확인 계열 수를 바꿈) → 결정성만 확인
    # S6b(사용자 10-27) — 소요 초 post_times(10-22)는 비교에서 뺀다: 이미지(PYTHONDONTWRITEBYTECODE=1)는 첫 실행만 import가 느려 0.01 ≠ 0.0
    def no_times(o):
        if isinstance(o, dict):
            return {k: no_times(v) for k, v in o.items() if k != "post_times"}
        return [no_times(v) for v in o] if isinstance(o, list) else o

    assert no_times(off1) == no_times(off2) and off1["engine"], (off1, off2)
    assert no_times(json.loads((d / "off1" / "rep.json").read_text(encoding="utf-8"))) == no_times(
        json.loads((d / "off2" / "rep.json").read_text(encoding="utf-8"))
    )

    try:
        main([str(doc_path), "--mode", "on"])
        raise AssertionError("--mode on인데 거부 안 됨")
    except SystemExit as ex:
        assert "거부" in str(ex)

    # shadow — LLM_FAKE로 네트워크 0(run_agent의 role=llm·LLM_FAKE=1 단락 경로, 도구 호출은 없지만 CLI 왕복·기록은 본다).
    # 도구 호출 궤적 자체(허용 밖 도구 거부·예산 초과)는 dev_tools/unit_test/platform/test_parse_agent_pipeline.py가 ScriptedModel로 본다.
    with COMMON.env(LLM_FAKE="1"):  # S7c — 설정 객체만 바꿔 끼움(adk가 객체로 읽음)
        shadow = main([str(doc_path), "--mode", "shadow", "--out", str(d / "shadow1"), "--parse-dir", str(d / "parse")])
    assert no_times(shadow) == no_times(off1)  # shadow의 규칙 실행 부분은 off와 바이트 동일(에이전트 제안은 별도 기록일 뿐)
    shadow_log = d / "parse" / "_agent" / "shadow.jsonl"  # --parse-dir 아래(공유 rag_out()/parse가 아님)
    rows = [json.loads(ln) for ln in shadow_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert rows and rows[-1]["usage"]["fake"] is True and no_times(rows[-1]["rule_proposal"]) == no_times(off1)

    print("[selftest] off 결정적(두 번 같음) · on 거부 · shadow(LLM_FAKE) 규칙 부분이 off와 바이트 동일·기록 확인 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
