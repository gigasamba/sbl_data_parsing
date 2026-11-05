"""common.ai.llm.complete — 모델 호출 한 길(HTTP). 가드·재시도·리다이렉트·agent= 형식 재요청·빈 응답 재요청·
EXTRA_BODY 사례. 가짜 로컬 서버만."""

import json
import threading
import time

import common.ai.llm as M
from common.ai.llm import ModelUnavailable, complete, schema_stats


def selftest():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from common.config.settings import COMMON

    # 가드 — 외부 주소 거부(require_internal이 그대로 전파, VLM 모듈이 지금도 안 잡는 것과 같게)
    with COMMON.env(VLM_ALLOW_EXTERNAL=None, VLM_BASE_URL="https://openrouter.ai/api/v1", VLM_MODEL="x"):
        try:
            complete("vlm", [{"role": "user", "content": "x"}])
            raise AssertionError("외부 주소인데 거부 안 됨")
        except RuntimeError as ex:
            assert "외부 주소" in str(ex), ex

    print("[selftest] 외부 주소 거부 통과")

    # preguarded 기본값은 항상 가드, 예외는 명시한 호출자만.
    # ① role="llm"이어도 기본값(preguarded=False)이면 외부 주소는 전송 전에 거부(cli/ping_models.py도 이 경로 — 역할별로
    #    가드를 건너뛰면 ping이 무가드가 된다)
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

    # 마지막 실패 뒤 대기 없음(재시도 2회, 둘 다 500 → sleep은 1번만)
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
        with COMMON.env(VLM_BASE_URL=f"http://127.0.0.1:{port}/v1", VLM_MODEL="mock"):
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
    print("[selftest] 재시도 — 마지막 실패 뒤 대기 없음(재시도 2회 → sleep 1번) 통과")

    # 리다이렉트 차단(guard._Redirect가 리다이렉트 대상을 다시 검사)
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
        with COMMON.env(VLM_BASE_URL=f"http://127.0.0.1:{port2}/v1", VLM_MODEL="mock"):
            try:
                complete("vlm", [{"role": "user", "content": "x"}], retries=1)
                raise AssertionError("외부로 리다이렉트인데 통과됨(http 전송)")
            except RuntimeError as ex:
                assert isinstance(ex, ModelUnavailable) and "openrouter" in str(ex) and "리다이렉트" in str(ex), (
                    ex
                )  # 0.2.0 — 호출부가 건너뛰게(GuardBlocked)
    finally:
        srv2.shutdown()
    print("[selftest] 내부 주소의 외부 리다이렉트 차단 통과")

    # agent=(패키지 경유) — 가짜 서버 1건: 응답 글자·usage가 agent 없는 경로와 같다(parity). 역할 불일치는 바로 거부.
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
        with COMMON.env(
            VLM_BASE_URL=f"http://127.0.0.1:{port5}/v1",
            VLM_MODEL="mock",
            LLM_BASE_URL=f"http://127.0.0.1:{port5}/v1",
            LLM_MODEL="mock",
        ):
            text_direct, usage_direct = complete("vlm", [{"role": "user", "content": "X는?"}], max_tokens=10)
            text_agent, usage_agent = complete(
                "vlm", [{"role": "user", "content": "X는?"}], max_tokens=10, agent="page_transcribe"
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

    # output_schema — 형식 검사·1회 재요청. nested_figure(output_schema 있음, 필수 "regions")로:
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
            assert _u.get("prompt_tokens") == 2 and _u.get("completion_tokens") == 2 and _u.get("calls") == 2, _u  # 두 호출 합산
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

    # 직접 호출자(agent=, call_reserved=False — vlm_page.py 등이 쓰는 모양)는 llm.chat()의
    # 빈 응답 안전망 밖이라 따로 재요청한다. page_transcribe(output_schema 없음, vlm_page.py가 실제로 쓰는 패키지)로: ① 1차가 빈
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
            assert _L16.usage()["calls"] - before16 == 2, "재요청도 공유 장부(호출 수)에 집계돼야 함(counted)"
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

    # ⑦ LLM_EXTRA_BODY·VLM_EXTRA_BODY 병합. http 전송으로 실제 요청 본문을 캡처해 확인:
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
    """이미지 selftest는 서버 env(RUN_ENV=dev 등)에서도 돈다 — 외부 허용 경로 시험은 PC(local) 가드 규칙으로."""
    from common.config.settings import COMMON

    with COMMON.env(RUN_ENV="local"):
        selftest()


def test_main():
    _selftest_local()
