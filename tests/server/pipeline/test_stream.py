"""pipeline.stream 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.stream --selftest`."""

import os
import threading
import time
from pathlib import Path

import pipeline.stream as M
from pipeline import config as pc
from pipeline.stream import (
    _acquire_lock,
    _acquire_lock_or_refuse,
    _delete_engine_outputs,
    _fetch_batch,
    _lock_path,
    _pid_alive,
    _within,
    attach_dir,
    cleanup_startup,
    safe_rmtree,
    safe_unlink,
    tmp_root,
    wait_for_space,
)


def selftest():
    # S9 — 옛 `global ROOT` → `M.<이름>`(모듈 전역 대입)
    import tempfile

    root = Path(tempfile.mkdtemp())
    (root / "a").mkdir()
    (root / "a" / "f.txt").write_text("x", encoding="utf-8")
    assert not _within(root / ".." / "outside", root)  # 범위 밖(상위로 탈출)
    assert _within(root / "a" / "f.txt", root)  # 범위 안
    outside = Path(tempfile.mkdtemp())
    assert safe_unlink(outside / "nope.txt", root) is False and not (outside / "nope.txt").exists()  # 범위 밖은 거부
    assert safe_rmtree(outside, root) == 0 and outside.exists()  # 폴더 전체도 범위 밖이면 거부
    n = safe_rmtree(root / "a", root)
    assert n == 1 and not (root / "a").exists()  # 범위 안은 지움
    tmp = Path(tempfile.mkdtemp()) / "leftover"
    (tmp / "x").mkdir(parents=True)
    (tmp / "x" / "f.json").write_text("{}", encoding="utf-8")
    cleanup_startup(tmp)
    assert tmp.exists() and not any(tmp.iterdir())  # 시작 시 청소 — 폴더는 남고 안은 빔
    wait_for_space(tmp, 0)  # 상한 0 = 즉시 통과(무한 대기 안 함)
    print("[selftest] X2 스트리밍 — 안전 삭제(범위 밖 거부)·시작 시 청소·크기 상한(0=통과) 통과")

    # 독립 보안 검토 재검토 5번: cleanup_startup(keep=...)은 지정한 경로(보통 막 얻은 잠금)는 남기고 나머지만 지움
    (tmp / "y").mkdir()
    (tmp / "y" / "junk.json").write_text("{}", encoding="utf-8")
    keep_file = tmp / ".stream.lock"
    keep_file.write_text("123", encoding="utf-8")
    cleanup_startup(tmp, keep={keep_file})
    assert keep_file.exists() and keep_file.read_text(encoding="utf-8") == "123"  # 남김
    assert not (tmp / "y").exists()  # 나머지는 지움
    keep_file.unlink()
    print("[selftest] X2 — cleanup_startup(keep=...)이 지정 경로는 남기고 나머지만 지움 통과")

    # 독립 보안 검토 BLOCKER 1: PARSE_TMP가 ROOT/output 아래 2단 이상이 아니면 tmp_root()가 거부·종료
    for bad in ("/", str(Path.home()), str(M.ROOT), str(M.ROOT / "output"), str(M.ROOT / "output" / "x")):
        with pc.PIPE.env(PARSE_TMP=bad):  # S7c — tmp_root()가 설정 객체로 읽음(os.environ 안 건드림)
            try:
                tmp_root()
                raise AssertionError(f"거부해야 할 PARSE_TMP를 받아들임: {bad}")
            except SystemExit:
                pass
    with pc.PIPE.env(PARSE_TMP=str(M.ROOT / "output" / "_tmp_parse" / "stream")):
        assert tmp_root() == (M.ROOT / "output" / "_tmp_parse" / "stream").resolve()  # 2단 이상은 통과
    print("[selftest] X2 — PARSE_TMP는 ROOT/output 아래 2단 이상만 허용('/'·홈·저장소 루트·out 바로 밑 거부) 통과")

    # 독립 보안 검토 MAJOR 4: 엔진별 중간 결과 삭제가 mark_done과 같은 함수(_delete_engine_outputs)를 쓰므로 두 호출
    # 지점(성공 경로의 mark_done 전·finally)이 따로 어긋날 수 없다 — 그 함수 자체가 제대로 지우는지 확인.
    op = Path(tempfile.mkdtemp())
    for eng in ("eng1", "eng2"):
        (op / eng).mkdir()
        (op / eng / "a.pdf.json").write_text("{}", encoding="utf-8")
    (op / "_rep").mkdir()
    (op / "_rep" / "a.pdf.json").write_text("{}", encoding="utf-8")  # 대표 결과는 안 건드려야 함
    _delete_engine_outputs(op, ["a.pdf"])
    assert not (op / "eng1" / "a.pdf.json").exists() and not (op / "eng2" / "a.pdf.json").exists()
    assert (op / "_rep" / "a.pdf.json").exists()  # _rep는 그대로
    _delete_engine_outputs(op, ["a.pdf"])  # 두 번째 호출(실패 경로 finally 흉내) — 이미 없어도 에러 없음
    print("[selftest] X2 — 엔진별 중간 결과 삭제(mark_done 전·finally 공용 함수)·_rep 보존·재호출 안전 통과")

    # 독립 보안 검토 MINOR 6: KEEP_ENGINE_CACHE=1이면 엔진별 중간 결과를 안 지움(합성 데이터 실험용 예외)
    (op / "eng1" / "b.pdf.json").write_text("{}", encoding="utf-8")
    with pc.PIPE.env(KEEP_ENGINE_CACHE="1"):  # S7c — _delete_engine_outputs가 설정 객체로 읽음
        _delete_engine_outputs(op, ["b.pdf"])
        assert (op / "eng1" / "b.pdf.json").exists()  # 기본(0)과 달리 지우지 않음
    print("[selftest] X2 — KEEP_ENGINE_CACHE=1이면 엔진별 중간 결과를 지우지 않음 통과")

    # 독립 보안 검토 MINOR 7: 살아 있는 프로세스의 잠금은 거부, 죽은 프로세스(PID 없음 가정)의 잠금은 치우고 통과
    lock_dir = Path(tempfile.mkdtemp())
    lock = _lock_path(lock_dir)
    assert _pid_alive(os.getpid())  # 자기 자신은 살아 있음
    _acquire_lock(lock)
    try:
        _acquire_lock(lock)
        raise AssertionError("같은 잠금을 두 번 만들 수 있으면 안 됨(O_EXCL)")
    except FileExistsError:
        pass
    assert int(lock.read_text(encoding="utf-8").strip()) == os.getpid()
    lock.unlink()
    print("[selftest] X2 — 잠금 파일 O_EXCL(중복 생성 거부)·pid 기록·_pid_alive 통과")

    # 독립 보안 검토 재검토 5번: 동시에 시작한 두 스레드 중 하나만 잠금을 얻고, 진 쪽은 이긴 쪽이 '작업 중'(잠금을
    # 쥔 채 작업 파일을 쓴 상태)인 폴더를 절대 건드리지 않아야 한다(cleanup_startup을 아예 못 부름).
    race_tmp = Path(tempfile.mkdtemp()) / "race"
    race_tmp.mkdir()
    barrier, results = threading.Barrier(2), {}

    def _race_worker(idx):
        lk = _lock_path(race_tmp)
        barrier.wait(timeout=5)  # 둘 다 같은 순간에 잠금을 시도하게
        try:
            _acquire_lock_or_refuse(lk, max_tries=3)
        except SystemExit:
            results[idx] = ("lost", None)
            return
        marker = race_tmp / f"work-{idx}.txt"
        marker.write_text("working", encoding="utf-8")
        time.sleep(0.2)  # '작업 중' 흉내 — 이 사이 진 쪽이 뭔가 지우면 안 됨
        cleanup_startup(race_tmp, keep={lk, marker})
        results[idx] = ("won", marker.exists())
        lk.unlink(missing_ok=True)

    threads = [threading.Thread(target=_race_worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    outcomes = [results.get(i) for i in range(2)]
    winners = [o for o in outcomes if o and o[0] == "won"]
    losers = [o for o in outcomes if o and o[0] == "lost"]
    assert len(winners) == 1 and len(losers) == 1, outcomes  # 정확히 하나만 이김
    assert winners[0][1] is True  # 이긴 쪽의 작업 파일이 그대로 있음(진 쪽이 안 지움)
    print("[selftest] X2 — 동시 시작 경쟁(스레드 2개): 잠금 하나만 승리·진 쪽은 이긴 쪽 작업 폴더를 안 건드림 통과")

    # 독립 보안 검토 재검토 6번: attach_dir()는 tmp_root() 밖(형제)이라 스트리밍 시작 청소가 안 건드림
    # (실제 저장소 output/을 건드리지 않게 ROOT를 임시 샌드박스로 바꿔서 확인 — 끝나면 반드시 되돌림)
    sandbox, old_root = Path(tempfile.mkdtemp()), M.ROOT
    (sandbox / "output").mkdir()
    try:
        M.ROOT = sandbox
        with pc.PIPE.env(PARSE_TMP=str(sandbox / "output" / "_tmp_parse" / "stream")):  # S7c — 설정 객체(os.environ 안 건드림)
            t_root, a_dir = tmp_root(), attach_dir()
            assert a_dir.parent == t_root.parent and a_dir != t_root and t_root not in a_dir.parents
            a_dir.mkdir(parents=True, exist_ok=True)
            marker = a_dir / "attach-keep.docx"
            marker.write_text("x", encoding="utf-8")
            lk = _lock_path(t_root)
            t_root.mkdir(parents=True, exist_ok=True)
            lk.write_text(str(os.getpid()), encoding="utf-8")
            cleanup_startup(t_root, keep={lk})  # stream/(t_root)만 청소 — attach/는 손대지 않음
            assert marker.exists()
    finally:
        M.ROOT = old_root
    print("[selftest] X2 — attach_dir()는 PARSE_TMP 형제 폴더라 스트리밍 시작 청소가 안 건드림 통과")

    # AD44 독립 검토 BLOCK 1 — 묶음 중 하나가 ETag 불일치(ValueError)여도 _run_batches가 쓰는 _fetch_batch가 그대로 전파해
    # 묶음 전체를 크래시시키지 않고, 나머지는 받아 이름만 돌려준다(여기서 바로 _run_batches를 돌리진 않지만 — 실제 호출부가
    # 쓰는 그 함수를 그대로 호출해 "fetch_one을 직접 부르지 않고" 확인).
    import tempfile

    dest = Path(tempfile.mkdtemp())

    from pipeline.extract.source import EtagMismatch

    def fake_fetch_one(name, d):
        if name == "bad":
            raise EtagMismatch(f"[source] ETag 불일치 — {name} 거부·기록")
        if name == "escape":
            raise ValueError("[source] 경로 조작 의심")
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(name, encoding="utf-8")

    ok = _fetch_batch(fake_fetch_one, ["good1", "bad", "good2"], dest)
    assert ok == ["good1", "good2"], ok
    assert (dest / "good1").exists() and (dest / "good2").exists() and not (dest / "bad").exists()
    try:
        _fetch_batch(fake_fetch_one, ["good3", "escape"], dest)
        raise AssertionError("경로 탈출 ValueError를 삼킴")
    except ValueError as e:
        assert not isinstance(e, EtagMismatch), e
    print("[selftest] AD44 — _fetch_batch: 묶음 중 ETag 불일치 1건은 건너뛰고 나머지는 받음(크래시 안 함)·경로 탈출은 그대로 크래시 통과")


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    selftest()
