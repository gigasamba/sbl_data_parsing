"""모델 엔드포인트 내부망 확인 — 회사 문서를 외부 모델에 보내지 않음(DONT 13). 파싱(VLM)·구조화(임베딩)·검색(임베딩·LLM) 공통.

외부 허용 = 두 겹(보안 검토 10-02 — VLM·임베딩이 한 겹이라 개발 PC env가 운영 서버로 복사되면 문서 이미지·본문이 바로 나갔음):
  ① <PREFIX>_ALLOW_EXTERNAL=1  ② 가상 코퍼스 정답 파일(LLM_SYNTHETIC_TRUTH 또는 SYNTHETIC_TRUTH — make_corpus의 "_meta")
실데이터 서버에는 ②가 없으므로 ①만 잘못 켜져도 거부된다. 리다이렉트로 외부로 가는 것도 막는다(urlopen)."""

import http.client
import ipaddress
import json
import os
import socket
import urllib.parse
import urllib.request
from pathlib import Path

from common.config.settings import by_env, cfg, checked, external_models_allowed, guard_run_env

_SUFFIX = (".local", ".internal", ".corp", ".lan")


def _internal_networks():
    """INTERNAL_IP_RANGES(쉼표 CIDR) — 사설 대역(RFC1918) 밖인 사내 대역(SI21, 개발 서버 실측 10-07).
    잘못된 항목·너무 넓은 대역(IPv4 /8보다 넓음 · IPv6 /16보다 넓음 — 0.0.0.0/0 같은 실수로 전부 '내부'가 되지 않게)은 무시하고 경고.
    무시는 '좁히는' 쪽(그 주소는 외부로 남음) — 가드를 넓히지 않는 실패. 호출마다 설정 객체를 다시 읽음(캐시 없음, selftest·재설정 반영 — S7b: 쉼표 목록은 객체가 strip·빈 것 버림)."""
    nets = []
    for s in cfg().models.guard.internal_ip_ranges or ():
        try:
            n = ipaddress.ip_network(s, strict=False)
        except ValueError:
            print(f"[guard] INTERNAL_IP_RANGES 무시(형식 오류): {s!r}", flush=True)
            continue
        if n.prefixlen < (8 if n.version == 4 else 16):
            print(f"[guard] INTERNAL_IP_RANGES 무시(너무 넓음): {s!r}", flush=True)
            continue
        nets.append(n)
    return nets


def _private(ip):
    ip = ipaddress.ip_address(ip)
    return ip.is_private or ip.is_loopback or any(ip in n for n in _internal_networks() if n.version == ip.version)


def _resolves_private(host):
    """이름 → 주소가 모두 사설·루프백이면 True. 풀리지 않으면 False(나중에 외부로 풀릴 수 있음 — 막고 본다).
    캐시하지 않음(재검증 10-02: 실패를 '내부'로 기억하면 DNS가 바뀐 뒤에도 통과) — 호출마다 이름 풀기 1회."""
    try:
        addrs = {a[4][0] for a in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    return bool(addrs) and all(_private(a.split("%")[0]) for a in addrs)


def _company_suffixes():
    """각 항목을 점으로 시작하게 정규화 — "mycompany.co.kr"만 적어도 "evilmycompany.co.kr"이 걸리지 않게(보안 검토 10-05)."""
    out = []
    for s in cfg().models.guard.internal_host_suffixes or ():  # S7b — 쉼표 목록은 객체가 strip·빈 것 버림
        s = s.strip().lower()
        if s:
            out.append(s if s.startswith(".") else "." + s)
    return tuple(out)


def is_internal(url):
    host = (urllib.parse.urlparse(url).hostname or "").rstrip(".")  # 끝점(FQDN) 제거 — host.mycompany.co.kr. 도 같은 호스트
    try:
        return _private(host)  # 주소 직접
    except ValueError:
        pass
    if host == "localhost" or "." not in host or host.endswith(_SUFFIX):
        return _resolves_private(host)  # 이름만 믿지 않음 — 점 없는 별칭·사내 접미사도 실제 주소가 사설일 때만
    if host.endswith(_company_suffixes()):
        return _resolves_private(host)  # INTERNAL_HOST_SUFFIXES 허용목록 — 풀린 주소가 전부 사설일 때만 내부(DNS 속임 방지)
    return False


def run_env_block():
    """RUN_ENV가 정확히 local이 아니면(없음·dev·stage·prd·모르는 글자) 거부 이유 글자(서버는 내부망 전용 — D-028 ⑧, S7b ·
    없음·모르는 글자도 서버로 — VS7b U-1 b), local이면 None(지금 가드대로). 두 겹 잠금이 다 열려 있어도 서버 환경이면 외부 모델을 못 쓴다."""
    run_env = guard_run_env()
    if external_models_allowed(run_env):
        return None
    return f"RUN_ENV={run_env} — 내부망 전용(외부 모델 거부)" if run_env else "RUN_ENV 없음 — local이 아니면 내부망 전용(외부 모델 거부)"


def synthetic_ok():
    """외부 허용 두 번째 잠금 — 가상 코퍼스 정답 파일(make_corpus의 "_meta")이 지정돼 있을 때만.
    RUN_ENV가 dev·stage·prd면 파일이 있어도 닫힘(run_env_block, S7b). llm.chat·external_allowed가 이 한 곳을 거침."""
    if run_env_block():
        return False
    p = cfg().models.guard.synthetic_truth  # S7e2 — 옛 별칭 SYNTHETIC_TRUTH는 읽지 않음(C-35, 사용자 10-28 — migrate가 새 칸으로 옮김)
    try:
        return bool(p) and "_meta" in json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False


def external_allowed(prefix):
    # S7b — {prefix}_ALLOW_EXTERNAL은 객체 칸(켜기 =1) · 칸 없는 접두(시험의 가짜 접두)는 False
    return bool(by_env(f"{prefix}_ALLOW_EXTERNAL", False)) and synthetic_ok()


def require_internal(url, prefix):
    """모델 엔드포인트(VLM·OCRVLM·EMBED) 외부 전송 가드 — 내부망만(DONT 13). 합성 데이터 실험이면 <prefix>_ALLOW_EXTERNAL=1 + 합성 정답 파일."""
    if url and not is_internal(url) and not external_allowed(prefix):
        host = urllib.parse.urlparse(url).hostname or url
        why = run_env_block()
        raise RuntimeError(
            f"{prefix}_BASE_URL이 외부 주소({host}) — 회사 문서는 내부망 모델만(DONT 13). "
            f"합성 데이터 실험이면 {prefix}_ALLOW_EXTERNAL=1 + LLM_SYNTHETIC_TRUTH(가상 코퍼스 정답 파일) 둘 다"
            + (f" ({why})" if why else "")
        )


class _Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, prefix):
        self.prefix = prefix

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_internal(newurl) and not external_allowed(self.prefix):
            raise RuntimeError(f"내부 엔드포인트가 외부({urllib.parse.urlparse(newurl).hostname})로 리다이렉트 — 거부(DONT 13)")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class BudgetExceeded(RuntimeError):
    pass


_SPEND_LOCAL = [0.0]  # LLM_SPEND_FILE이 없을 때 이 프로세스 장부
import threading as _threading  # noqa: E402

_LOCAL_LOCK = _threading.Lock()  # 프로세스 안 스레드 간 확인+가산 원자화(10-05 재검증)


class _FileLock:
    """장부 파일 옆 .lock — 확인+예약을 프로세스 간 원자적으로(10-05 독립 검토: 확인·기록 사이 틈으로 동시 호출이 상한 초과)."""

    def __init__(self, path):
        self.f = open(str(path) + ".lock", "a+")

    def __enter__(self):
        if os.name == "nt":
            import msvcrt
            import time as _t

            while True:
                try:
                    self.f.seek(0)
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                    return self
                except OSError:
                    _t.sleep(0.05)
        import fcntl

        fcntl.flock(self.f.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        try:
            if os.name == "nt":
                import msvcrt

                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        finally:
            self.f.close()


def _ledger_sum(f):
    try:
        return sum(float(x) for x in open(f, encoding="utf-8").read().split() if x)
    except (OSError, ValueError):
        return 0.0


def budget_usd():
    """지출 상한 LLM_BUDGET_USD(float, 없으면 None) — 읽는 곳은 모두 이것으로(VS7b R-5 — checked를 빠뜨려 형식 틀린 상한이
    "상한 없음"으로 열리지 않게). 형식이 틀리면(nan·inf 포함 — R-12) ValueError(이름만)."""
    checked("LLM_BUDGET_USD")
    return cfg().models.guard.budget_usd


def spend_total():
    f = cfg().models.guard.spend_file
    return _ledger_sum(f) if f else _SPEND_LOCAL[0]


def spend_reserve(usd, label):
    """유료 호출 전 예상 최대 비용을 먼저 장부에 씀(선차감) — 상한(LLM_BUDGET_USD)을 넘으면 BudgetExceeded(호출 안 함).
    LLM_SPEND_FILE(실행 전체가 공유)이 있으면 파일 잠금 안에서 합계 확인+기록."""
    budget, f = budget_usd(), cfg().models.guard.spend_file  # S7b — 예산은 float|None(옛 글자 "0"도 참이었으므로 is not None)
    if f:
        with _FileLock(f):
            total = _ledger_sum(f)
            if budget is not None and total + usd > budget:
                raise BudgetExceeded(f"LLM_BUDGET_USD={budget} — 누적 ${total:.2f} + 이번 {label} 예상 ${usd:.4f} 초과, 호출 안 함")
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(f"{usd:.6f}\n")
        return
    with _LOCAL_LOCK:
        if budget is not None and _SPEND_LOCAL[0] + usd > budget:
            raise BudgetExceeded(f"LLM_BUDGET_USD={budget} — 누적 ${_SPEND_LOCAL[0]:.2f} + {label} ${usd:.4f} 초과, 호출 안 함")
        _SPEND_LOCAL[0] += usd


def spend_settle(delta):
    """호출 뒤 실제−예상 정산(음수 가능). 사용량을 모르면 부르지 않음 = 예상 최대치가 그대로 남음(보수적)."""
    if not delta:
        return
    f = cfg().models.guard.spend_file
    if f:
        with _FileLock(f), open(f, "a", encoding="utf-8") as fh:
            fh.write(f"{delta:.6f}\n")
    else:
        with _LOCAL_LOCK:
            _SPEND_LOCAL[0] += delta


# llm.chat 밖에서 바로 부르는 유료 호출(VLM 그림·쪽, 임베딩, 재랭크)의 호출당 예상 비용($) — 예산 선차감용(보수적 고정값, env로 덮어씀)
_EST_USD = {"VLM": 0.02, "EMBED": 0.001, "RERANK": 0.001}


class ScopeExceeded(RuntimeError):
    pass


def external_scope():
    """EXTERNAL_SCOPE(기본 func) — "e2e"가 아니면 전부 func로 본다(미지값도 안전하게 보수적인 쪽, AD43)."""
    return cfg().models.guard.external_scope  # 빈 글자는 그대로(옛 get(X, "func")처럼 — blank="keep")


def check_scope(urls, *, n_combos=None, n_docs=None, n_questions=None):
    """AD43 — 외부(OpenRouter 등) 모델 사용 '범위' 가드(require_internal·precheck의 두 겹·예산·NO_PAID_CALLS와
    별개의 세 번째 겹, 여기서 그 가드들을 느슨하게 하지 않는다). urls: 이번 실행이 쓰는 모델 엔드포인트 주소들
    (LLM·VLM·EMBED 등 — None·빈 문자열 섞여도 됨). 전부 내부망이면 바로 통과(내부 실행은 영향 없음).
    외부 주소가 하나라도 있으면:
      ① 조합(n_combos) ≥2 — scope 무관 항상 거부(스택 조합별 성능 비교는 서버 내부 모델로 돌리세요 · 전체 E2E
         점검은 조합 1개로 끝까지 도는 것만 EXTERNAL_SCOPE=e2e로 허용).
      ② external_scope() != "e2e"(기본 func) — 기능 시험만:
         - LLM_BUDGET_USD 미설정이면 거부(예산 상한 없는 외부 호출 금지)
         - n_docs > EXTERNAL_MAX_DOCS(기본 10) 또는 n_questions > EXTERNAL_MAX_QUESTIONS(기본 20)면 거부
      scope=="e2e"면 ②는 건너뜀(①이 이미 조합 1개로 막아 둠)."""
    if not any(u and not is_internal(u) for u in urls):
        return
    if n_combos is not None and n_combos >= 2:
        raise ScopeExceeded(
            f"조합 {n_combos}개 + 외부 주소 — 스택 조합별 성능 비교는 서버 내부 모델로 돌리세요"
            f"(전체 E2E 점검은 EXTERNAL_SCOPE=e2e로 조합 1개만 허용)"
        )
    if external_scope() != "e2e":
        if budget_usd() is None:
            raise ScopeExceeded("EXTERNAL_SCOPE=func(기본) — LLM_BUDGET_USD 없이 외부 호출 금지. 성능 비교는 서버 내부 모델로 돌리세요")
        max_docs = cfg().models.guard.external_max_docs
        max_q = cfg().models.guard.external_max_questions
        if n_docs is not None and n_docs > max_docs:
            raise ScopeExceeded(
                f"EXTERNAL_SCOPE=func — 문서 {n_docs}개 > 상한 {max_docs}(EXTERNAL_MAX_DOCS). 성능 비교는 서버 내부 모델로 돌리세요"
            )
        if n_questions is not None and n_questions > max_q:
            raise ScopeExceeded(
                f"EXTERNAL_SCOPE=func — 질문 {n_questions}개 > 상한 {max_q}(EXTERNAL_MAX_QUESTIONS). 성능 비교는 서버 내부 모델로 돌리세요"
            )


def precheck(url, prefix):
    """모델 호출 전 비용 관문(원래 urlopen 안에 있던 사전 검사 — GA, urlopen·common/adk.py가 공유하게 뽑음).
    require_internal(외부 주소 거부)은 별개로 호출자가 먼저 부른다. 비용 관문(10-05): NO_PAID_CALLS=1이면 외부 주소
    호출 자체를 거부(추정·preflight·context-only) · LLM_BUDGET_USD가 있으면 llm.chat 밖 호출(VLM·EMBED·RERANK)도
    호출 전 고정 예상액을 선차감(LLM은 llm.chat이 토큰 기준으로 함).
    반환: 이번 호출이 선차감한 금액(0.0이면 내부망·LLM_BUDGET_USD 미설정 등 정산 대상 아님) — BR45, 호출자가 응답의
    실제 토큰 usage를 알게 된 뒤 settle_tokens(이 값, ...)로 사후 정산한다(선차감 당시엔 토큰 수를 모르니 고정값)."""
    external = not is_internal(url)
    if external and cfg().models.guard.no_paid_calls:
        raise BudgetExceeded(f"NO_PAID_CALLS=1 — 외부 유료 호출 차단({prefix}: {urllib.parse.urlparse(url).hostname})")
    if external and prefix != "LLM" and budget_usd() is not None:
        usd = by_env(f"{prefix}_EST_USD", _EST_USD.get(prefix, 0.01))  # 칸 없는 접두·값 없음은 _EST_USD 표
        spend_reserve(usd, prefix)
        return usd
    return 0.0


def release_reserve(usd):
    """GA9 — spend_reserve()로 선차감한 금액을 전부 되돌린다(실패·취소: 호출이 안 끝나 settle_tokens를 거칠
    실제 usage가 없는 경우). settle_tokens와 짝 — 성공은 settle_tokens(차이만 정산), 실패·취소는 release_reserve
    (전액 반환). usd<=0이면 아무것도 안 함(이중 반환 방지는 호출자가 자기 쪽 예약 플래그를 지우는 것으로 막는다
    — 여기는 단순 산술이라 두 번 불리면 두 번 돌려주므로 호출자 책임)."""
    if usd:
        spend_settle(-usd)


def settle_tokens(reserved, model, usage):
    """BR45 — precheck()가 고정 선차감한 비-LLM 호출(VLM·EMBED 등)을, 응답이 실제 토큰 수(usage)를 담고 있으면
    common/llm.PRICES(모델 이름 기준 고정표만 — env LLM_PRICE_IN·OUT은 안 봄, 그건 llm.chat 자신의 role=llm 전용
    오버라이드라 그대로 재사용하면 VLM·EMBED에 LLM 쪽 단가가 잘못 섞여 들어갈 수 있다)로 실제 비용을 계산해 차이를
    정산한다(llm.py _do_call의 토큰 정산과 같은 방식 — 10-11 실측: VLM 15회가 flat $0.02×15=$0.30으로 잡혀 실제
    약 $0.02보다 과하게 일찍 상한이 걸림). reserved<=0(정산 대상 아님)·usage 없음·단가 모름(이 모델이 PRICES에
    없음 — 예: 로컬 e5-small 같은 비-API 임베딩이나 미등록 VLM)이면 아무것도 안 하고 기존 고정값이 그대로 남는다 —
    llm.chat처럼 단가를 모르면 호출 자체를 거부하지 않는다(이미 끝난 호출의 사후 정산이라 조용히 보수적인 값에
    머무는 쪽이 안전)."""
    if not (reserved and usage):
        return
    from common.ai import llm as _L  # 지연 import — guard.py가 llm.py보다 먼저 로드되므로 모듈 최상단에선 순환 import

    name = (model or "").removeprefix("openai/")
    d = _L.PRICES.get(name) or _L.PRICES.get(name.split("/")[-1].split(":")[0])
    if d is None:
        return
    usd = (usage.get("prompt_tokens", 0) * d["in"] + usage.get("completion_tokens", 0) * d["out"]) / 1e6
    spend_settle(usd - reserved)


def _connect_timeout():
    """RV24 — MODEL_CONNECT_TIMEOUT(기본 10초, <=0이면 끔). urllib의 timeout 인자 하나는 connect·recv 공용(소켓
    타임아웃이 connect() 때 걸리고 그대로 남아 recv에도 적용됨, 실측) — 서버가 멈춰 TCP 연결이 안 열리면(블랙홀·
    방화벽 drop) 쪽 응답을 기다리는 것과 같은 전체 timeout(기본 VLM 360초)을 다 기다렸다. connect만 짧게 끊는다."""
    v = cfg().models.transport.connect_timeout
    return v if v > 0 else None


def _connect_with_split_timeout(conn, real_connect):
    """connect()만 _connect_timeout()으로 짧게 묻고, 연결되면 소켓 타임아웃을 호출자가 원래 요청한 전체 시간(읽기
    상한)으로 되돌린다 — http·https 전송(MODEL_TRANSPORT=http, 어댑터 롤백 경로) 둘 다 adk/litellm 경로(RV24,
    agent_platform.models.create_model)와 같은 connect/read 분리를 받는다. real_connect는 호출부가 넘기는 실제
    부모 클래스의 connect(HTTPConnection 또는 HTTPSConnection, TLS 핸드셰이크까지 포함)
    — zero-arg super()는 __class__ 셀이 정의 시점 클래스에 묶여 다른 클래스(HTTPS용)에 그대로 재사용 못 해
    (TypeError: super(type, obj) — obj must be instance of type) 두 클래스가 각자 자기 부모를 명시해서 넘긴다."""
    read_timeout = conn.timeout
    c = _connect_timeout()
    has_read = read_timeout not in (None, socket._GLOBAL_DEFAULT_TIMEOUT)
    if c is not None:
        conn.timeout = min(c, read_timeout) if has_read else c
    try:
        real_connect()
    finally:
        conn.timeout = read_timeout
    if conn.sock is not None and has_read:
        conn.sock.settimeout(read_timeout)


class _SplitTimeoutHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        _connect_with_split_timeout(self, lambda: http.client.HTTPConnection.connect(self))


class _SplitTimeoutHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        _connect_with_split_timeout(self, lambda: http.client.HTTPSConnection.connect(self))


class _ConnectTimeoutHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_SplitTimeoutHTTPConnection, req)


class _ConnectTimeoutHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_SplitTimeoutHTTPSConnection, req, context=self._context)


def _precheck_and_open(req, timeout, prefix):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    reserved = precheck(url, prefix)
    opener = urllib.request.build_opener(_Redirect(prefix), _ConnectTimeoutHTTPHandler(), _ConnectTimeoutHTTPSHandler())
    return opener.open(req, timeout=timeout), reserved


def urlopen(req, timeout, prefix):
    """모델 호출용 urlopen — 리다이렉트 대상도 같은 가드(_Redirect)로 다시 확인. 최초 요청은 precheck로."""
    resp, _reserved = _precheck_and_open(req, timeout, prefix)
    return resp


def urlopen_metered(req, timeout, prefix):
    """urlopen()과 같지만 BR45 사후 정산에 쓸 선차감액도 함께 돌려준다((응답, reserved)) — 호출자가 응답 JSON의
    usage로 settle_tokens(reserved, model, usage)를 부를 수 있게(common/embed.py 등, urlopen()의 기존 호출자
    (rerank.py 등)는 그대로 둠 — 반환 모양을 바꾸지 않음)."""
    return _precheck_and_open(req, timeout, prefix)
