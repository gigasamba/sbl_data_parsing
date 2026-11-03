"""pipeline.shared.parse_run 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.shared.parse_run --selftest`."""

import os
from pathlib import Path

from common.core.artifacts import sha8
from pipeline.shared.parse_run import engine_version, prompt_id, purge_caches, raw_engine_path, raw_vlm_path


def selftest():
    import tempfile

    failures = []

    def check(name, cond):
        print(("OK   " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)

    check("prompt_id: name-version-sha8(text)", prompt_id("table-fix", "v1", "본문") == f"table-fix-v1-{sha8('본문')}")
    check("prompt_id: 글자가 다르면 id도 다름", prompt_id("p", "v1", "a") != prompt_id("p", "v1", "b"))
    check(
        "raw_engine_path: raw/<engine>@<버전>/<sha12>.json",
        str(raw_engine_path("S", "pymupdf", "1.2.3", "a" * 64)) == str(Path("S") / "raw" / "pymupdf@1.2.3" / ("a" * 12 + ".json")),
    )
    check(
        "raw_vlm_path: raw/vlm/<model>/<prompt_id>/<image_sha12>.json",
        str(raw_vlm_path("S", "qwen-vlm", "fig", "v1", "지시문", "b" * 64))
        == str(Path("S") / "raw" / "vlm" / "qwen-vlm" / prompt_id("fig", "v1", "지시문") / ("b" * 12 + ".json")),
    )
    check("engine_version: 없는 엔진 이름 → unknown", engine_version("no-such-engine-xyz") == "unknown")
    check("engine_version: stdlib 매핑 → stdlib", engine_version("html_stdlib") == "stdlib")

    # RV3 — purge_caches: 합성 캐시 폴더로 상한 넘김 → 오래된 것부터 지움, 제외 폴더는 안 건드림(server-runbook C7 —
    # raw/·_images는 '원본 삭제 뒤에도 남음'이라 정리 대상이 아니다, 엔진 원문·_rep·결정 기록도 그대로)
    with tempfile.TemporaryDirectory() as td:
        pd = Path(td)
        import time as _t

        old_ts = _t.time() - 86400
        for d, fname, ts in [
            ("_reread_p3/_vlm_cache", "c1.json", old_ts),
            ("_agent/_vlm_cache", "c2.json", old_ts),
            ("signals/page_signals@v1", "s1.json", old_ts),
            ("signals/page_signals@v1", "s2.json", None),
        ]:
            f = pd / d / fname
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x" * (1024 * 1024))  # 1MB씩
            if ts:
                os.utime(f, (ts, ts))
        keep_engine = pd / "pymupdf" / "doc1.pdf.json"
        keep_rep = pd / "_rep" / "doc1.pdf.json"
        keep_dec = pd / "_agent" / "decisions" / "doc1.pdf.json"
        keep_raw_vlm = pd / "raw" / "vlm" / "m" / "p" / "old.json"  # C7 '남음' — 대상 아님
        keep_images = pd / "_images" / "doc1" / "a.png"  # C7 '남음' — 대상 아님(index.jsonl 참조 보존)
        for f in (keep_engine, keep_rep, keep_dec, keep_raw_vlm, keep_images):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"y" * (1024 * 1024))
            os.utime(f, (old_ts, old_ts))  # 오래됐어도 제외 목록이라 지워지면 안 됨
        before = sum(1 for _ in pd.rglob("*") if _.is_file())
        res_ok = purge_caches(pd, max_gb=1000, log=lambda *a: None)  # 상한 안 넘음 — 아무것도 안 지움
        check("purge_caches: 상한 안 넘으면 지우지 않음", res_ok["removed"] == 0 and before == sum(1 for _ in pd.rglob("*") if _.is_file()))
        res = purge_caches(pd, max_gb=0.000001, log=lambda *a: None)  # 거의 0 — 대상 폴더 파일을 전부 지워야 함
        check("purge_caches: 상한 넘으면 오래된 것부터 지움", res["removed"] == 4)
        check(
            "purge_caches: raw·_images(C7 '남음')·엔진 원문·_rep·결정 기록은 그대로",
            all(f.exists() for f in (keep_engine, keep_rep, keep_dec, keep_raw_vlm, keep_images)),
        )
        check(
            "purge_caches: 지운 폴더는 빈 폴더까지 정리", not (pd / "_reread_p3").exists() and not (pd / "_agent" / "_vlm_cache").exists()
        )
        res_off = purge_caches(pd, max_gb=0)
        check("purge_caches: PARSE_CACHE_MAX_GB=0 → 꺼짐(skipped)", res_off.get("skipped") == "PARSE_CACHE_MAX_GB=0")
        outside = Path(tempfile.mkdtemp())
        (outside / "evil.json").write_bytes(b"z")
        purge_caches(pd, max_gb=0.000001, dirs=("../" + outside.name,), log=lambda *a: None)
        check("purge_caches: dirs에 탈출 경로가 섞여도 parse_dir 밖은 안 건드림", (outside / "evil.json").exists())

        # engine-qa BLOCK② — 캐시 루트(real) 안의 **중첩** 링크 디렉터리 안으로 들어가지 않음(rglob·os.walk followlinks만
        # 믿으면 링크를 따라가 캐시 루트 밖 파일까지 지울 수 있었음 — 루트 자체가 링크인 경우는 위 escape 시험이 이미 덮음,
        # 이건 중첩 사례). Windows는 symlink에 보통 관리자 권한이 필요해 **directory junction**(`mklink /J`, 권한 불필요)으로
        # 시험 — junction은 `os.path.islink()`가 False를 줘서 os.walk(followlinks=False)로는 안 걸러짐(실측), resolve() 기준
        # containment 확인(_contained_dirs)만이 막는다. symlink가 되는 환경(POSIX·Windows 개발자 모드)은 그걸로.
        pd2 = Path(td) / "pd2"
        outside2 = Path(tempfile.mkdtemp())
        protected = outside2 / "protected.json"
        protected.write_bytes(b"y" * (1024 * 1024))
        os.utime(protected, (old_ts, old_ts))
        vlm_cache = pd2 / "_agent" / "_vlm_cache"  # 실제 디렉터리(캐시 루트) — 이 안에 중첩 링크를 둠
        vlm_cache.mkdir(parents=True, exist_ok=True)
        (vlm_cache / "real.json").write_bytes(b"x" * (1024 * 1024))  # 진짜 캐시 파일(상한 넘기기용)
        os.utime(vlm_cache / "real.json", (old_ts, old_ts))
        link_dir = vlm_cache / "evil_link"
        link_kind = None
        try:
            os.symlink(str(outside2), str(link_dir), target_is_directory=True)
            link_kind = "symlink"
        except (OSError, NotImplementedError):
            if os.name == "nt":  # symlink 권한 없음 — junction(mklink /J)은 권한 없이도 됨
                import subprocess

                r = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link_dir), str(outside2)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )  # cmd 메시지는 로캘 코드페이지(cp949 등) — PYTHONUTF8=1과 충돌 방지
                if r.returncode == 0 and link_dir.is_dir():
                    link_kind = "junction"
        if link_kind:
            res_link = purge_caches(pd2, max_gb=0.000001, log=lambda *a: None)
            check(f"purge_caches: 캐시 루트 안의 중첩 링크({link_kind}) 디렉터리 안으로 안 들어감", protected.exists())
            check(
                "purge_caches: 링크 밖 진짜 캐시 파일은 정상적으로 지움",
                res_link["removed"] == 1 and not (vlm_cache / "real.json").exists(),
            )
        else:
            print("[selftest] purge_caches 링크 시험 — 이 환경은 symlink·junction 둘 다 생성 못 함(건너뜀)")

    print(f"\n{'모두 통과' if not failures else str(len(failures)) + '건 실패: ' + ', '.join(failures)}")
    if failures:
        raise SystemExit(1)


def test_main():  # 옛 `if __name__ == "__main__":` 의 --selftest 갈래
    selftest()
