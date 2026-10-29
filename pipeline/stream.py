#!/usr/bin/env python3
"""스트리밍 모드(백로그 X2 = O2+O11 통합) — 문서를 작은 묶음으로 받아 처리한 뒤 즉시 지운다.
cli/pipeline.py의 parse 모듈이 PARSE_STREAM=1 · --source일 때 이 모듈의 run()을 쓴다.

왜: 수집 서버(1차는 개발 서버)가 실원본을 받는다 — 처리가 끝나면 디스크에 원본·사본·본문이 남으면 안 된다(데이터 보호).
어떻게: 한 바퀴(묶음 1건) = 받기(PARSE_TMP) → 회전 보정(prepare) → 파싱(run_all) → 채점(parse_qa) → 대표 결과(represent)
→ (try/finally) 원본·회전 사본·그 문서들의 엔진별 중간 결과를 지움. 대표 결과(_rep)·그림 기록/PNG(output/parse/_images)는 항상 남긴다.
묶음 단위로만 받아 PARSE_TMP가 동시에 작은 양만 들고 있게 한다(컨테이너가 죽어도 디스크에 남는 게 적음).
PARSE_TMP/.stream.lock(pid 기록, O_EXCL)으로 같은 PARSE_TMP에 스트리밍 두 개가 동시에 돌지 못하게 막는다
(독립 보안 검토 MINOR 7) — 죽은 프로세스의 잠금은 시작할 때 자동으로 치운다(pid 살아있는지 확인).
**순서가 중요**: 잠금을 먼저 얻고 그 다음에 시작 시 청소를 한다(독립 보안 검토 재검토 5번) — 반대로 하면
동시에 시작한 두 프로세스가 둘 다 청소를 통과해 버려, 나중에 잠그는 쪽이 이긴 쪽의 작업 파일을 지울 수 있다.
첨부 임시 파일(post/attachments.py)은 PARSE_TMP 안이 아니라 그 형제 폴더(attach_dir, output/_tmp_parse/attach)에
둔다(독립 보안 검토 재검토 6번) — 시작 시 청소가 PARSE_TMP(.../stream)만 지우므로, 스트리밍이 아닌 다른 프로세스가
같은 때에 첨부를 파싱 중이어도 그 임시 파일이 지워지지 않는다. attach_dir은 시작 시 통째 청소를 안 하고
쓰는 쪽이 파일 하나 끝낼 때마다 finally로 직접 지운다.

환경변수(S7c — 설정 객체 pipeline 절로 읽음):
  PARSE_STREAM         1 = 이 경로(스트리밍) · (기본 꺼짐 — cli/pipeline.py가 호출 전에 확인)
  PARSE_STREAM_BATCH   한 바퀴에 받아 처리할 문서 수(기본 1)
  PARSE_TMP            받기·회전 보정에 쓰는 임시 폴더(기본 output/_tmp_parse/stream) — tmpfs 권장(--tmpfs로 마운트:
                        컨테이너가 죽어도 디스크에 안 남고, 재시작하면 바로 비어 있어 시작 시 청소도 덜 필요).
                        ROOT/output 아래 2단 이상 하위 폴더만 허용(그 밖이면 거부·종료) — cleanup_startup이 통째로
                        rmtree하므로 `/`·홈 폴더·저장소 루트로 잘못 설정되면 재앙(독립 보안 검토 BLOCKER 1).
  PARSE_TMP_MAX_GB     PARSE_TMP 사용량 상한(GB, 0 = 제한 없음) — 넘으면 다음 묶음을 받기 전에 대기
  KEEP_RAW_LAYER       1(기본) = P0 원본 층 캐시(output/parse/raw/** — VLM·메일 첨부 재사용, common/artifacts.py) 유지
                        0 = 그 문서가 이번에 새로 만든 캐시도 즉시 지움(수집 서버처럼 재사용보다 보호가 중요할 때)
  KEEP_ENGINE_CACHE    0(기본, 운영) = 엔진별 중간 결과(output/parse/<엔진>/<문서>.json)를 대표 결과 생성 뒤 항상 지움
                        1 = 안 지움 — 합성 데이터로 스택·엔진을 반복 실험할 때 "원문은 다시 안 긁는다" 캐시를 그대로
                        두고 싶을 때만(독립 보안 검토 MINOR 6). 실원본이 있는 운영 환경에서는 켜지 않는다.
  KEEP_LOCAL_ORIGINALS (source.py에 이미 있음) 1 = 원본·사본을 지우지 않음(샘플 작업 예외)
  PARSE_STREAM_FINGERPRINT 1(기본) = 받은 파일이 지워지기 전에 **최소** 지문(source_id·updated_at·etag·size·
                        sha256)만 output/dedup/manifest.jsonl에 남긴다(O3, 백로그 server.md, 2026-10-14 재설계).
                        완전 중복(같은 sha256 — 다른 원천에서 와도)만 가린다: parse/source.py의 fetch_one이
                        받기 전(비멀티파트 ETag+크기)·받은 뒤(sha256) 둘 다 이 매니페스트와 대조해 중복이면
                        받지 않거나 파싱하지 않는다(DuplicateContent) — 이름·근사 내용 유사(사람만 보는 report.html
                        후보, 아무도 안 봄)는 뺐다. 0 = 끔(이전 동작과 바이트 동일, 중복 확인 자체도 안 함).

"엔진별 중간 결과"(output/parse/<엔진>/<문서>.json, P0 — common/artifacts.py의 "p0" 층)는 KEEP_RAW_LAYER와 무관하게
대표 결과를 만든 뒤 지운다(백로그 X2 ③, KEEP_ENGINE_CACHE=1이면 예외). P0 "원본 층 캐시"(output/parse/raw/**,
raw_engine_path·raw_vlm_path)는 문서 하나가 아니라 이미지·첨부 바이트 단위로 쌓여 다른 문서도 쓸 수 있어
KEEP_RAW_LAYER로 따로 다룬다.

안 함(스코프 밖, ponytail): 폴더 모드(dedup.run_folder·groups.csv·report.html)의 이름·근사 내용 유사 후보는
스트리밍에 안 들여온다 — 사람이 안 보는 산출물이었다(no-human-in-loop, 2026-10-14 사용자 결정). 보안 문서
복호화(cli/secure_docs.py)도 이 흐름에 자동으로 엮지 않는다(기존에도 수동 도구) — 쓰려면 --out을 PARSE_TMP
아래로 주고 그 안에서 decrypt→purge.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
from common.core.paths import APP_ROOT  # noqa: E402 — 폴더 재편 뒤 이 상수만 바뀌면 됨
from pipeline import config as pc  # noqa: E402 — pipeline 칸(S7c — 설정 객체 · cfg()·PIPE.env())

ROOT = APP_ROOT  # output/ 보안 경계(아래 _validate_under_out)·cwd 전부 여기 기준(옛 dev/, 코드 자체는 PKG_ROOT)
PY = sys.executable


def _validate_under_out(p, root, min_depth=2):
    """p가 root/output 아래 min_depth단 이상인지 확인 — 아니면 거부·종료(독립 보안 검토 BLOCKER 1).
    tmp_root()·attach_dir()가 같이 쓴다 — 둘 다 cleanup(rmtree·unlink)의 대상이라 범위가 좁아야 한다.
    root을 인자로 받는다(OP26 독립 검토 MINOR) — cli/parse_parallel.py가 자기 전역 ROOT로 같은 검증을
    그대로 재사용(복사 없이)할 수 있게 — 모듈 전역을 몰래 보면 그 전역을 시험에서 바꿔 끼울 때(이 파일
    자신의 selftest()가 하듯) 다른 모듈이 복사해 둔 버전과 어긋난다."""
    p = Path(p)
    root_out = (root / "output").resolve()
    rp = p.resolve()
    try:
        rel = rp.relative_to(root_out)
    except ValueError:
        rel = None
    if rel is None or rp == root_out or len(rel.parts) < min_depth:
        raise SystemExit(
            f"[stream] 경로 거부 — {p}(resolve: {rp})는 {root_out} 아래 {min_depth}단 이상 하위 폴더여야 함"
            "(예: output/_tmp_parse/stream) · '/'·홈·저장소 루트·out 바로 밑은 금지"
        )
    return rp


def tmp_root():
    """PARSE_TMP(기본 output/_tmp_parse/stream) — ROOT/output 아래 2단 이상 하위 폴더만 허용하고, 아니면 거부·종료
    (독립 보안 검토 BLOCKER 1 — `/`·홈 폴더·저장소 루트로 설정되면 cleanup_startup의 rmtree가 그걸 통째로 지운다)."""
    return _validate_under_out(pc.cfg().paths.parse_tmp or (ROOT / "output" / "_tmp_parse" / "stream"), ROOT)


def attach_dir_of(tmp):
    """tmp(스트리밍 작업 폴더)의 형제 attach/ 경로 — 순수 계산(검증 없음, check_residue 등 진단 전용 재사용).
    cleanup_startup은 tmp(보통 .../stream) 안만 치우므로 이 형제 폴더는 안 건드린다(독립 보안 검토 재검토 6번)."""
    return Path(tmp).parent / "attach"


def attach_dir():
    """post/attachments.py가 쓰는 첨부 임시 파일 폴더 — PARSE_TMP의 형제(output/_tmp_parse/attach).
    스트리밍 시작 청소(cleanup_startup)가 PARSE_TMP(.../stream)만 지우므로, 스트리밍이 아닌 다른 프로세스가
    같은 시각에 첨부를 파싱 중이어도 그 프로세스의 임시 파일이 지워지지 않는다(독립 보안 검토 재검토 6번).
    대신 쓰는 쪽이 파일 하나 끝낼 때마다 finally로 직접 지운다(시작 시 통째 청소 없음) — tmp_root()와 같은
    2단 이상 가드를 적용."""
    return _validate_under_out(attach_dir_of(tmp_root()), ROOT)


def _within(p, root):
    """p가 root 안(resolve 뒤 비교)인지 — 경로 조작·심링크로 허용 범위 밖을 지우지 않게(백로그 X2 안전 요건)."""
    try:
        rp, rr = Path(p).resolve(), Path(root).resolve()
    except OSError:
        return False
    return rp == rr or rr in rp.parents


def safe_rmtree(p, root):
    """root 안에서만 통째로 지움 — 밖이면 거부하고 알림. shutil.rmtree는 안의 심링크를 따라 들어가 지우지 않는다(표준 동작)."""
    p = Path(p)
    if not p.exists() and not p.is_symlink():
        return 0
    if not _within(p, root):
        print(f"[stream] 삭제 거부(허용 범위 밖): {p}", flush=True)
        return 0
    n = sum(1 for _ in p.rglob("*")) if p.is_dir() and not p.is_symlink() else 1
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p, ignore_errors=True)
    else:
        p.unlink(missing_ok=True)
    return n


def safe_unlink(p, root):
    p = Path(p)
    if not _within(p, root):
        print(f"[stream] 삭제 거부(허용 범위 밖): {p}", flush=True)
        return False
    if p.exists() or p.is_symlink():
        p.unlink()
        return True
    return False


def cleanup_startup(tmp, keep=()):
    """시작 시 지난 실행 잔여물 청소(강제 종료 대비, 백로그 X2 ④) — PARSE_TMP를 비우되 keep에 준 경로(보통 막
    얻은 잠금 파일)는 남긴다. **잠금을 먼저 얻은 뒤에만 불러야 한다**(독립 보안 검토 재검토 5번 — 청소가 잠금보다
    먼저면 동시에 시작한 두 프로세스가 둘 다 청소를 통과하고, 나중에 잠그는 쪽이 이긴 쪽이 일하는 중인 파일을
    지울 수 있다). 통째 rmtree 대신 안쪽부터 지워 keep 경로(와 그 경로로 가는 폴더)는 남긴다."""
    tmp = Path(tmp)
    keep_rp = {Path(k).resolve() for k in keep}
    if tmp.exists():
        removed = 0
        for p in sorted(tmp.rglob("*"), key=lambda x: -len(str(x))):  # 깊은 것부터(폴더는 비어야 지울 수 있음)
            if p.resolve() in keep_rp:
                continue
            try:
                if p.is_dir() and not p.is_symlink():
                    if not any(p.iterdir()):
                        p.rmdir()
                else:
                    p.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                pass
        if removed:
            print(f"[stream] 시작 시 임시 폴더 잔여물 {removed}개 지움 — {tmp}", flush=True)
    tmp.mkdir(parents=True, exist_ok=True)


def _du_gb(p):
    """폴더 전체 바이트 합(파일만, 심링크 제외) → GB."""
    total = 0
    for f in Path(p).rglob("*"):
        if f.is_file() and not f.is_symlink():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total / (1024**3)


def wait_for_space(tmp, max_gb, timeout_sec=1800, poll_sec=5):
    """PARSE_TMP 사용량이 PARSE_TMP_MAX_GB를 넘으면 다음 묶음을 받기 전에 대기(백로그 X2 ②). 0이면 제한 없음.
    ponytail: 고정 간격 폴링 — timeout_sec 넘으면 경고만 하고 진행(영원히 막히지 않게)."""
    if not max_gb:
        return
    t0 = time.time()
    while _du_gb(tmp) > max_gb:
        if time.time() - t0 > timeout_sec:
            print(f"[stream] PARSE_TMP_MAX_GB({max_gb}GB) 초과 대기 {timeout_sec}초 넘음 — 그대로 진행", flush=True)
            return
        print(f"[stream] PARSE_TMP 사용량 {_du_gb(tmp):.2f}GB > 상한 {max_gb}GB — 대기", flush=True)
        time.sleep(poll_sec)


def _run(module, args, env=None):
    """pipeline.*를 `-m`으로 서브프로세스(기존 cli/pipeline.py 방식과 같음) — 띄우기 전 메모리 문(common/resources.gated_popen),
    실패하면 예외."""
    from common.core import resources as RS
    from common.core.paths import child_env

    cmd = [PY, "-m", module, *map(str, args)]
    rc = RS.gated_popen(cmd, cwd=ROOT, env=env or child_env()).wait()  # child_env() — PYTHONPATH(deploy/) 보장(env=None 기본 호출 포함)
    if rc:
        raise SystemExit(f"[stream] 실패({rc}): {' '.join(cmd)}")


def _raw_dir():
    """P0 원본 층 캐시 폴더(raw_engine_path·raw_vlm_path가 실제로 쓰는 곳) — raw_root()는 그 'store' 인자(보통 output/parse)를
    돌려주므로 캐시 자체는 그 아래 raw/다. output/parse 전체를 보면 방금 만든 _rep·엔진 결과까지 '새 파일'로 잡혀 지워진다(실측 버그)."""
    from pipeline.shared.postprocess import raw_root

    return raw_root() / "raw"


def _raw_snapshot():
    r = _raw_dir()
    return set(r.rglob("*")) if r.exists() else set()


def _raw_cleanup(before):
    """KEEP_RAW_LAYER=0 — 이번 묶음이 새로 만든 P0 원본 층 캐시 파일만 지움(다른 문서·이전 실행 것은 안 건드림)."""
    r = _raw_dir()
    after = set(r.rglob("*")) if r.exists() else set()
    new = sorted((after - before), key=lambda p: -len(str(p)))  # 깊은 파일부터(빈 폴더 정리가 부모보다 먼저)
    n = 0
    for p in new:
        if p.is_file():
            n += 1 if safe_unlink(p, r) else 0
    for p in new:  # 비게 된 폴더 정리
        if p.is_dir() and p.exists() and not any(p.iterdir()):
            try:
                p.rmdir()
            except OSError:
                pass
    if n:
        print(f"[stream] KEEP_RAW_LAYER=0 — 이번 묶음이 만든 P0 원본 캐시 {n}개 지움", flush=True)


def _delete_engine_outputs(out_parse, batch):
    """엔진별 중간 결과(X2 ③) 삭제 — 성공·실패 모두 항상(KEEP_RAW_LAYER와 무관). 이미 지워졌으면 그냥 넘어간다(idempotent)
    — mark_done 전에 한 번(독립 보안 검토 MAJOR 4: 크래시가 mark_done 뒤·삭제 전에 나면 그 문서는 다시 안 받아 잔여물이
    영원히 남는다) · finally에서 다시 한 번(실패 경로 대비).
    KEEP_ENGINE_CACHE=1(기본 0 — 운영은 지움)이면 안 지움 — 합성 데이터 실험에서 "원문은 다시 안 긁는다" P0 캐시를
    그대로 두고 싶을 때만(독립 보안 검토 MINOR 6). 운영(실원본)에서는 켜지 않는다."""
    if pc.cfg().extract.cache.keep_engine_cache:
        return
    for n in batch:
        for eng_dir in out_parse.iterdir():
            if eng_dir.is_dir() and eng_dir.name not in ("_rep", "_images", "raw"):
                safe_unlink(eng_dir / f"{n}.json", out_parse)


def _pid_alive(pid):
    """그 PID의 프로세스가 지금 있는지 — 잠금 파일이 죽은 프로세스 것인지(자동 치움) 살아 있는 프로세스 것인지 구분.
    OP26 재검토(10-22) — tasklist의 실제 출력은 콘솔 코드페이지(cp949 등)인데 PYTHONUTF8=1(이 저장소 시험
    기본값)이 서 있으면 text=True가 UTF-8로 디코드를 강제해 비-UTF-8 바이트에서 백그라운드 리더 스레드가
    UnicodeDecodeError로 죽고 subprocess.run이 stdout=None을 돌려준다(실측: 한글 Windows PC). bytes로 받아
    errors="replace"로 직접 디코드해 그 경로를 없앤다 — 판정 자체(pid 문자열 포함 여부)는 그대로."""
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True)
        out = r.stdout.decode("utf-8", errors="replace") if r.stdout else ""
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _lock_path(tmp):
    return Path(tmp) / ".stream.lock"


def _acquire_lock(lock):
    """O_EXCL(동시에 둘이 만들면 하나만 성공) + pid 기록 — 원자적 생성 1회(실패하면 FileExistsError)."""
    fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode("utf-8"))
    finally:
        os.close(fd)


def _acquire_lock_or_refuse(lock, max_tries=50):
    """같은 PARSE_TMP로 스트리밍 두 개가 동시에 돌지 못하게(독립 보안 검토 MINOR 7, 재검토 5번).
    O_EXCL로 만들다 이미 있으면: 살아 있는 프로세스 것 → 거부·종료 / 죽은 프로세스 것 → 지우고 다시 시도.
    "지우고 다시 O_EXCL"을 재시도 루프로 — 두 프로세스가 동시에 같은 죽은 잠금을 보고 둘 다 지우려 해도
    O_EXCL 재생성은 하나만 이기고, 진 쪽은 다음 바퀴에서 이긴 쪽의 (살아 있는) pid를 보고 거부된다."""
    for _ in range(max_tries):
        try:
            _acquire_lock(lock)
            return
        except FileExistsError as err:
            try:
                other_pid = int(lock.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                other_pid = None
            if (
                other_pid is None
            ):  # 방금 O_EXCL로 만들어지고 pid를 아직 안 쓴 잠금 — 죽은 것으로 보고 지우면 둘 다 이김(부하 때 selftest X2 재현)
                try:
                    fresh = time.time() - lock.stat().st_mtime < 5
                except FileNotFoundError:
                    continue
                if fresh:
                    time.sleep(0.05)
                    continue
            if other_pid and _pid_alive(other_pid):
                raise SystemExit(f"[stream] 이미 돌고 있음(PID {other_pid}, 잠금 {lock}) — 동시에 두 번 돌리지 않음") from err
            print(f"[stream] 잠금 {lock}이 죽은 프로세스(PID {other_pid}) 것 — 치우고 다시 시도", flush=True)
            try:
                lock.unlink()
            except FileNotFoundError:
                pass  # 그 사이 다른 프로세스가 이미 지웠음 — 다음 바퀴에서 O_EXCL로 다시 경쟁
    raise SystemExit(f"[stream] 잠금({lock})을 못 얻음 — 다른 프로세스와 계속 경합")


def run(a, engines):
    """PARSE_STREAM=1일 때 cli/pipeline.py parse_module이 부른다 — a는 argparse 결과(parse 서브커맨드), engines는 콤마 목록.
    순서: 잠금(O_EXCL)을 먼저 얻고, 그 다음에야 시작 시 청소를 한다(독립 보안 검토 재검토 5번 — 청소를 먼저 하면
    동시에 시작한 두 프로세스가 둘 다 청소를 통과해 버릴 수 있다)."""
    from pipeline.extract import source as SRC

    tmp = tmp_root()
    tmp.mkdir(parents=True, exist_ok=True)  # 잠금 파일을 만들려면 폴더가 먼저 있어야 함
    lock = _lock_path(tmp)
    _acquire_lock_or_refuse(lock)
    try:
        cleanup_startup(tmp, keep={lock})  # 막 얻은 잠금은 남기고 나머지(지난 실행 잔여물)만 청소
        return _run_batches(a, engines, tmp, SRC)
    finally:
        lock.unlink(missing_ok=True)


def _source_meta_of(name, a, state, is_remote):
    """record_fingerprint의 source_id·etag·updated_at — 원천의 진짜 식별자(독립 검토 #3 재검토: file_name
    만으로는 서로 다른 경로·접두의 같은 이름 문서가 뭉개진다). 원격(s3://·rdb:)이면 source.py가 받을 때
    이미 써 둔 state/manifest.jsonl에서 그 이름의 행(uri·etag·updated_at)을 읽는다 — 이 함수가 불릴 땐
    _fetch_batch가 이미 끝나 그 줄이 있다. 폴더면 원본 폴더(a.source) 기준 file:// URI(parse_parallel.
    _manifest_row의 폴더 규칙과 같음, etag·updated_at은 없음 — 폴더는 추적할 상태가 없음)."""
    if is_remote:
        from common.core.contract import jl

        man_f = Path(state) / "manifest.jsonl"
        if man_f.exists():
            for r in jl(man_f):
                if r.get("file_name") == name:
                    return {"uri": r.get("uri") or r.get("key"), "etag": r.get("etag"), "updated_at": r.get("updated_at")}
        return {"uri": None, "etag": None, "updated_at": None}
    return {"uri": (Path(a.source) / name).resolve().as_uri(), "etag": None, "updated_at": None}


def _record_fingerprints(raw_dir, done_names, manifest_path, a, state, is_remote):
    """O3(백로그 server.md) — 원본이 지워지기 전에(이 함수 호출 뒤 raw_dir는 묶음이 끝나면 finally로 지워짐)
    파일마다 **최소** 지문(source_id·updated_at·etag·size·sha256)만 output/dedup/manifest.jsonl에 남긴다
    (2026-10-14 재설계 — 근사 중복은 뺐다, dedup.record_fingerprint 참고).
    **독립 검토(10-14 재검토) — done_names는 ok_now(대표 결과가 실제로 나온 문서, mark_done과 같은 집합)
    여야 한다, batch_ok(받기만 성공) 전체가 아니다.** 받기만 되고 파싱이 계속 실패하는 문서를 여기서
    기록하면 그 문서가 매니페스트에 "원본"으로 영구히 자리 잡아 같은 내용의 다른(진짜 처리 가능한) 사본이
    영영 중복으로 건너뛰어지는데, 실패 문서 쪽은 끝내 결과가 안 나와(publish도 안 됨) 그 내용 자체가
    통째로 사라진다 — 그래서 호출부(_run_batches)가 mark_done과 **같은 시점**(raw_dir가 아직 지워지기
    전, represent 뒤)에만 이 함수를 부른다.
    완전 중복 판정 자체는 받는 쪽(parse/source.py의 fetch_one)이 받기 전·받은 뒤에 이미 끝낸 뒤라
    done_names에는 중복이 없다 — 여기서는 나중에 다른 원천이 이 문서와 겹치는지 찾을 수 있게 지문만 쌓는다.
    PARSE_STREAM_FINGERPRINT(기본 켬, =0으로 끔) — 끄면 이 호출 자체를 안 해 이전 동작과 바이트 동일."""
    if not pc.cfg().extract.stream.fingerprint:
        return
    from pipeline.extract import dedup as DEDUP

    for n in done_names:
        meta = _source_meta_of(n, a, state, is_remote)
        DEDUP.record_fingerprint(raw_dir / n, manifest_path, source_id=meta["uri"], etag=meta["etag"], updated_at=meta["updated_at"])


def _fetch_batch(fetch_one, batch, dest):
    """묶음 중 받기 — ETag 불일치·완전 중복(ValueError, source.py _rdb_plan.fetch_one의 EtagMismatch·
    DuplicateContent)은 그 문서 하나만 건너뛰고(이미 rejected.jsonl 또는 매니페스트+처리 기록에 남음)
    나머지는 계속 받는다 → 받은 이름만. 전부 실패하면 빈 목록(독립 검토 BLOCK 1 — 전에는 하나만 틀려도
    배치 전체가 크래시해 처리 기록도 안 남고 영구 중단이었음)."""
    from pipeline.extract.source import DuplicateContent, EtagMismatch

    ok = []
    for n in batch:
        try:
            fetch_one(n, dest)
            ok.append(n)
        except (EtagMismatch, DuplicateContent) as e:  # 경로 탈출 ValueError는 잡지 않음(보안 fail-loud)
            print(f"[stream] {e}", flush=True)
    return ok


def _run_batches(a, engines, tmp, SRC):
    pc.checked("PARSE_TMP_MAX_GB")  # 디스크 상한 — 형식 틀리면 옛 float()처럼 실패(조용히 '제한 없음'이 되지 않게 — S7c1 리뷰)
    max_gb = pc.cfg().extract.cache.parse_tmp_max_gb  # S7c — 설정 객체(기본 0 = 제한 없음)
    batch_n = max(1, pc.cfg().extract.stream.batch)
    keep_raw = pc.cfg().extract.cache.keep_raw_layer
    is_s3 = SRC.is_remote(a.source)  # s3:// 목록이든 rdb:(AD44)든 처리 기록(mark_done) 대상 — 이름은 호출부 호환으로 유지
    out_parse = ROOT / "output" / "parse"
    out_parse.mkdir(parents=True, exist_ok=True)
    names, fetch_one, state = SRC.plan(a.source, ROOT / "output", a.source_limit, a.mode)
    if not names:
        print("[stream] 새로 처리할 문서 없음", flush=True)
        return
    from common.config import settings as C
    from common.core import resources as RS
    from common.core.paths import child_env

    # 설정 이름은 덮기 파일로(S7e3 B-1 — env dict의 설정 이름은 자식이 안 읽음): 문서×쪽 동시 수가 VLM_MAX_CONCURRENCY를 안 넘게 ·
    # 파싱 모듈은 LLM을 부르지 않음(LLM_BASE_URL 비움 — 기존 비-스트리밍 경로와 같게) · D4 — prepare의 --out(묶음 임시 폴더)은 지워지므로 건너뜀 기록은 밖에 누적
    env = C.child_env(
        child_env(),
        VLM_CONCURRENCY=str(RS.vlm_page_concurrency(a.workers, a.vlm_concurrency)),
        LLM_BASE_URL=None,
        PARSE_SKIPPED_LOG=str(out_parse / "_source" / "skipped.jsonl"),
    )
    done_total = 0
    for i in range(0, len(names), batch_n):
        batch = names[i : i + batch_n]
        wait_for_space(tmp, max_gb)
        raw_dir, prep_dir = tmp / "raw", tmp / "prepared"
        only = tmp / "batch_only.txt"
        before_raw = None if keep_raw else _raw_snapshot()
        try:
            batch_ok = _fetch_batch(fetch_one, batch, raw_dir)
            if not batch_ok:
                print(f"[stream] 묶음 {i // batch_n + 1} — {len(batch)}건 전부 거부(ETag 불일치) — 건너뜀", flush=True)
                continue
            only.write_text("\n".join(batch_ok) + "\n", encoding="utf-8")
            if pc.cfg().dev.stream_test_crash and i == 0:
                os._exit(17)  # 시험용 강제 종료 흉내(try/finally도 못 도는 진짜 kill) — 재시작 뒤 cleanup_startup이 치움
            _run("pipeline.extract.prepare", ["--src", raw_dir, "--out", prep_dir, "--only", only], env)
            args = ["--src", prep_dir, "--out", out_parse, "--procs", a.procs, "--workers", a.workers, "--engines", engines]
            _run("pipeline.extract.run_all", args + ["--docs-from", only], env)
            _run("pipeline.transform.represent.parse_qa", ["--parse", out_parse, "--src", prep_dir], env)
            from pipeline import stackcfg

            stack_file, stack = stackcfg.current(out_parse.parent)  # S8b — 엔진 구성 활성 판의 사본(진입점이 만든 것 — 없으면 여기서)
            if not stack.get("parse"):
                raise SystemExit("[stream] 엔진 구성이 비어 있음 — 먼저 set-stack")
            _run("pipeline.transform.represent.represent", ["--stack", stack_file, "--parse-dir", out_parse, "--src", prep_dir], env)
            idx = json.loads((out_parse / "_rep" / "index.json").read_text(encoding="utf-8"))["docs"]
            ok_now = {r["doc"] for r in idx if r["doc"] in batch_ok and r.get("engine")}
            # 독립 검토(10-14 재검토) — 지문은 ok_now(= mark_done 대상, 대표 결과가 실제로 나온 문서)에만
            # 남긴다. batch_ok(받기만 성공) 시점에 남기면 파싱이 계속 실패하는 문서가 매니페스트에 "원본"으로
            # 영구히 자리 잡아, 같은 내용의 다른 원천(진짜로 처리 가능한 사본)이 영영 중복으로 건너뛰어지고
            # 실패 문서 쪽은 결과가 끝내 안 나온다(아무도 publish 안 됨) — mark_done과 같은 시점(raw_dir가
            # 아직 지워지기 전)으로 옮겨 실패 문서는 지문을 남기지 않게 한다.
            _record_fingerprints(raw_dir, sorted(ok_now), ROOT / "output" / "dedup" / "manifest.jsonl", a, state, is_s3)
            _delete_engine_outputs(out_parse, batch_ok)  # mark_done보다 먼저(독립 보안 검토 MAJOR 4) — 순서가 중요
            SRC.mark_done(state, sorted(ok_now), is_s3)
            done_total += len(ok_now)
            print(f"[stream] 묶음 {i // batch_n + 1} — {len(batch)}건 중 받음 {len(batch_ok)}건, 대표 결과 {len(ok_now)}건", flush=True)
        finally:
            _delete_engine_outputs(out_parse, batch)  # 실패 경로 대비(이미 지웠으면 그냥 넘어감)
            if not keep_raw:
                _raw_cleanup(before_raw)
            if not pc.cfg().extract.cache.keep_local_originals:
                safe_rmtree(raw_dir, tmp)
                safe_rmtree(prep_dir, tmp)
            only.unlink(missing_ok=True)
    print(f"[stream] 끝 — 대상 {len(names)}개 중 대표 결과 {done_total}건", flush=True)
    storage_report(out_parse)


def storage_report(out_parse):
    """보관 용량 보고(10-05 사용자: 엔진별 결과를 보관하되 용량 문제가 생기면 수집 서버 경유 Object Storage로 넘김) —
    엔진별 중간 결과·P0 원본 층·대표 결과·그림, 남은 디스크. ENGINE_CACHE_WARN_GB(기본 20)·DISK_FREE_WARN_GB(기본 10) 넘으면 경고 한 줄."""
    import shutil as _sh

    out_parse = Path(out_parse)
    if not out_parse.exists():
        return {}
    special = {"_rep", "raw", "_images", "_source"}
    eng = sum(_du_gb(d) for d in out_parse.iterdir() if d.is_dir() and d.name not in special and not d.name.startswith("."))
    rep = {
        "엔진별": eng,
        "원본층(raw)": _du_gb(out_parse / "raw"),
        "대표(_rep)": _du_gb(out_parse / "_rep"),
        "그림(_images)": _du_gb(out_parse / "_images"),
    }
    free = _sh.disk_usage(out_parse).free / 1024**3
    print("[stream] 보관 용량 — " + " · ".join(f"{k} {v:.2f}GB" for k, v in rep.items()) + f" · 디스크 남음 {free:.1f}GB", flush=True)
    if eng > pc.cfg().extract.engine_cache_warn_gb or free < pc.cfg().extract.disk_free_warn_gb:  # S7c — 설정 객체(기본 20·10)
        print(
            "[stream] 경고: 보관 용량 기준 초과 — 엔진별 결과를 수집 서버 경유 Object Storage로 넘기거나 KEEP_ENGINE_CACHE=0 검토(백로그 S10)",
            flush=True,
        )
    return {**rep, "free_gb": free}
