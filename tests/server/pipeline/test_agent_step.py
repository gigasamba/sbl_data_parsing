"""pipeline.transform.represent.agent_step 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.represent.agent_step`."""

import copy
import json
import time
from pathlib import Path
from unittest import mock

import pipeline.transform.represent.agent_step as M
from common.config import settings as C
from pipeline import config as pc
from pipeline.transform.represent import reread as reread_mod
from pipeline.transform.represent import reread_stage3 as p3_mod
from pipeline.transform.represent.agent_step import (
    AGENT_ID,
    MAX_DOCS,
    MODES,
    NEAR_MARGIN,
    VLM_MAX,
    _session_sec,
    fake_policy,
    figure_pending,
    mode,
    model_mode,
    session_tools,
    step,
)


def selftest():
    import tempfile

    import fitz

    with pc.PIPE.env(PARSE_AGENT=None, PARSE_AGENT_FAKE=None):  # S7c — 설정 객체만 바꿔 끼움
        assert mode() == "shadow" and mode("0") == "off" and mode("on") == "apply" and mode("APPLY") == "apply"
        try:
            mode("yes")
            raise AssertionError("모르는 PARSE_AGENT 값인데 통과")
        except ValueError:
            pass
    print("[selftest] mode() — 기본 shadow·=0 off·on→apply·모르는 값 거부 통과")

    # RV4 — 세션 시간 상한 기본 180초(옛 agent.json 120 — 실 GLM 7턴 ≈115초가 닿은 실측), PARSE_AGENT_SESSION_SEC로 덮어씀
    with pc.PIPE.env(PARSE_AGENT_SESSION_SEC=None):  # S7c — 설정 객체만 바꿔 끼움
        assert _session_sec(AGENT_ID) == 180.0
    with pc.PIPE.env(PARSE_AGENT_SESSION_SEC="45"):
        assert _session_sec(AGENT_ID) == 45.0
    print("[selftest] _session_sec — 기본 180초·PARSE_AGENT_SESSION_SEC 덮어쓰기 통과")

    d = Path(tempfile.mkdtemp())
    pdf = d / "a.pdf"
    doc = fitz.open()
    doc.new_page(width=300, height=200).insert_text((20, 40), "단가: 430.000")
    doc.save(pdf)
    doc.close()
    engine_docs = {
        "pymupdf": {"facts": [{"context": ["단가"], "value": "430.000"}]},
        "rapidocr_ko": {"facts": [{"context": ["단가"], "value": "430,000"}]},
    }

    def base_rep():
        return {
            "text": "단가: 430.000",
            "rep": {"format": ".pdf_text"},
            "post": {"figures": 1},
            "fused": {
                "facts": [
                    {
                        "context": ["단가"],
                        "value": "430.000",
                        "engines": ["pymupdf"],
                        "score": 3.5,
                        "unverified": True,
                        "reread": {"page": 1, "bbox": [20, 30, 120, 45], "matched": False},
                    }
                ],
                "conflicts": [
                    {
                        "label": "단가",
                        "winner": "430.000",
                        "winner_engines": ["pymupdf"],
                        "losers": [{"engines": ["rapidocr_ko"], "text": "430,000", "score": 1.0}],
                    }
                ],
                "reread": {"attempted": 1, "p3": {"attempted": 1}},
            },
        }

    def vlm_sees(answer):
        return lambda png, cands, ctx: json.dumps({"answer": answer}, ensure_ascii=False)

    def ocr_sees(text):
        return lambda png: text

    with C.COMMON.env(LLM_FAKE="1"):  # S7c — 설정 객체만 바꿔 끼움(adk가 객체로 읽음)
        # 트리거 없음 — unverified 없는 rep은 세 모드 모두 None·rep 그대로
        r0 = base_rep()
        r0["fused"]["facts"][0]["unverified"] = False
        snap = json.dumps(r0, sort_keys=True)
        for m in MODES:
            assert step(r0, "a.pdf", pdf, engine_docs, "pymupdf", d / "parse", agent_mode=m, policy=fake_policy) is None
        assert json.dumps(r0, sort_keys=True) == snap
        print("[selftest] 트리거 없음 — off·shadow·apply 모두 세션 안 엶·rep 불변 통과")

        # off — 트리거가 있어도 아무것도 안 씀
        r_off = base_rep()
        snap = json.dumps(r_off, sort_keys=True)
        assert step(r_off, "a.pdf", pdf, engine_docs, "pymupdf", d / "parse", agent_mode="off", policy=fake_policy) is None
        assert json.dumps(r_off, sort_keys=True) == snap and not (d / "parse" / "_agent").exists()

        # shadow — 세션은 끝까지 돌지만 rep 바이트 동일, 기록은 _agent/decisions/에만
        r_sh = base_rep()
        snap = json.dumps(r_sh, sort_keys=True)
        rec = step(
            r_sh, "a.pdf", pdf, engine_docs, "pymupdf", d / "parse", agent_mode="shadow", policy=fake_policy, vlm_fn=vlm_sees("430,000")
        )
        assert json.dumps(r_sh, sort_keys=True) == snap, "shadow가 rep을 바꿈"
        assert rec["status"] == "finished" and not rec["applied"] and rec["decisions"]["0"]["action"] == "adopt"
        assert [t["tool"] for t in rec["trajectory"]] == ["list_fragments", "reread_fragment", "decide_fragment", "finish"]
        assert rec["usage"]["model_calls"] == 5 and rec["usage"]["tool_calls"] == 4 and rec["vlm_calls"] == 1
        assert json.loads((d / "parse" / "_agent" / "decisions" / "a.pdf.json").read_text(encoding="utf-8"))["status"] == "finished"
        print("[selftest] shadow — 가짜 정책 세션 완주(궤적 4단계)·rep 바이트 동일·기록은 _agent/decisions/에만 통과")

        # apply — 같은 세션이 rep.fused에 반영(값 맞바꿈·conflicts 갱신)·rep.agent 기록
        r_ap = base_rep()
        rec = step(
            r_ap, "a.pdf", pdf, engine_docs, "pymupdf", d / "parse", agent_mode="apply", policy=fake_policy, vlm_fn=vlm_sees("430,000")
        )
        f = r_ap["fused"]["facts"][0]
        assert rec["applied"] and f["value"] == "430,000" and f["unverified"] is False and f["agent"]["was"] == "430.000"
        assert r_ap["fused"]["conflicts"][0]["winner"] == "430,000" and r_ap["agent"]["status"] == "finished"
        print("[selftest] apply — 가짜 LLM·VLM로 끝까지: 근거 있는 후보 채택·conflicts 갱신·rep.agent 기록 통과")

        # 루프 재진입(10-08 기능 시험 ① 실측 멈춤) — 실 VLM 경로처럼 도구 안에서 adk 공용 루프에 일을 넣고 기다려도 끝나야 함
        import asyncio
        import threading

        from common.ai import adk as A

        def vlm_reenter(png, cands, ctx):
            return A._run_async(asyncio.sleep(0, result=json.dumps({"answer": "430,000"})))

        box = {}
        th = threading.Thread(
            target=lambda: box.update(
                rec=step(
                    base_rep(),
                    "a.pdf",
                    pdf,
                    engine_docs,
                    "pymupdf",
                    d / "parse",
                    agent_mode="apply",
                    policy=fake_policy,
                    vlm_fn=vlm_reenter,
                )
            ),
            daemon=True,
        )
        th.start()
        th.join(60)
        assert not th.is_alive(), "도구 안 adk 루프 재진입으로 세션이 멈춤(_off_loop 회귀)"
        assert box["rec"]["status"] == "finished" and box["rec"]["applied"]
        print("[selftest] 도구 안 adk 공용 루프 재진입(실 VLM 경로 모양) — 멈추지 않고 완주 통과")

        # 되돌이 — VLM이 NONE이면 다른 방법(ocr_page)으로 돌아가 맞힘
        r_bl = base_rep()
        rec = step(
            r_bl,
            "a.pdf",
            pdf,
            engine_docs,
            "pymupdf",
            d / "parse",
            agent_mode="apply",
            policy=fake_policy,
            vlm_fn=vlm_sees("NONE"),
            ocr_fn=ocr_sees("단가: 430,000"),
        )
        assert [t["tool"] for t in rec["trajectory"]] == [
            "list_fragments",
            "reread_fragment",
            "reread_fragment",
            "decide_fragment",
            "finish",
        ]
        assert rec["rereads"]["0"][0]["method"] == "vlm_context" and rec["rereads"]["0"][1]["method"] == "ocr_page"
        assert r_bl["fused"]["facts"][0]["value"] == "430,000" and r_bl["fused"]["facts"][0]["agent"]["method"] == "ocr_page"
        print("[selftest] 되돌이 — vlm_context 실패 → ocr_page로 되돌아가 채택(조각당 2회) 통과")

        # D11 — 두 번 다 못 맞히면 human(사람 확인 꼬리표), 값은 규칙 그대로
        r_h = base_rep()
        rec = step(
            r_h,
            "a.pdf",
            pdf,
            engine_docs,
            "pymupdf",
            d / "parse",
            agent_mode="apply",
            policy=fake_policy,
            vlm_fn=vlm_sees("NONE"),
            ocr_fn=ocr_sees("읽을 수 없음"),
        )
        f = r_h["fused"]["facts"][0]
        assert rec["decisions"]["0"]["action"] == "human" and f["needs_review"] is True and f["value"] == "430.000" and f["unverified"]
        print("[selftest] D11 — 근거 없으면 human 꼬리표·값 불변 통과")

        # 근거 없는 adopt 거부(도구 직접) · 상한
        tools, S = session_tools(
            pdf,
            copy.deepcopy(base_rep()["fused"]),
            p3_mod._candidate_groups(engine_docs, "pymupdf"),
            vlm_fn=vlm_sees("NONE"),
            ocr_fn=ocr_sees("x"),
        )
        assert tools["decide_fragment"](0, "adopt", "430,000")["error"].startswith("근거 없음")
        tools["reread_fragment"](0, "ocr_page")
        assert tools["reread_fragment"](0, "ocr_page")["repeat"] is True  # 같은 방법 = 재사용(횟수 안 셈)
        tools["reread_fragment"](0, "vlm_choice")
        assert "되돌이 상한" in tools["reread_fragment"](0, "vlm_context")["error"]
        assert "조각 9 없음" in tools["reread_fragment"](9, "ocr_page")["error"]
        tools, S = session_tools(
            pdf, copy.deepcopy(base_rep()["fused"]), p3_mod._candidate_groups(engine_docs, "pymupdf"), ocr_fn=ocr_sees("단가: 430,000")
        )
        S["close"]()  # 시간 초과 뒤 늦게 부른 도구
        assert "세션 종료 뒤" in tools["reread_fragment"](0, "ocr_page")["error"] and not S["rereads"] and not S["evidence"]
        assert not tools["decide_fragment"](0, "keep")["ok"] and not tools["finish"]("x")["ok"] and S["finished"] is None

        # 동시 도구 호출(engine-qa 10-08 MAJOR — ADK가 한 응답의 tool_call을 asyncio.gather로 동시에, 도구는 to_thread)
        def _two(fn_a, fn_b):
            bar, res = threading.Barrier(2), [None, None]

            def run(i, fn):
                bar.wait()
                res[i] = fn()

            ts = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate((fn_a, fn_b))]
            [t.start() for t in ts]
            [t.join(30) for t in ts]
            return res

        # 검사(예산 남음?)와 차감 사이를 일부러 넓힘 — 실 VLM 경로의 _vlm_configured()가 그 사이에 있다. lock이 없으면
        # 두 스레드가 둘 다 '남음'을 보고 둘 다 차감(VLM_MAX+1)해 이 시험이 실패한다(lock을 빼고 실패 확인함).
        def _slow_configured():  # 0.3초 쉰 뒤 True(시험용 가짜)
            time.sleep(0.3)
            return True

        with (
            mock.patch.object(M, "_vlm_configured", _slow_configured),
            mock.patch.object(M, "_vlm_pick", lambda png, cands, method, context, vlm_fn: (None, False)),
        ):
            tools, S = session_tools(pdf, copy.deepcopy(base_rep()["fused"]), p3_mod._candidate_groups(engine_docs, "pymupdf"))
            S["vlm_calls"] = VLM_MAX - 1  # VLM 예산 1회 남음
            res = _two(lambda: tools["reread_fragment"](0, "vlm_context"), lambda: tools["reread_fragment"](0, "vlm_choice"))
        assert S["vlm_calls"] == VLM_MAX and sum(1 for r in res if "VLM 예산 소진" in (r.get("error") or "")) == 1, (S["vlm_calls"], res)
        assert len(S["rereads"][0]) == 1 and "pending" not in S["rereads"][0][0]  # 차감·이력 한 번씩만

        def slow_ocr(png):
            time.sleep(0.3)
            return "단가: 430,000"

        tools, S = session_tools(pdf, copy.deepcopy(base_rep()["fused"]), p3_mod._candidate_groups(engine_docs, "pymupdf"), ocr_fn=slow_ocr)
        res = _two(lambda: tools["reread_fragment"](0, "ocr_page"), lambda: tools["reread_fragment"](0, "ocr_page"))
        assert sorted(bool(r.get("matched")) for r in res) == [False, True] and len(S["rereads"][0]) == 1, res
        assert any("읽는 중" in (r.get("error") or "") for r in res)

        gate = threading.Event()

        def held_vlm(png, cands, ctx):
            gate.wait(10)
            return json.dumps({"answer": "430,000"})

        tools, S = session_tools(pdf, copy.deepcopy(base_rep()["fused"]), p3_mod._candidate_groups(engine_docs, "pymupdf"), vlm_fn=held_vlm)
        box = {}
        th = threading.Thread(target=lambda: box.update(r=tools["reread_fragment"](0, "vlm_choice")))
        th.start()
        time.sleep(0.2)
        S["close"]()  # 읽는 도중 세션 종료
        gate.set()
        th.join(10)
        assert "세션 종료 뒤 결과" in box["r"]["error"] and not S["rereads"][0] and not S["evidence"]
        assert "세션 종료 뒤" in tools["reread_fragment"](0, "ocr_page")["error"]
        print("[selftest] 동시 도구 호출 — VLM 예산 한 번만 차감·같은 방법 동시 호출 하나만·닫힌 뒤(진행 중 포함) 결과 버림 통과")
        print("[selftest] 근거 없는 adopt 거부·같은 방법 재사용·되돌이 상한·없는 조각 통과")

        # 예산 초과 → 규칙 복귀 — 같은 도구만 되풀이하는 정책은 LLM 호출 상한(8)에서 '예산 초과'로 끝남 → 적용 안 함
        r_b = base_rep()
        snap = json.dumps(r_b["fused"], sort_keys=True)
        rec = step(
            r_b,
            "a.pdf",
            pdf,
            engine_docs,
            "pymupdf",
            d / "parse",
            agent_mode="apply",
            policy=lambda results: ("call", "list_fragments", {}),
            vlm_fn=vlm_sees("430,000"),
        )
        assert rec["status"] == "budget" and not rec["applied"] and rec["usage"]["model_calls"] == 8
        assert json.dumps(r_b["fused"], sort_keys=True) == snap and r_b["agent"]["status"] == "budget"
        # finish 없이 글자로 끝남 → 적용 안 함
        r_n = base_rep()
        rec = step(
            r_n,
            "a.pdf",
            pdf,
            engine_docs,
            "pymupdf",
            d / "parse",
            agent_mode="apply",
            policy=lambda results: ("text", "끝"),
            vlm_fn=vlm_sees("430,000"),
        )
        assert rec["status"] == "no_finish" and not rec["applied"] and r_n["fused"]["facts"][0]["value"] == "430.000"
        # 공유 호출 상한(GH1-08b 턴 단위 거부) → 'call_cap'으로 기록(no_finish와 구분) · 적용 안 함
        _orig_rs = M._run_session
        M._run_session = lambda *a_, **k_: ("공유 호출 상한", [], {})
        try:
            r_c = base_rep()
            rec = step(
                r_c,
                "a.pdf",
                pdf,
                engine_docs,
                "pymupdf",
                d / "parse",
                agent_mode="apply",
                policy=lambda results: ("text", "끝"),
                vlm_fn=vlm_sees("430,000"),
            )
            assert rec["status"] == "call_cap" and not rec["applied"], rec["status"]
        finally:
            M._run_session = _orig_rs
        # 토큰 예산(ADK2 콜백) — 상한을 낮추면 첫 도구 호출 전에 PlatformError → 'budget'·적용 안 함
        saved_tok, M.TOKENS_MAX = M.TOKENS_MAX, 50
        try:
            r_t = base_rep()
            rec = step(
                r_t, "a.pdf", pdf, engine_docs, "pymupdf", d / "parse", agent_mode="apply", policy=fake_policy, vlm_fn=vlm_sees("430,000")
            )
        finally:
            M.TOKENS_MAX = saved_tok
        assert rec["status"] == "budget" and "token budget" in rec["error"] and not rec["applied"]
        assert r_t["fused"]["facts"][0]["value"] == "430.000"
        print("[selftest] 예산 초과(LLM 8회·토큰 상한)·finish 없음 → 결정 버리고 규칙 결과 유지 통과")

        # 3단계 (a) 근소 조각 — unverified 아님 + split·heuristic + 점수 차 ≤ 문턱 → 세션 대상(P2가 쪽을 안 남겼으면 자리 찾기)
        def near_rep(gap):
            r = base_rep()
            f = r["fused"]["facts"][0]
            f.pop("unverified"), f.pop("reread")
            f["score"] = 3.0 + gap
            r["fused"]["conflicts"][0].update(split=True, resolved_by="heuristic")
            r["fused"]["conflicts"][0]["losers"][0]["score"] = 3.0
            return r

        r_nr = near_rep(0.05)
        snap = json.dumps(r_nr, sort_keys=True)
        rec = step(
            r_nr, "a.pdf", pdf, engine_docs, "pymupdf", d / "parse", agent_mode="shadow", policy=fake_policy, vlm_fn=vlm_sees("430,000")
        )
        assert json.dumps(r_nr, sort_keys=True) == snap and rec["trigger"]["near"] == 1 and rec["status"] == "finished"
        assert rec["decisions"]["0"]["action"] == "adopt" and rec["decisions"]["0"]["value"] == "430,000"
        assert rec["rereads"]["0"][0]["method"] == "vlm_context"  # P2 이력 없음 → tried 비어 첫 방법부터
        assert (
            step(near_rep(NEAR_MARGIN + 1), "a.pdf", pdf, engine_docs, "pymupdf", d / "parse", agent_mode="apply", policy=fake_policy)
            is None
        )  # 점수 차가 문턱보다 큼 — 트리거 아님
        r_trust = near_rep(0.05)
        r_trust["fused"]["conflicts"][0]["resolved_by"] = "trust"
        assert step(r_trust, "a.pdf", pdf, engine_docs, "pymupdf", d / "parse", agent_mode="apply", policy=fake_policy) is None
        M.NEAR_ON = False
        try:
            assert step(near_rep(0.05), "a.pdf", pdf, engine_docs, "pymupdf", d / "parse", agent_mode="apply", policy=fake_policy) is None
        finally:
            M.NEAR_ON = True
        print("[selftest] 3단계 (a) 근소 조각 — split·heuristic·문턱 이하만 세션(자리 찾기)·trust·문턱 초과·=0 끔은 안 엶 통과")

        # 3단계 (c) 그림 조각 — 그림 VLM 값 vs 본문 갈림 → 그림 PNG OCR로 다시 읽어 기록(fused 없어도)
        fig_png = d / "fig.png"
        fig_png.write_bytes(reread_mod.render_crop(pdf, 0, None))
        figs = [{"image_id": "a.pdf#p1#i0", "page": 1, "png_path": str(fig_png), "conflict": {"함량": {"그림": "59", "본문": "95"}}}]
        r_fg = {"text": "함량 95", "rep": {"format": ".pdf_text"}, "post": {"figures": 1}}
        rec = step(
            r_fg,
            "a.pdf",
            pdf,
            None,
            "pymupdf",
            d / "parse",
            agent_mode="apply",
            policy=fake_policy,
            ocr_fn=ocr_sees("그림: 함량 95 ug/mL"),
            fig_records=figs,
        )
        fc = rec["figure_checks"][0]
        assert rec["status"] == "finished" and rec["trigger"]["figure"] == 1 and "fused" not in r_fg
        assert fc["decision"] == "adopt" and fc["value"] == "95" and fc["method"] == "ocr_figure" and r_fg["agent"] is rec
        rec = step(
            {"text": "", "rep": {}, "post": {"figures": 1}},
            "a.pdf",
            pdf,
            None,
            "pymupdf",
            d / "parse",
            agent_mode="apply",
            policy=fake_policy,
            vlm_fn=vlm_sees("NONE"),
            ocr_fn=ocr_sees("x"),
            fig_records=figs,
        )
        assert [h["method"] for h in rec["rereads"]["0"]] == ["ocr_figure", "vlm_context"]
        assert rec["figure_checks"][0]["decision"] == "human" and rec["figure_checks"][0]["needs_review"]
        M.FIG_ON = False
        try:
            assert (
                step(dict(r_fg), "a.pdf", pdf, None, "pymupdf", d / "parse", agent_mode="apply", policy=fake_policy, fig_records=figs)
                is None
            )
        finally:
            M.FIG_ON = True
        tools, _S = session_tools(pdf, None, {}, fig_frags=figure_pending(figs), ocr_fn=ocr_sees("x"))
        assert "안 맞는 method" in tools["reread_fragment"](0, "ocr_band")["error"]
        print("[selftest] 3단계 (c) 그림 조각 — ocr_figure 채택·되돌이 뒤 human·=0 끔·글자 조각 방법 거부 통과")

        # 3단계 (b) PARSE_AGENT_MODEL — vlm이면 이미지 문서는 parse_decide_vlm(vlm 역할), 이미지 없으면 그대로 llm
        assert model_mode() == "split" and model_mode("VLM") == "vlm"
        try:
            model_mode("both")
            raise AssertionError("모르는 PARSE_AGENT_MODEL 값인데 통과")
        except ValueError:
            pass
        rec = step(
            base_rep(),
            "a.pdf",
            pdf,
            engine_docs,
            "pymupdf",
            d / "parse",
            agent_mode="apply",
            policy=fake_policy,
            vlm_fn=vlm_sees("430,000"),
            model="vlm",
        )
        assert rec["agent"] == "parse_decide_vlm" and rec["role"] == "vlm" and rec["applied"]
        r_ni = base_rep()
        r_ni["post"] = {}
        rec = step(
            r_ni,
            "a.pdf",
            pdf,
            engine_docs,
            "pymupdf",
            d / "parse",
            agent_mode="apply",
            policy=fake_policy,
            vlm_fn=vlm_sees("430,000"),
            model="vlm",
        )
        assert rec["agent"] == AGENT_ID and rec["role"] == "llm"
        print("[selftest] 3단계 (b) PARSE_AGENT_MODEL=vlm — 이미지 문서만 VLM 판단 세션(가짜 정책)·split 기본·모르는 값 거부 통과")

        # 시간 상한 — 다음 턴 시작 전 '지금까지 + 가장 긴 턴'으로 멈춤(세션 상한 안에서 끝남) · 배치 시간 예산
        def slow_none(png, cands, ctx):
            time.sleep(0.7)
            return json.dumps({"answer": "NONE"})

        saved_b = (M.BATCH_SEC, M._batch_spent)
        try:
            M.BATCH_SEC, M._batch_spent = 1.6, 0.0  # 세션 상한 = min(180, 남은 1.6초)
            rec = step(
                base_rep(),
                "a.pdf",
                pdf,
                engine_docs,
                "pymupdf",
                d / "parse",
                agent_mode="apply",
                policy=fake_policy,
                vlm_fn=slow_none,
                ocr_fn=lambda png: (time.sleep(0.7), "x")[1],
            )
            assert rec["status"] == "timeout" and rec["text"] == "시간 상한" and not rec["applied"], rec["status"]
            assert rec["sec"] < rec["session_sec"] and rec["session_sec"] == 1.6, (rec["sec"], rec["session_sec"])
            M._batch_spent = M.BATCH_SEC  # 배치 예산 다 씀 → 남은 문서는 세션 없이
            r_bt = base_rep()
            rec = step(r_bt, "a.pdf", pdf, engine_docs, "pymupdf", d / "parse", agent_mode="apply", policy=fake_policy)
            assert rec["status"] == "skipped" and "PARSE_AGENT_BATCH_SEC" in rec["reason"] and r_bt["fused"]["facts"][0]["unverified"]
        finally:
            M.BATCH_SEC, M._batch_spent = saved_b
        print("[selftest] 시간 상한 — 다음 턴 전 예측으로 세션 상한 안에서 멈춤(timeout·적용 안 함)·배치 예산 다 쓰면 세션 안 엶 통과")

        # 문서 수 상한
        saved = M._docs_used
        M._docs_used = MAX_DOCS
        try:
            r_m = base_rep()
            rec = step(r_m, "a.pdf", pdf, engine_docs, "pymupdf", d / "parse", agent_mode="apply", policy=fake_policy)
            assert rec["status"] == "skipped" and r_m["fused"]["facts"][0]["value"] == "430.000"
        finally:
            M._docs_used = saved
        print("[selftest] PARSE_AGENT_MAX_DOCS 상한 — 세션 안 엶 통과")

    # 모델 없음(LLM 미설정·가짜 아님) → no_model, 규칙 복귀
    with C.COMMON.env(LLM_BASE_URL=None, LLM_MODEL=None), pc.PIPE.env(PARSE_AGENT_FAKE=None):  # S7c — 설정 객체만 바꿔 끼움
        r_x = base_rep()
        rec = step(r_x, "a.pdf", pdf, engine_docs, "pymupdf", d / "parse", agent_mode="apply")
        assert rec["status"] == "no_model" and not rec["applied"] and r_x["fused"]["facts"][0]["unverified"]
    print("[selftest] 모델 없음 → no_model·규칙 결과 유지 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
