"""pipeline.load.index 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.load.index --selftest`."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from common.config.settings import COMMON
from common.config.settings import child_env as settings_env
from common.core import index_cfg as IC
from common.core.paths import GLOSSARY_ROOT, PKG_ROOT, STACK_FILE
from pipeline.load import index_cfg as ICS

ROOT = PKG_ROOT
PY = sys.executable


def selftest():
    """가짜 없이 실제 bundle.py를 embed=none으로 두 설정(청크 크기 다름) 돌려 같은 _rep에서 색인 2개 — 폴더·id·완료 표시·재실행 건너뜀."""
    import tempfile

    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        rep = t / "parse" / "_rep"
        rep.mkdir(parents=True)
        body = "\n\n".join(f"문단 {i} 계약 단가 내용 " * 8 for i in range(30))
        (rep / "a.txt.json").write_text(
            json.dumps(
                {
                    "text": body,
                    "rep": {
                        "engine": "plaintext",
                        "format": ".txt",
                        "pages": 1,
                        "meta": {"pairs": [], "all": []},
                        "source": {"path": "a.txt", "sha256": "a" * 64, "uri": "file:///a.txt"},
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (rep / "index.json").write_text(json.dumps({"docs": [{"doc": "a.txt", "engine": "plaintext"}]}), encoding="utf-8")
        confs = []
        for n, cs in (("a", 200), ("b", 600)):
            p = t / f"{n}.json"
            p.write_text(json.dumps({"embed": "none", "chunk_size": cs, "summary": "lead"}), encoding="utf-8")
            confs.append(p)
        env = settings_env(
            INDEX_ROOT=str(t / "index"), EMBED_CACHE="0", CHUNK_SIZE=None, GLOSSARY_DIR=None, CLIENT_ROSTER=None
        )  # 하위 프로세스 — 덮기 파일(S7e2)
        base = [
            PY,
            "-m",
            "pipeline.load.index",
            "build",
            "--parse-dir",
            str(t / "parse"),
            "--src",
            str(t / "nosrc"),
            "--stack",
            str(STACK_FILE),
            "--skip-contract",
        ]  # S8b — 시험은 파일(서버 이미지에서도 판 표 없이)
        r = subprocess.run(
            base + ["--conf", str(confs[0]), "--conf", str(confs[1])], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8"
        )
        assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
        with COMMON.env(INDEX_ROOT=str(t / "index")):  # S7c — common index_cfg가 객체로 읽음(os.environ 안 건드림)
            ids = [ICS.index_id(json.loads(c.read_text(encoding="utf-8"))) for c in confs]
            assert sorted(ids) == IC.list_ids() and ids[0] != ids[1], (ids, IC.list_ids())
            n = [IC.info(i)["chunks"] for i in ids]
            assert n[0] > n[1] > 0, n  # 청크 크기가 작으면 청크가 더 많음
            assert all(IC.info(i)["dim"] == 0 and IC.info(i)["pg_schema"] is None for i in ids)
            r2 = subprocess.run(base + ["--conf", str(confs[0])], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
            assert r2.returncode == 0 and "건너뜀" in r2.stdout, r2.stdout[-1000:]  # 같은 _rep면 다시 안 만듦
            bad = t / "bad.json"
            bad.write_text(json.dumps({"chunk_size": 512, "oops": 1}), encoding="utf-8")
            r3 = subprocess.run(base + ["--conf", str(bad)], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
            assert r3.returncode == 2 and "모르는 칸" in r3.stderr, (r3.returncode, r3.stderr[-500:])
            r4 = subprocess.run(
                base[:-1] + ["--conf", str(confs[0]), "--force"], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8"
            )
            assert r4.returncode == 3 and IC.info(ids[0]) is not None, (
                r4.returncode,
                r4.stderr[-500:],
            )  # 계약 위반(_DONE 없음) → 시작 전 거부(기존 색인 유지)
            import shutil

            shutil.copytree(GLOSSARY_ROOT, t / "g")  # 사전만 바꿈(없음 → 있음) — --force 없이도 다시 빌드해야 함
            g_before = IC.info(ids[0])["inputs"]
            r5 = subprocess.run(
                base + ["--conf", str(confs[0])],
                cwd=ROOT,
                env=settings_env(env, GLOSSARY_DIR=str(t / "g")),  # op-09 — 자식은 덮기 파일로
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            g_after = IC.info(ids[0])["inputs"]
            assert r5.returncode == 0 and "건너뜀" not in r5.stdout and "입력이 바뀜(glossary)" in r5.stdout, (
                r5.stdout[-1500:] + r5.stderr[-800:]
            )
            assert g_before["glossary"] == "none" != g_after["glossary"] and {k: v for k, v in g_before.items() if k != "glossary"} == {
                k: v for k, v in g_after.items() if k != "glossary"
            }
            r6 = subprocess.run(
                base + ["--conf", str(confs[0])],
                cwd=ROOT,
                env=settings_env(env, GLOSSARY_DIR=str(t / "g")),  # op-09 — 자식은 덮기 파일로
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            assert r6.returncode == 0 and "건너뜀" in r6.stdout, r6.stdout[-800:]  # 같은 사전으로 한 번 더 → 건너뜀
            lk = t / "index" / f"{ids[1]}.lock"
            lk.write_text("999 다른 빌드", encoding="utf-8")  # 같은 id 빌드 중
            r7 = subprocess.run(
                base + ["--conf", str(confs[1]), "--force"], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8"
            )
            assert r7.returncode == 75 and "빌드 중" in r7.stderr and lk.exists() and IC.info(ids[1]) is not None, (
                r7.returncode,
                r7.stderr[-500:],
            )
            old = time.time() - 7 * 3600
            os.utime(lk, (old, old))  # 6시간 넘은 잠금 → 회수하고 빌드
            r8 = subprocess.run(
                base + ["--conf", str(confs[1]), "--force"], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8"
            )
            assert r8.returncode == 0 and "오래된 잠금 회수" in r8.stderr and not lk.exists(), (r8.returncode, r8.stderr[-500:])
    print(
        "[selftest] cli/index — 같은 _rep로 색인 2개(청크 크기별)·완료 표시·재실행 건너뜀·설정 오류 2·계약 위반 3·사전만 바뀐 재빌드·잠금 75·오래된 잠금 회수 통과"
    )


def test_main():  # 옛 main()의 `if "--selftest" in args:` 갈래
    selftest()
