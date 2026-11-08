"""parse_document 서비스 — mcp-data-parsing 컨테이너(11-03 — 옛 data-pipeline-parse; 작업 서비스가 주 프로세스, compose.data-parsing.yml)의 작업 서비스(run_mcp_parsing)에 넘기는 프록시.
S5(10-26, refactor_plan 5-1·D-007 — 코디네이터 답 Q5 a)에 mcp_server/main.py(옛 data_retrieval/mcp_server.py)에서 옮김 — 내용 그대로
(설정 상수만 mcp_server/config.py의 CFG로). S7d(D-028 ⑨): 토큰은 설정 객체에서, 코드에 박혀 있던 대체 토큰은 지움 — 설정 필수.
"""

import json
import time

from common.core import parse_limit
from mcp_server import config as mc
from mcp_server.config import CFG
from mcp_server.services.tool_runner import PARSE_MAX_SEC

_NO_TOKEN = "parse 서비스 토큰 없음 — settings.yaml required.tokens.mcp_token를 설정(두 컨테이너가 같은 칸을 읽음)"


class NoToken(RuntimeError):
    """parse 서비스 토큰이 설정에 없음(공백만인 값 포함) — 값은 메시지에 넣지 않는다."""


def _token():
    """required.tokens.mcp_token(작업 서비스도 같은 칸). 없거나 공백만이면 NoToken. 요청마다 읽음."""
    tok = mc.token_text(mc.common_cfg().tokens.mcp)
    if not tok:
        raise NoToken(_NO_TOKEN)
    return tok


# ── 텍스트 파싱 프록시(2026-10-21 사용자 요청) — mcp-data-parsing 컨테이너(11-03 — 옛 data-pipeline-parse)의 작업 서비스(run_mcp_parsing,
#    그 컨테이너의 주 프로세스 — 토큰은 두 컨테이너가 같은 칸 required.tokens.mcp_token)
#    를 localhost HTTP로 호출 — 구조화·임베딩·EDW/OS 적재·그림[VLM] 파싱 없이 text 파싱 대표 결과만. ──
def _run_mcp_parsing(method, path, payload=None, timeout=10):
    """parse 서비스 HTTP — 토큰은 _token()."""
    import urllib.request

    data = json.dumps(payload).encode() if payload is not None else None
    tok = _token()
    req = urllib.request.Request(
        CFG.PARSE_URL + path, data=data, method=method, headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _parse_shaped(j, max_chars):
    """완료 응답 다듬기 — text가 max_chars(기본 200000자)를 넘으면 잘리고 text_truncated 표시(전체는 rep_path 파일).
    완료 응답에도 status:"done"을 심는다(호출자가 폴링 마감 조건으로 쓰게 — 2026-10-21 실사 중 빠진 게 튀어 나와 붙임)."""
    if j.get("status") != "done":
        return {k: j.get(k) for k in ("job_id", "filename", "status", "error", "elapsed_ms") if j.get(k) is not None}
    res = dict(j.get("result") or {})
    res["status"] = "done"
    t = res.get("text") or ""
    if max_chars and len(t) > int(max_chars):
        res["text"], res["text_truncated"] = t[: int(max_chars)], True
    return res


def do_parse_document(path=None, content_b64=None, filename=None, time_out_threshold=300, max_chars=200000):
    """비정형 파일 1건 → text 파싱 대표 결과. path(컨테이너 허용 루트 하위) 또는 content_b64+filename 둘 중 하나.
    time_out_threshold(기본 300초) 안에 파싱이 끝나야 결과를 돌려주고, 못 끝내면
    {"error": "시간 안에 수행 못했습니다", "job_id": …}를 반환한다(작업 자체는 서버에서 계속 진행 — 결과는
    수집 서버 _mcp_parse/jobs/<job_id>/에 만들어진다). 노출 도구는 이것 하나뿐이다(결과 수령 도구는 미노출 — 사용자 결정 10-21)."""
    import urllib.error

    payload = {"path": path, "content_b64": content_b64, "filename": filename}
    if not path and not content_b64:
        return {"error": "path 또는 content_b64(+filename) 필요"}
    if content_b64:  # 11-03 — 상한을 넘으면 서비스로 보내지 않고 여기서 거름(path는 서비스가 같은 칸으로 거름)
        # 원래 바이트 수 — 서비스(b64decode validate=False)처럼 줄바꿈·공백·'='는 빼고 셈(MIME 줄바꿈 base64도 같은 값)
        n = (len(content_b64) - sum(map(content_b64.count, ("\r", "\n", " ", "\t", "=")))) * 3 // 4
        if msg := parse_limit.too_big(n):
            return {"error": msg}
    t0 = time.time()  # 등록(큰 본문 전송) 시간도 time_out_threshold 안 — 바깥 창구(_bg_long, 기준 + 10초)보다 먼저 job_id를 돌려주게
    try:
        job = _run_mcp_parsing("POST", "/jobs", payload, timeout=60)  # 11-03 — 100MB(base64 약 133MB) 본문을 받아 풀고 쓰는 동안 기다림
    except NoToken as e:
        return {"error": str(e)}  # S7d — 설정 없음(연결 실패와 가름, 값 없음)
    except urllib.error.HTTPError as e:
        try:
            return {"error": json.loads(e.read()).get("error", f"HTTP {e.code}")}
        except Exception:
            return {"error": f"parse 서비스 오류: HTTP {e.code}"}
    except Exception as e:
        return {
            "error": f"parse 서비스 연결 실패({CFG.PARSE_URL}) — mcp-data-parsing 컨테이너(작업 서비스가 주 프로세스) 기동 확인: {type(e).__name__}: {e}"
        }
    job_id = job.get("job_id")
    if not job_id:
        return {"error": f"작업 등록 실패: {job}"}
    ahead = job.get("queue_position", 0)  # 2026-10-22 — 클대기 순번(지연 원인 추적용)
    thr = min(max(2.0, float(time_out_threshold or 0)), PARSE_MAX_SEC)  # 바깥 창구(_bg_long)와 같은 10분 상한
    while time.time() - t0 < thr:
        time.sleep(1.0)
        try:
            j = _run_mcp_parsing("GET", f"/jobs/{job_id}")
        except Exception:
            continue
        if j.get("status") in ("done", "failed"):
            return _parse_shaped(j, max_chars)
    return {
        "error": f"시간 안에 수행 못했습니다 — time_out_threshold({int(thr)}초) 내 파싱 미완료",
        "job_id": job_id,
        "elapsed_s": round(time.time() - t0, 1),
        "queue_position_at_submit": ahead,
        "note": f"작업은 수집 서버에서 계속 진행(대기열 {ahead}건 뒤) — 결과는 _mcp_parse/jobs/<job_id>/ 아래에 만들어진다(수집 서버 담당자 확인)",
    }
