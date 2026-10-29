"""pipeline.eval.parse_shadow 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.parse_shadow --selftest`."""

import json
from pathlib import Path

from pipeline import config as pc
from pipeline.eval.parse_shadow import iter_rep_docs, main, run


def selftest():
    import tempfile

    d = Path(tempfile.mkdtemp())
    rep_dir, out_dir = d / "_rep", d / "_shadow"
    rep_dir.mkdir()

    decisions_a = [{"step": "engine_scope", "choice": "all", "reason": "형식별 전부", "inputs": {}}]
    (rep_dir / "docA.json").write_text(json.dumps({"context": {"format": ".txt", "page": []}, "decisions": decisions_a}), encoding="utf-8")
    decisions_b = [{"step": "figures", "choice": "3건", "reason": "상한 안 걸림", "inputs": {}}]
    (rep_dir / "docB.json").write_text(
        json.dumps({"context": {"format": ".pdf_text", "page": []}, "decisions": decisions_b}), encoding="utf-8"
    )
    (rep_dir / "docC.json").write_text(json.dumps({"text": "PARSE_CONTEXT 꺼진 문서 — context·decisions 없음"}), encoding="utf-8")
    (rep_dir / "index.json").write_text("[]", encoding="utf-8")  # represent()가 같이 쓰는 목록 파일 — 문서로 안 셈

    docs = dict(iter_rep_docs(rep_dir))
    assert set(docs) == {"docA", "docB"}  # docC(PA0 꺼짐)·index.json은 빠짐
    print("[selftest] iter_rep_docs — PA0 켜진 문서만(context·decisions 둘 다), index.json 제외 통과")

    # --mode rules — LLM 호출 0, 전부 keep, 파일 그대로 기록
    summary_rules = run(rep_dir, out_dir, mode="rules")
    assert summary_rules["docs"] == 2 and summary_rules["mode"] == "rules"
    assert summary_rules["steps"]["engine_scope"] == {"agree": 1, "disagree": 0, "examples": []}
    saved_a = json.loads((out_dir / "docA.json").read_text(encoding="utf-8"))
    assert saved_a["proposals"] == [
        {"step": "engine_scope", "action": "keep", "reason": "규칙 그대로(모델 미사용 — rules-only 모드)", "confidence": 1.0}
    ]
    print("[selftest] run(mode=rules) — LLM 0회, 문서별 파일 + summary.json 집계(전부 동의) 통과")

    # --mode llm — 가짜 LLM(결정적, figures에서 규칙과 다름) 주입 — 네트워크 0
    def _fake(prompt):
        if '"step": "figures"' in prompt:  # payload(JSON) 안에서 실제로 이 문서의 decisions에 figures가 있을 때만
            # (프롬프트 고정 설명부는 모든 step 이름을 늘 담고 있어 "figures" 단독 검사로는 못 가림)
            return json.dumps({"proposals": [{"step": "figures", "action": "raise_cap", "reason": "변환 실패 2건", "confidence": 0.6}]})
        return json.dumps({"proposals": [{"step": "engine_scope", "action": "keep", "reason": "충분", "confidence": 0.8}]})

    summary_llm = run(rep_dir, out_dir, mode="llm", llm_complete=_fake)
    assert summary_llm["steps"]["engine_scope"]["agree"] == 1
    assert summary_llm["steps"]["figures"]["disagree"] == 1
    ex = summary_llm["steps"]["figures"]["examples"][0]
    assert ex["doc"] == "docB" and ex["action"] == "raise_cap" and ex["rule_choice"] == "3건"
    print("[selftest] run(mode=llm, 가짜 LLM) — 알려진 step(figures)에서 규칙과 불일치 집계·예시 기록 통과")

    # max_docs 상한
    summary_cap = run(rep_dir, out_dir, mode="rules", max_docs=1)
    assert summary_cap["docs"] == 1
    print("[selftest] run — max_docs 상한 통과")

    # PARSE_SHADOW 게이트 — =0이면 main()이 아무것도 안 씀, --force면 씀
    out_dir2 = d / "_shadow2"
    with pc.PIPE.env(PARSE_SHADOW="0"):  # S7c — 설정 객체에 겹쳐 씀(os.environ 안 건드림 — shadow.on()이 객체로 읽음, represent 묶음 전환)
        r = main(["--rep-dir", str(rep_dir), "--out", str(out_dir2), "--mode", "rules"])
        assert r is None and not out_dir2.exists()
        main(["--rep-dir", str(rep_dir), "--out", str(out_dir2), "--mode", "rules", "--force"])
        assert (out_dir2 / "summary.json").exists()
    print("[selftest] PARSE_SHADOW 게이트 — =0이면 아무것도 안 씀·--force 무시 통과")

    out_dir3 = d / "_shadow3"
    with pc.PIPE.env(PARSE_SHADOW=None):  # 기본(미설정) = 꺼짐(구조 개편 v4 step1) — S7c: 설정 객체
        r3 = main(["--rep-dir", str(rep_dir), "--out", str(out_dir3), "--mode", "rules"])
    assert r3 is None and not out_dir3.exists()
    print("[selftest] PARSE_SHADOW 기본 꺼짐(미설정) — main()이 아무것도 안 씀 통과")

    out_dir4 = d / "_shadow4"
    with pc.PIPE.env(PARSE_SHADOW="1"):  # S7c — 설정 객체
        main(["--rep-dir", str(rep_dir), "--out", str(out_dir4), "--mode", "rules"])
        assert (out_dir4 / "summary.json").exists()
    print("[selftest] PARSE_SHADOW=1 — main()이 동작 통과")


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    selftest()
