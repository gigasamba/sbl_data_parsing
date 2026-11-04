"""모델 엔드포인트 내부망 확인 — 회사 문서를 외부 모델에 보내지 않음(DONT 13). 파싱(VLM)·구조화(임베딩)·검색(임베딩·LLM) 공통.

외부 허용 = <PREFIX>_ALLOW_EXTERNAL=1 이고 RUN_ENV가 정확히 local일 때만(서버 dev·prd·없음은 거부).
합성 문서 선언 파일(옛 LLM_SYNTHETIC_TRUTH) 잠금은 뺐다(사용자 10-29 — 실데이터 없음·사내 폐쇄망은 외부 경로 막힘). 리다이렉트로 외부로 가는 것도 막는다(urlopen)."""

import http.client
import ipaddress
import os
import socket
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from common.config import layout as L
from common.config.settings import by_env, cfg, checked, external_models_allowed, guard_run_env
from common.core.paths import SPEND_DIR

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
    """RUN_ENV가 정확히 local이 아니면(없음·dev·prd·모르는 글자) 거부 이유 글자(서버는 내부망 전용 — D-028 ⑧, S7b ·
    없음·모르는 글자도 서버로 — VS7b U-1 b), local이면 None(지금 가드대로). 외부 허용이 켜져 있어도 서버 환경이면 외부 모델을 못 쓴다."""
    run_env = guard_run_env()
    if external_models_allowed(run_env):
        return None
    return f"RUN_ENV={run_env} — 내부망 전용(외부 모델 거부)" if run_env else "RUN_ENV 없음 — local이 아니면 내부망 전용(외부 모델 거부)"


def fake_llm():
    """가짜 LLM 응답(common.dev.llm_fake)을 쓸지 — op-02(사용자 10-29): local 전용. 서버(dev·prd)·모르는 RUN_ENV에서 켜져 있으면
    RuntimeError(시작 관문을 안 거치는 docker exec 모듈도 막음). RUN_ENV 없음(selftest·시험)은 지금처럼 허용."""
    if not cfg().dev.llm_fake:
        return False
    run = guard_run_env()
    if run is not None and run != "local":
        raise RuntimeError(f"RUN_ENV={run} — 가짜 LLM 응답(settings.yaml {L.to_yaml('common.dev.llm_fake')})은 local 전용(서버에서 끔)")
    return True


def external_ok(allow):
    """외부 모델 허용 규칙 한 곳 — 허용 스위치가 켜지고 RUN_ENV=local일 때만(합성 문서 선언 잠금은 사용자 10-29에 삭제).
    external_allowed(설정 칸)·llm.chat(allow_external 인자·LLM_ALLOW_EXTERNAL 설정)이 이 한 곳을 거친다."""
    return bool(allow) and not run_env_block()


def external_allowed(prefix):
    # S7b — {prefix}_ALLOW_EXTERNAL은 객체 칸(켜기 =1) · 칸 없는 접두(시험의 가짜 접두)는 False
    return external_ok(by_env(f"{prefix}_ALLOW_EXTERNAL", False))


def require_internal(url, prefix):
    """모델 엔드포인트(VLM·EMBED) 외부 전송 가드 — 내부망만(DONT 13). 개발 PC 실험이면 <prefix>_ALLOW_EXTERNAL=1(RUN_ENV=local)."""
    if url and not is_internal(url) and not external_allowed(prefix):
        host = urllib.parse.urlparse(url).hostname or url
        why = run_env_block()
        raise RuntimeError(
            f"{prefix}_BASE_URL이 외부 주소({host}) — 회사 문서는 내부망 모델만(DONT 13). "
            f"개발 PC 실험이면 {prefix}_ALLOW_EXTERNAL=1(RUN_ENV=local)" + (f" ({why})" if why else "")
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


def ledger_file(day=None):
    """오늘(현지 날짜) 지출 장부 파일 — 상한은 하루 단위(사용자 11-03 — PC 사용자마다 하루 0.1달러 기본). spend_file이 있으면 그 이름 뒤에
    날짜를 붙이고(`spend.json` → `spend-2026-11-03.json`), 없으면 <저장소>/output/_llm_spend/<날짜>.txt — 그 작업 폴더의 모든 프로세스가 공유
    (worktree·다른 체크아웃은 따로).
    외부 호출은 RUN_ENV=local(PC)에서만 되므로 "사람마다" = PC·OS 사용자마다(서버는 외부 모델을 거부)."""
    day = day or time.strftime("%Y-%m-%d")
    f = cfg().models.guard.spend_file
    return Path(f).with_name(f"{Path(f).stem}-{day}{Path(f).suffix}") if f else SPEND_DIR / f"{day}.txt"


def spend_total():
    return _ledger_sum(ledger_file())


# 선차감한 날짜(스레드마다) — 정산·반환은 선차감과 같은 날 장부로(자정을 넘겨 돌아온 환불이 다음 날 상한을 늘리지 않게 — 리뷰 11-03).
# ponytail: 한 스레드가 정산 전에 다른 선차감을 하면 마지막 날짜를 씀 — 지금 호출 길(선차감→호출→정산)은 스레드마다 하나씩, 겹치면
# spend_reserve가 장부 파일을 돌려주고 호출자가 들고 다니게 바꿈.
_DAY = threading.local()


def spend_reserve(usd, label):
    """유료 호출 전 예상 최대 비용을 먼저 오늘 장부에 씀(선차감) — 하루 상한(LLM_BUDGET_USD)을 넘으면 BudgetExceeded(호출 안 함).
    파일 잠금 안에서 합계 확인+기록(프로세스·스레드 사이 원자적)."""
    _DAY.d = time.strftime("%Y-%m-%d")
    budget, f = budget_usd(), ledger_file(_DAY.d)  # S7b — 예산은 float|None(옛 글자 "0"도 참이었으므로 is not None)
    f.parent.mkdir(parents=True, exist_ok=True)
    with _FileLock(f):
        total = _ledger_sum(f)
        if budget is not None and total + usd > budget:
            raise BudgetExceeded(f"LLM_BUDGET_USD={budget}(하루) — 오늘 누적 ${total:.2f} + 이번 {label} 예상 ${usd:.4f} 초과, 호출 안 함")
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"{usd:.6f}\n")


def spend_settle(delta):
    """호출 뒤 실제−예상 정산(음수 가능) — 이 스레드가 선차감한 날의 장부에(없으면 오늘). 사용량을 모르면 부르지 않음 = 예상 최대치가
    그대로 남음(보수적)."""
    if not delta:
        return
    f = ledger_file(getattr(_DAY, "d", None))
    f.parent.mkdir(parents=True, exist_ok=True)
    with _FileLock(f), open(f, "a", encoding="utf-8") as fh:
        fh.write(f"{delta:.6f}\n")


# llm.chat 밖에서 바로 부르는 유료 호출(VLM 그림·쪽, 임베딩, 재랭크)의 호출당 예상 비용($) — 예산 선차감용(보수적 고정값, env로 덮어씀)
_EST_USD = {"VLM": 0.02, "EMBED": 0.001}


def precheck(url, prefix):
    """모델 호출 전 비용 관문(원래 urlopen 안에 있던 사전 검사 — GA, urlopen·common.ai.llm이 공유하게 뽑음).
    require_internal(외부 주소 거부)은 별개로 호출자가 먼저 부른다. 비용 관문: LLM_BUDGET_USD가 있으면 llm.chat 밖 호출(VLM·EMBED·RERANK)도
    호출 전 고정 예상액을 선차감(LLM은 llm.chat이 토큰 기준으로 함).
    반환: 이번 호출이 선차감한 금액(0.0이면 내부망·LLM_BUDGET_USD 미설정 등 정산 대상 아님) — BR45, 호출자가 응답의
    실제 토큰 usage를 알게 된 뒤 settle_tokens(이 값, ...)로 사후 정산한다(선차감 당시엔 토큰 수를 모르니 고정값)."""
    external = not is_internal(url)
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
    없음 — 예: 미등록 VLM)이면 아무것도 안 하고 기존 고정값이 그대로 남는다 —
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
    상한)으로 되돌린다 — http·https 전송 둘 다 같은 connect/read 분리를 받는다(0.2.0 — 모델 호출은 common.ai.llm HTTP 한 길,
    옛 ADK·litellm 경로는 pl-46에 지움). real_connect는 호출부가 넘기는 실제
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


def open_guarded(req, timeout, prefix):
    """precheck 없이 여는 길 — 리다이렉트 가드(_Redirect)·연결 시간 상한은 같음. 호출자가 이미 precheck로 선차감한 경우만
    (common.ai.llm.complete — 시도마다 다시 선차감하면 정산되지 않는 몫이 장부에 쌓임, 0.2.0 리뷰)."""
    opener = urllib.request.build_opener(_Redirect(prefix), _ConnectTimeoutHTTPHandler(), _ConnectTimeoutHTTPSHandler())
    return opener.open(req, timeout=timeout)


def _precheck_and_open(req, timeout, prefix):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    reserved = precheck(url, prefix)
    return open_guarded(req, timeout, prefix), reserved


def urlopen(req, timeout, prefix):
    """모델 호출용 urlopen — 리다이렉트 대상도 같은 가드(_Redirect)로 다시 확인. 최초 요청은 precheck로."""
    resp, _reserved = _precheck_and_open(req, timeout, prefix)
    return resp


def urlopen_metered(req, timeout, prefix):
    """urlopen()과 같지만 BR45 사후 정산에 쓸 선차감액도 함께 돌려준다((응답, reserved)) — 호출자가 응답 JSON의
    usage로 settle_tokens(reserved, model, usage)를 부를 수 있게(common/embed.py 등, urlopen()의 기존 호출자
    (rerank.py 등)는 그대로 둠 — 반환 모양을 바꾸지 않음)."""
    return _precheck_and_open(req, timeout, prefix)
