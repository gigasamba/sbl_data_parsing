"""common.ai.adk 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.ai.adk`."""

import json
import threading
import time

import common.ai.adk as M
from common.ai.adk import ModelUnavailable, _redirect_ok, _to_contents, complete, run_agent, schema_stats
from common.core.paths import resolve_agent_dir


def selftest():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from common.config.settings import COMMON

    # 메시지 변환 — 글자 + 이미지(data: base64), system 역할만 system_instruction으로 옮김(I4)
    sys_, contents = _to_contents(
        [
            {"role": "system", "content": "지시"},
            {
                "role": "user",
                "content": [{"type": "text", "text": "질문"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}],
            },
        ]
    )
    assert sys_ == "지시" and len(contents) == 1 and contents[0].role == "user" and len(contents[0].parts) == 2
    assert contents[0].parts[1].inline_data.mime_type == "image/png"
    sys2, contents2 = _to_contents([{"role": "user", "content": "그냥 질문"}])
    assert sys2 is None and contents2[0].role == "user"  # system 메시지가 없으면 옮길 것도 없음(I4)

    # BLOCKER 1(engine-qa 2026-10-06) — vLLM reasoning_content는 ADK가 thought=True Part로 끼워 넣음(실측) — 답 글자만
    # 이어붙이는 로직을 _complete_adk와 똑같이 단위 시험(모의 LlmResponse 없이 Part 리스트만으로, google.genai 실제 타입 사용).
    from google.genai import types as _T

    thought_part = _T.Part.from_text(text="생각하는 중...")
    thought_part.thought = True
    answer_part = _T.Part.from_text(text="최종 답")
    mixed = [thought_part, answer_part]
    joined = "".join(p.text or "" for p in mixed if not getattr(p, "thought", False))
    assert joined == "최종 답", joined

    # 가드 — 외부 주소 거부(require_internal이 그대로 전파, VLM 모듈이 지금도 안 잡는 것과 같게)
    with COMMON.env(VLM_ALLOW_EXTERNAL=None, VLM_BASE_URL="https://openrouter.ai/api/v1", VLM_MODEL="x"):
        try:
            complete("vlm", [{"role": "user", "content": "x"}])
            raise AssertionError("외부 주소인데 거부 안 됨")
        except RuntimeError as ex:
            assert "외부 주소" in str(ex), ex

    # NO_PAID_CALLS=1 — 외부 호출 차단(외부 허용이 있어도, require_internal은 통과하지만 precheck가 막음)
    from common.ai.guard import BudgetExceeded

    # (옛 시험은 위 블록의 VLM_BASE_URL·VLM_MODEL을 지우지 않고 이어 씀 — 같은 값을 다시 준다)
    with COMMON.env(VLM_BASE_URL="https://openrouter.ai/api/v1", VLM_MODEL="x", VLM_ALLOW_EXTERNAL="1", NO_PAID_CALLS="1"):
        try:
            complete("vlm", [{"role": "user", "content": "x"}])
            raise AssertionError("NO_PAID_CALLS인데 통과됨")
        except BudgetExceeded:
            pass
    print("[selftest] 메시지 변환(글자·이미지·system 역할 불변) · thought Part 제외(BLOCKER 1) · 외부 주소 거부 · NO_PAID_CALLS 차단 통과")

    # BLOCK(보안 독립 검토 2026-10-06) — preguarded 기본값은 항상 가드, 예외는 명시한 호출자만.
    # ① role="llm"이어도 기본값(preguarded=False)이면 외부 주소는 전송 전에 거부(cli/ping_models.py가 이 경로로 복귀 — 전환
    #    전엔 require_internal을 직접 불렀는데, llm 역할만 건너뛰게 했던 이전 설계가 ping_models의 LLM ping을 무가드로 만들었음)
    with COMMON.env(LLM_BASE_URL="https://openrouter.ai/api/v1", LLM_MODEL="x"):
        try:
            complete("llm", [{"role": "user", "content": "x"}])
            raise AssertionError("llm 역할 기본값인데 외부 주소 거부 안 됨")
        except RuntimeError as ex:
            assert "외부 주소" in str(ex), ex
    # ② preguarded=True는 common/llm.py chat()만 쓰는 예외 경로 — require_internal을 **전혀 안 부름**(이미 자기 allow_external
    #    매개변수로 통과시킨 뒤라서). require_internal을 가로채 호출 횟수로 증명(내부 주소라 어차피 통과하므로 결과만 보면 구분 안 됨).
    calls = []
    _orig_require_internal = M.require_internal

    def _spy(*a, **k):
        calls.append(a)
        return _orig_require_internal(*a, **k)

    M.require_internal = _spy

    class Ok(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            self.rfile.read(length)
            out = json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv4 = ThreadingHTTPServer(("127.0.0.1", 0), Ok)
    port4 = srv4.server_address[1]
    threading.Thread(target=srv4.serve_forever, daemon=True).start()
    try:
        with COMMON.env(LLM_BASE_URL=f"http://127.0.0.1:{port4}/v1", LLM_MODEL="mock"):
            text, _u = complete("llm", [{"role": "user", "content": "x"}], preguarded=True)
            assert text == "ok" and len(calls) == 0, calls  # require_internal이 전혀 안 불림(이미 신뢰된 호출자)
    finally:
        M.require_internal = _orig_require_internal
        srv4.shutdown()
    print("[selftest] preguarded — 기본값은 항상 가드(llm 역할도)·예외 경로만 require_internal 생략 통과")

    # http 전송 — 마지막 실패 뒤 대기 없음(재시도 2회, 둘 다 500 → sleep은 1번만)
    class Fail(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"x"}')

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fail)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with COMMON.env(VLM_BASE_URL=f"http://127.0.0.1:{port}/v1", VLM_MODEL="mock", MODEL_TRANSPORT="http"):
            slept = []
            orig_sleep = time.sleep
            time.sleep = lambda s: slept.append(s)
            try:
                try:
                    complete("vlm", [{"role": "user", "content": "x"}], retries=2)
                    raise AssertionError("500 반복인데 성공 처리됨")
                except ModelUnavailable:
                    pass
                assert len(slept) == 1, slept  # 재시도 2회 → 대기는 1번만(마지막 실패 뒤엔 안 쉼)
            finally:
                time.sleep = orig_sleep
    finally:
        srv.shutdown()
    print("[selftest] http 전송 재시도 — 마지막 실패 뒤 대기 없음(재시도 2회 → sleep 1번) 통과")

    # 리다이렉트 차단 — http 전송(guard._Redirect가 리다이렉트 대상을 다시 검사)
    class Redir(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(302)
            self.send_header("Location", "https://openrouter.ai/api/v1/chat/completions")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv2 = ThreadingHTTPServer(("127.0.0.1", 0), Redir)
    port2 = srv2.server_address[1]
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    try:
        with COMMON.env(VLM_BASE_URL=f"http://127.0.0.1:{port2}/v1", VLM_MODEL="mock", MODEL_TRANSPORT="http"):
            try:
                complete("vlm", [{"role": "user", "content": "x"}], retries=1)
                raise AssertionError("외부로 리다이렉트인데 통과됨(http 전송)")
            except RuntimeError as ex:
                assert "openrouter" in str(ex) and "리다이렉트" in str(ex), ex
    finally:
        srv2.shutdown()
    print("[selftest] http 전송 — 내부 주소의 외부 리다이렉트 차단 통과")

    # 리다이렉트 차단 — adk 전송. litellm/openai의 httpx 클라이언트는 follow_redirects=True가 기본이고(실측 확인),
    # client 생성 시점에 follow_redirects=False를 줘도 openai SDK가 매 요청마다 kwargs.setdefault("follow_redirects", True)로
    # 덮어써 무력하다(openai/_base_client.py 확인) — 그래서 httpx event_hooks(_guarded_client)로 리다이렉트 **응답 자체**를
    # 가로채 거부한다. 판단 로직(_redirect_ok)은 네트워크 없이 단위 시험 — common.guard와 같은 규칙.
    assert _redirect_ok("http://127.0.0.1:1/x", "VLM") is True  # 내부(루프백) — 그대로 따라가도 됨
    assert _redirect_ok("http://8.8.8.8/x", "VLM") is False  # 외부 + 허용 없음 — 거부
    with COMMON.env(RUN_ENV="local", VLM_ALLOW_EXTERNAL="1"):
        assert _redirect_ok("http://8.8.8.8/x", "VLM") is True  # 외부 허용 + local이면 외부도 허용
        with COMMON.env(RUN_ENV="dev"):
            assert _redirect_ok("http://8.8.8.8/x", "VLM") is False  # 서버(dev·prd)는 허용이 열려도 외부 거부(S7b — D-028 ⑧)
    print("[selftest] _redirect_ok 단위 시험(내부 허용·외부 거부·외부 허용) 통과")

    # 실제 호출 경로 — 내부 서버가 외부 주소(8.8.8.8, guard.py 자기점검과 같은 선택)로 리다이렉트하면 후킹이 요청을 끊고,
    # litellm이 밖에서 재매핑해도 _find_redirect_block이 원래 문구("…외부(8.8.8.8)로 리다이렉트…")를 체인에서 다시 꺼내
    # 올린다. 걸리는 시간이 짧게 유지되는 것(아래 10초 한도)으로도 "따라가서 네트워크가 걸렸다"를 배제(따라갔으면
    # 8.8.8.8:80 연결 시도가 수 초~타임아웃까지 걸림).
    class Redir2(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(307)
            self.send_header("Location", "http://8.8.8.8/nope")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv3 = ThreadingHTTPServer(("127.0.0.1", 0), Redir2)
    port3 = srv3.server_address[1]
    threading.Thread(target=srv3.serve_forever, daemon=True).start()
    try:
        with COMMON.env(VLM_BASE_URL=f"http://127.0.0.1:{port3}/v1", VLM_MODEL="mock", MODEL_TRANSPORT=None):
            t0 = time.perf_counter()
            try:
                complete("vlm", [{"role": "user", "content": "x"}], retries=1)
                raise AssertionError("리다이렉트인데 통과됨(adk 전송)")
            except ModelUnavailable as ex:
                assert time.perf_counter() - t0 < 10, "너무 오래 걸림 — 8.8.8.8에 실제로 연결을 시도했을 가능성"
                assert "외부(8.8.8.8)로 리다이렉트" in str(ex) and "거부" in str(ex), ex  # 원문 메시지가 재매핑을 뚫고 올라옴
    finally:
        srv3.shutdown()
    print("[selftest] adk 전송 — httpx event_hooks 리다이렉트 응답 차단(follow_redirects 무관), 실제 연결 없음(짧은 시간) 확인 통과")

    # agent=(GA2 패키지 경유) — 가짜 서버 1건: 응답 글자·usage가 agent 없는 경로와 같다(parity, I5). 역할 불일치는 바로 거부.
    class Ok2(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            self.rfile.read(length)
            out = json.dumps(
                {
                    "choices": [{"message": {"role": "assistant", "content": "에이전트 응답"}}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 3},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv5 = ThreadingHTTPServer(("127.0.0.1", 0), Ok2)
    port5 = srv5.server_address[1]
    threading.Thread(target=srv5.serve_forever, daemon=True).start()
    try:
        with COMMON.env(LLM_BASE_URL=f"http://127.0.0.1:{port5}/v1", LLM_MODEL="mock", MODEL_TRANSPORT=None):
            text_direct, usage_direct = complete("llm", [{"role": "user", "content": "X는?"}], max_tokens=10)
            text_agent, usage_agent = complete(
                "llm", [{"role": "user", "content": "X는?"}], max_tokens=10, agent="doc_summary"
            )  # 스키마 없는 에이전트 - 형식 재요청 없이 경로 동일성만
            assert text_direct == text_agent == "에이전트 응답" and usage_direct == usage_agent == {
                "prompt_tokens": 2,
                "completion_tokens": 3,
            }
            try:
                complete("llm", [{"role": "user", "content": "x"}], agent="figure_describe")  # figure_describe의 model_role=vlm
                raise AssertionError("role!=model_role인데 통과됨")
            except ModelUnavailable as ex:
                assert "model_role" in str(ex), ex
    finally:
        srv5.shutdown()
    print("[selftest] agent= — 응답·usage가 비-agent 경로와 같음(parity) · model_role 불일치 거부 통과")

    # output_schema — 형식 검사·1회 재요청(AD33 ⓑ). nested_figure(output_schema 있음, 필수 "regions" — 11-01 research_judge 지움)로:
    # ① 1차 깨진 JSON → 2차 정상 → 정상 반환·요청 2회·invalid+1·retry_ok+1 ② 둘 다 깨짐 → 마지막(2차) 응답 그대로·
    # 요청 2회·invalid+1·retry_failed+1(호출부가 그 뒤 기본값 처리) ③ 1차부터 정상 → 요청 1회·통계 불변(재요청 없음).
    def _schema_server(bodies):
        hits = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                self.rfile.read(length)
                i = len(hits)
                hits.append(1)
                text = bodies[min(i, len(bodies) - 1)]
                out = json.dumps(
                    {
                        "choices": [{"message": {"role": "assistant", "content": text}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, hits

    valid = json.dumps({"regions": []})
    srvA, hitsA = _schema_server(["이건 JSON이 아님", valid])
    try:
        with COMMON.env(VLM_BASE_URL=f"http://127.0.0.1:{srvA.server_address[1]}/v1", VLM_MODEL="mock"):
            before = schema_stats()
            text, _u = complete("vlm", [{"role": "user", "content": "x"}], agent="nested_figure")
            assert text == valid and len(hitsA) == 2, (text, hitsA)
            assert _u.get("prompt_tokens") == 2 and _u.get("completion_tokens") == 2 and _u.get("calls") == 2, (
                _u
            )  # 두 호출 합산(독립 검토 10-06)
            after = schema_stats()
            assert after["invalid"] == before["invalid"] + 1 and after["retry_ok"] == before["retry_ok"] + 1
    finally:
        srvA.shutdown()

    srvB, hitsB = _schema_server(["여전히 JSON 아님"])
    try:
        with COMMON.env(VLM_BASE_URL=f"http://127.0.0.1:{srvB.server_address[1]}/v1", VLM_MODEL="mock"):
            before = schema_stats()
            text, _u = complete("vlm", [{"role": "user", "content": "x"}], agent="nested_figure")
            assert text == "여전히 JSON 아님" and len(hitsB) == 2, (text, hitsB)  # 재요청 1회(2차도 깨짐) — 그대로 반환(호출부 기본값 처리)
            after = schema_stats()
            assert after["invalid"] == before["invalid"] + 1 and after["retry_failed"] == before["retry_failed"] + 1
    finally:
        srvB.shutdown()

    srvC, hitsC = _schema_server([valid])
    try:
        with COMMON.env(VLM_BASE_URL=f"http://127.0.0.1:{srvC.server_address[1]}/v1", VLM_MODEL="mock"):
            before = schema_stats()
            text, _u = complete("vlm", [{"role": "user", "content": "x"}], agent="nested_figure")
            assert text == valid and len(hitsC) == 1, (text, hitsC)  # 1차부터 정상 — 재요청 없음(호출 1회)
            assert schema_stats() == before
    finally:
        srvC.shutdown()
    print(
        "[selftest] output_schema — 1차 깨짐→2차 정상(재요청 1회·invalid+retry_ok) · 둘 다 깨짐(retry_failed) · 1차부터 정상(재요청 0) 통과"
    )

    # RV16 — 직접 호출자(agent=, call_reserved=False — post/vlm_page.py 등이 쓰는 모양)는 common/llm.chat()의 RV12
    # 빈 응답 안전망 밖이었다. page_transcribe(output_schema 없음, vlm_page.py가 실제로 쓰는 패키지)로: ① 1차가 빈
    # 응답(토큰 소모)→4배 max_tokens로 딱 한 번 재요청→성공(요청 2회·공유 장부 2건=counted) ② 재요청도 빈 응답이면
    # 그대로 반환(요청 2회에서 끝 — 무한 재시도 없음) ③ call_reserved=True(chat()이 이미 자기 안전망을 가진 모양)는
    # 여기서 또 재요청하지 않는다(두 안전망이 겹치면 최대 4회까지 늘어나는 것을 막음).
    def _rv16_server(bodies):
        hits = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                self.rfile.read(length)
                text, ctok = bodies[min(len(hits), len(bodies) - 1)]
                hits.append(1)
                out = json.dumps(
                    {
                        "choices": [{"message": {"role": "assistant", "content": text}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": ctok},
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, hits

    from common.ai import llm as _L16

    srvD, hitsD = _rv16_server([("", 50), ("실제 답", 60)])
    try:
        with COMMON.env(VLM_BASE_URL=f"http://127.0.0.1:{srvD.server_address[1]}/v1", VLM_MODEL="mock"):
            before16 = _L16.usage()["calls"]
            text, u = complete("vlm", [{"role": "user", "content": "x"}], max_tokens=500, agent="page_transcribe")
            assert text == "실제 답" and len(hitsD) == 2, (text, hitsD)
            assert u.get("calls") == 2 and u.get("completion_tokens") == 110, u
            assert _L16.usage()["calls"] - before16 == 2, "재요청도 공유 장부(LLM_MAX_CALLS)에 집계돼야 함(counted)"
    finally:
        srvD.shutdown()

    srvE, hitsE = _rv16_server([("", 50)])  # 재요청도 빈 응답
    try:
        with COMMON.env(VLM_BASE_URL=f"http://127.0.0.1:{srvE.server_address[1]}/v1", VLM_MODEL="mock"):
            text, u = complete("vlm", [{"role": "user", "content": "x"}], max_tokens=500, agent="page_transcribe")
            assert text == "" and len(hitsE) == 2, (text, hitsE)  # 재요청 1번만 하고 그대로 반환(두 번째도 빈 응답)
    finally:
        srvE.shutdown()

    srvF, hitsF = _rv16_server([("", 50), ("실제 답", 60)])
    try:  # call_reserved=True(chat()이 이미 자기 안전망을 가진 모양) — 여기서 또 재요청하면 안 됨(겹침 방지)
        with COMMON.env(VLM_BASE_URL=f"http://127.0.0.1:{srvF.server_address[1]}/v1", VLM_MODEL="mock"):
            text, u = complete("vlm", [{"role": "user", "content": "x"}], max_tokens=500, agent="page_transcribe", call_reserved=True)
            assert text == "" and len(hitsF) == 1, (text, hitsF)
    finally:
        srvF.shutdown()
    print(
        "[selftest] RV16 — 직접 호출자(agent=) 빈 응답 1회 재요청(4배 max_tokens)·공유 장부 집계(counted) · "
        "재요청도 빈 응답이면 그대로 · call_reserved=True(chat() 자기 안전망)는 안 겹침 통과"
    )

    # agent= — 리다이렉트 차단(DONT 13). _redirect_block 상자(1차 신호)로 판정해 ① 실제 연결 0(8.8.8.8에 안 닿음·짧은 시간)
    # ② 재시도 없이 1회 시도(서버 요청 수로 확인 — retries=3을 줘도 1회만 가야 함) ③ 메시지에 "리다이렉트"·"거부"가 그대로 남는다
    # (ADK Workflow의 노드 실패 재포장이 예외 __context__를 덮어써 예전 체인 탐색만으로는 못 찾던 것 — 2026-10 보완).
    hits6 = []

    class Redir3(BaseHTTPRequestHandler):
        def do_POST(self):
            hits6.append(1)
            self.send_response(307)
            self.send_header("Location", "http://8.8.8.8/nope")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv6 = ThreadingHTTPServer(("127.0.0.1", 0), Redir3)
    port6 = srv6.server_address[1]
    threading.Thread(target=srv6.serve_forever, daemon=True).start()
    try:
        with COMMON.env(VLM_BASE_URL=f"http://127.0.0.1:{port6}/v1", VLM_MODEL="mock"):
            t1 = time.perf_counter()
            try:
                complete("vlm", [{"role": "user", "content": "x"}], retries=3, agent="page_transcribe")
                raise AssertionError("리다이렉트인데 통과됨(agent=)")
            except ModelUnavailable as ex:
                assert time.perf_counter() - t1 < 10, "너무 오래 걸림 — 8.8.8.8에 실제로 연결을 시도했을 가능성"
                assert len(hits6) == 1, f"재시도 없이 1회만 시도해야 함(재시도 대상 아님) — 실제 {len(hits6)}회"
                assert "외부(8.8.8.8)로 리다이렉트" in str(ex) and "거부" in str(ex), ex
    finally:
        srv6.shutdown()
    srv7 = ThreadingHTTPServer(("127.0.0.1", 0), Fail)
    port7 = srv7.server_address[1]
    threading.Thread(target=srv7.serve_forever, daemon=True).start()
    try:
        with COMMON.env(VLM_BASE_URL=f"http://127.0.0.1:{port7}/v1", VLM_MODEL="mock"):
            slept2 = []
            orig_sleep2 = time.sleep
            time.sleep = lambda s: slept2.append(s)
            try:
                try:
                    complete("vlm", [{"role": "user", "content": "x"}], retries=2, agent="page_transcribe")
                    raise AssertionError("500 반복인데 성공 처리됨(agent=)")
                except ModelUnavailable:
                    pass
                assert len(slept2) == 1, slept2
            finally:
                time.sleep = orig_sleep2
    finally:
        srv7.shutdown()
    print(
        "[selftest] agent= — 리다이렉트 차단(_redirect_block 상자, 실제 연결 0·재시도 없이 1회·문구 보존) · 5xx 재시도(마지막 실패 뒤 대기 없음) 통과"
    )

    try:  # 10-15 이미지 selftest — example_agentic은 dev_tools/unit_test/fixtures(PC 전용, 이미지에 없음)
        resolve_agent_dir("example_agentic")
        _have_agentic_fixture = True
    except FileNotFoundError:
        _have_agentic_fixture = False
        print("[selftest] run_agent(AG4) 묶음 건너뜀 — example_agentic 시험 패키지가 이 환경에 없음(이미지 — PC 시험 전용 fixtures)")
    if _have_agentic_fixture:
        # run_agent(AG4) — agentic:true 패키지(dev/agents/example_agentic/, local_tools=lookup·finish_hint) 경유.
        from google.genai import types as _types

        def lookup(term: str) -> dict:
            return {"term": term, "found": True}

        def finish_hint(note: str) -> dict:
            return {"note": note}

        _AGENTIC_TOOLS = {"lookup": lookup, "finish_hint": finish_hint}
        _question = _types.Content(role="user", parts=[_types.Part.from_text(text="질문")])

        # ① 외부 주소 — 모델 호출(네트워크) 전에 거부(require_internal이 그대로 전파)
        with COMMON.env(LLM_BASE_URL="https://openrouter.ai/api/v1", LLM_MODEL="x"):
            try:
                run_agent("example_agentic", _question, role="llm", tools=_AGENTIC_TOOLS)
                raise AssertionError("run_agent — 외부 주소인데 거부 안 됨")
            except RuntimeError as ex:
                assert "외부 주소" in str(ex), ex

        # ② FAKE 경로 — LLM_FAKE=1이면 네트워크 0(common/llm.chat()과 같은 모양: 입력 글자 앞 200자 + "[FAKE]")
        with COMMON.env(LLM_FAKE="1"):
            text, trajectory, usage = run_agent("example_agentic", _question, role="llm", tools=_AGENTIC_TOOLS)
            assert text == "질문[FAKE]" and trajectory == [] and usage.get("fake") is True, (text, trajectory, usage)

        # ③ 예산 공유 — common/llm.reserve_call()이 chat()·run_agent() 둘 다 쓰는 같은 장부(LLM_MAX_CALLS).
        from common.ai import llm as _L

        with COMMON.env(LLM_MAX_CALLS="1"):
            with _L._lock:
                saved_calls = _L._stats["calls"]
                _L._stats["calls"] = 0
            try:
                _L.reserve_call()  # 이 한 번이 상한을 다 씀(공유 장부) — run_agent는 네트워크를 건드리기 전에 막힘
                with COMMON.env(LLM_BASE_URL="http://127.0.0.1:1", LLM_MODEL="mock"):
                    try:
                        run_agent("example_agentic", _question, role="llm", tools=_AGENTIC_TOOLS)
                        raise AssertionError("run_agent — LLM_MAX_CALLS 공유인데 통과됨")
                    except ModelUnavailable as ex:
                        assert "LLM_MAX_CALLS" in str(ex), ex
            finally:
                with _L._lock:
                    _L._stats["calls"] = saved_calls
        print("[selftest] run_agent — 외부 주소 거부(네트워크 전) · FAKE 경로(네트워크 0) · LLM_MAX_CALLS 공유 장부 통과")

        # ④ 실제 왕복 — 모의 OpenAI 서버가 tool_calls(도구 호출) 두 번(되돌이) 뒤 글자 응답으로 끝남(백루프 포함 정상 종료).
        _agentic_hits = []
        _agentic_replies = [
            {
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": json.dumps({"term": "x"})}}
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
            {
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_2",
                                    "type": "function",
                                    "function": {"name": "finish_hint", "arguments": json.dumps({"note": "y"})},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
            {
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "최종 답"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        ]

        class AgenticMock(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                self.rfile.read(length)
                i = len(_agentic_hits)
                _agentic_hits.append(1)
                out = json.dumps(_agentic_replies[min(i, len(_agentic_replies) - 1)]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        srv8 = ThreadingHTTPServer(("127.0.0.1", 0), AgenticMock)
        port8 = srv8.server_address[1]
        threading.Thread(target=srv8.serve_forever, daemon=True).start()
        try:
            with COMMON.env(LLM_BASE_URL=f"http://127.0.0.1:{port8}/v1", LLM_MODEL="mock"):
                text, trajectory, usage = run_agent("example_agentic", _question, role="llm", tools=_AGENTIC_TOOLS)
                assert text == "최종 답", text
                assert [t["tool"] for t in trajectory] == ["lookup", "finish_hint"], trajectory
                assert usage["model_calls"] == 3 and usage["tool_calls"] == 2, usage
                assert len(_agentic_hits) == 3, _agentic_hits
        finally:
            srv8.shutdown()
        print("[selftest] run_agent — 모의 서버 왕복: 도구 호출 두 번(백루프)·글자 응답으로 정상 종료, trajectory 순서 통과")

        # ⑤ 보안 독립 검토(AG4 후속) F1 — sub_agents의 model_role이 메인 role과 다를 때(여기 vlm) 그 role 전용 주소도
        # 모델 호출 전에 가드된다. 메인(llm)은 내부 주소로 통과시키고 sub(vlm)만 외부로 둬서 "메인만 가드되고 sub는
        # 안 됐던" 구멍을 재현·검증(require_internal은 순수 호스트 이름 판정이라 실제 전송 0 — is_internal 독스트링).
        with COMMON.env(LLM_BASE_URL="http://127.0.0.1:1", LLM_MODEL="mock", VLM_BASE_URL="https://openrouter.ai/api/v1", VLM_MODEL="x"):
            try:
                run_agent("example_agentic_vlm_sub", _question, role="llm", tools={})
                raise AssertionError("run_agent — sub_agent(vlm) 외부 주소인데 거부 안 됨")
            except RuntimeError as ex:
                assert "외부 주소" in str(ex), ex
        print("[selftest] run_agent — sub_agents 역할별 주소 가드(F1): 메인 role 통과·sub role(vlm) 외부면 호출 전 거부 통과")

        # ⑥ 보안 독립 검토(AG4 후속) F3 — LLM_MAX_CALLS=2인데 백루프는 실제로 3번 모델을 불러야 끝난다. reserve_call()의
        # 1건 예약만 보고 끝까지 돌리면 공유 장부를 몰래 넘기게 되므로, 진입 시 남은 수(remaining_calls())로 max_turns를
        # 미리 2로 깎아 3번째 요청은 서버에 보내지도 않고(hits==2) "예산 초과"로 끝나야 하고, 끝난 뒤 장부는 정확히
        # 2(예약 1 + 정산 1)여야 한다(3으로 과다 정산되거나 1로 과소 정산되면 안 됨).
        _hits6 = []

        class CapMock(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                self.rfile.read(length)
                i = len(_hits6)
                _hits6.append(1)
                out = json.dumps(_agentic_replies[min(i, len(_agentic_replies) - 1)]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        srv9 = ThreadingHTTPServer(("127.0.0.1", 0), CapMock)
        port9 = srv9.server_address[1]
        threading.Thread(target=srv9.serve_forever, daemon=True).start()
        with _L._lock:
            saved_calls2 = _L._stats["calls"]
            _L._stats["calls"] = 0
        try:
            with COMMON.env(LLM_BASE_URL=f"http://127.0.0.1:{port9}/v1", LLM_MODEL="mock", LLM_MAX_CALLS="2"):
                text, trajectory, usage = run_agent("example_agentic", _question, role="llm", tools=_AGENTIC_TOOLS)
                assert text == "예산 초과", text
                assert usage["model_calls"] == 2, usage
                assert len(_hits6) == 2, _hits6  # 3번째 요청은 서버에 보내지도 않음(선차감으로 미리 줄인 max_turns)
                with _L._lock:
                    assert _L._stats["calls"] == 2, _L._stats["calls"]  # 예약 1 + 정산 1 = 실제로 쓴 수와 정확히 같음
        finally:
            srv9.shutdown()
            with _L._lock:
                _L._stats["calls"] = saved_calls2
        print("[selftest] run_agent — LLM_MAX_CALLS 선차감(F3): 남은 수로 max_turns 축소·3번째 요청 전송 0·장부 정확히 정산 통과")

    # ⑦ RV12 — LLM_EXTRA_BODY·VLM_EXTRA_BODY(env) 병합. http 전송으로 실제 요청 본문을 캡처해 확인:
    # ① LLM_EXTRA_BODY만 있으면 role=llm 요청에 그대로 섞여 들어감 ② 호출자가 준 extra=가 같은 키를 덮어씀(figure_review.py
    # 패턴과 공존) ③ VLM_EXTRA_BODY는 role=vlm에만 적용, role=llm에는 안 묻음(역할별 분리).
    captured = []

    class Capture(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            captured.append(json.loads(self.rfile.read(length)))
            out = json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv10 = ThreadingHTTPServer(("127.0.0.1", 0), Capture)
    port10 = srv10.server_address[1]
    threading.Thread(target=srv10.serve_forever, daemon=True).start()
    try:
        with COMMON.env(
            LLM_BASE_URL=f"http://127.0.0.1:{port10}/v1",
            LLM_MODEL="mock",
            MODEL_TRANSPORT="http",
            LLM_EXTRA_BODY=json.dumps({"reasoning": {"enabled": False}, "x": 1}),
        ):
            complete("llm", [{"role": "user", "content": "x"}])
            assert captured[-1].get("reasoning") == {"enabled": False} and captured[-1].get("x") == 1, captured[-1]
            complete("llm", [{"role": "user", "content": "x"}], extra={"x": 2})  # 호출자 extra가 env의 같은 키를 덮어씀
            assert captured[-1].get("x") == 2 and captured[-1].get("reasoning") == {"enabled": False}, captured[-1]
            with COMMON.env(
                VLM_BASE_URL=f"http://127.0.0.1:{port10}/v1",
                VLM_MODEL="mock",
                VLM_EXTRA_BODY=json.dumps({"chat_template_kwargs": {"enable_thinking": False}}),
            ):
                complete("vlm", [{"role": "user", "content": "x"}])
                assert captured[-1].get("chat_template_kwargs") == {"enable_thinking": False} and "reasoning" not in captured[-1]
                complete("llm", [{"role": "user", "content": "x"}])  # role=llm은 VLM_EXTRA_BODY를 안 보고 LLM_EXTRA_BODY만 봄
                assert "chat_template_kwargs" not in captured[-1] and captured[-1].get("reasoning") == {"enabled": False}
    finally:
        srv10.shutdown()
    print("[selftest] LLM_EXTRA_BODY·VLM_EXTRA_BODY(RV12) — 역할별 분리·호출자 extra가 env를 덮어씀·요청 본문 병합 확인 통과")


def _selftest_local():
    """이미지 selftest는 서버 env(RUN_ENV=dev 등)에서도 돈다 — 외부 허용 경로 시험은 PC(local) 가드 규칙으로(S7b)."""
    from common.config.settings import COMMON

    with COMMON.env(RUN_ENV="local"):
        selftest()


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    _selftest_local()
