#!/usr/bin/env python3
"""AD41 색인 빌더 — Data Structuring 모듈(구조화 build_bundle.py + 적재 pgvector_load.py)을 설정 파일 1개로 구동해 색인 1개를 만든다.
같은 _rep에서 설정이 다른 색인을 나란히(--conf 여러 개). 설계: docs/architecture.md §8 · 규칙: common/index_cfg.py.

  python cli/index.py id   <설정.json> ...                                 # index_id만 출력
  python cli/index.py build --conf a.json [--conf b.json] [--parse-dir output/parse] [--src output/prepared] [--pg] [--force]
  python cli/index.py list                                               # 완료된 색인(index.json) 목록

결과: INDEX_ROOT(기본 dev/out/index)/<index_id>/bundle/ + index.json(마지막에 씀 = 완료 표시 — 없으면 MCP가 안 씀).
index_id = 설정만의 지문(PG 스키마 이름이 안정). 다시 지을지는 따로 '입력 지문'(index.json inputs = _rep/index.json · 용어 사전
GLOSSARY_DIR · 고객 명부 CLIENT_ROSTER · stack.json · common 지문 · modules/structure 코드 지문)으로 판정 — 하나라도 바뀌면 --force 없이도 다시 빌드.
같은 index_id 동시 빌드는 INDEX_ROOT/<id>.lock(O_EXCL)으로 막음 — 이미 빌드 중이면 종료 코드 75, INDEX_LOCK_STALE_SEC(기본 6시간) 지난 잠금은 회수.
--pg면 PG 스키마 <PG_SCHEMA>_<index_id>에 deploy·load --replace(묶음 문서는 고치고, 묶음에 없는 문서는 안 지움 — pl-13). 설정이 없으면 이 명령을 안 씀 — 기본 색인은 pipeline.py 그대로.
종료 코드: 2 설정 오류 · 3 인계 폴더 계약 위반·dim 불일치 · 5 임베딩 연결 없음(api)·임베딩 없는 묶음의 --pg · 75 같은 색인 빌드 중."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from common.config.settings import cfg  # common 칸(S7c) · 자식 덮기 파일(S7e2)
from common.config.settings import child_env as settings_env
from common.core import index_cfg as IC  # check_id·root·info·bundle_dir·list_ids(공용)
from common.core.console import utf8_stdout
from common.core.paths import PKG_ROOT  # 공용 자산 루트(10-14 이미지 단위 분리) · 엔진 구성·용어집(S2 — resources/)
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.load import index_cfg as ICS  # normalize·load·index_id·env_for·inputs·pg_schema(빌더 전용, 10-14 이전)

HERE = Path(__file__).resolve().parent
ROOT = PKG_ROOT  # 하위 프로세스 cwd(공용 패키지 루트) — 10-14 분리 전엔 HERE.parent(data_pipeline/)

PY = sys.executable


def _run(module, args, env):
    cmd = [PY, "-m", module, *map(str, args)]
    print("$ " + " ".join(cmd), flush=True)
    rc = subprocess.run(cmd, cwd=ROOT, env=env).returncode
    if rc:
        raise SystemExit(f"실패({rc}): {' '.join(cmd)}")


def build_one(conf_path, a):
    try:
        conf = ICS.load(conf_path)
    except ValueError as e:
        print(f"[index] {e}", file=sys.stderr)
        raise SystemExit(2) from e
    from pipeline.transform.structure.chunking import CHUNKERS  # 이름 확인만(빌드는 bundle.py가)

    if conf["chunker"] not in CHUNKERS:
        print(f"[index] chunker 모름: {conf['chunker']} (있는 것: {sorted(CHUNKERS)})", file=sys.stderr)
        raise SystemExit(2)
    iid = ICS.index_id(conf)
    with _lock(iid):
        return _build_locked(conf, iid, a)


LOCK_STALE_SEC = float(pc.cfg().load.index_lock_stale_sec)  # S7c — 설정 객체(import 때 한 번, 옛 `or 6 * 3600` = 모델 기본값 21600.0)


class _lock:
    """같은 index_id 동시 빌드 막기 — INDEX_ROOT/<id>.lock을 O_EXCL로 만듦(bundle.tmp·스키마 적재 경합도 이걸로 막힘).
    이미 있으면 '빌드 중'으로 종료 코드 75 · INDEX_LOCK_STALE_SEC(기본 6시간)보다 오래된 잠금은 죽은 빌드로 보고 회수."""

    def __init__(self, iid):
        self.p = IC.root() / f"{iid}.lock"

    def __enter__(self):
        self.p.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')}".encode())
                os.close(fd)
                return self
            except FileExistsError as err:
                try:
                    age = time.time() - self.p.stat().st_mtime
                except FileNotFoundError:
                    continue  # 그 사이 풀림 — 다시 시도
                if age < LOCK_STALE_SEC:
                    who = self.p.read_text(encoding="utf-8", errors="replace").strip()
                    print(f"[index] {self.p.stem} 빌드 중(잠금 {self.p}, {who}, {age / 60:.0f}분 전) — 끝난 뒤 다시", file=sys.stderr)
                    raise SystemExit(75) from err
                print(f"[index] 오래된 잠금 회수({age / 3600:.1f}시간): {self.p}", file=sys.stderr)
                self.p.unlink(missing_ok=True)
        raise SystemExit(75)

    def __exit__(self, *exc):
        self.p.unlink(missing_ok=True)


def _build_locked(conf, iid, a):
    rep = Path(a.parse_dir) / "_rep"
    stack_args = ["--stack", a.stack]
    if a.stack:  # 엔진 구성 파일(PC 실험·시험 — 옛 사본과 같은 꼴)
        stack_bytes = Path(a.stack).read_bytes()
    else:  # pl-32 — 넘겨받은 판(STACK_VERSION), 없으면 여기서(서버 판 표·PC 파일)
        from pipeline import stackcfg

        st = stackcfg.current()
        stack_bytes = stackcfg.snapshot_bytes(st)
        stack_args = [] if st.version_id is None else ["--stack-version", str(st.version_id)]
    inputs = ICS.inputs(rep, stack_bytes)  # 재빌드 판정용 입력 지문(_rep·사전·명부·stack·common·구조화 코드) — index_id와 별개
    done = IC.info(iid)
    if done and done.get("inputs") == inputs and bool(done.get("pg_schema")) == a.pg and not a.force:
        print(f"[index] {iid} 이미 있음(입력 지문 같음) — 건너뜀(--force로 다시)", flush=True)
        return iid
    if done and done.get("inputs") and done["inputs"] != inputs:
        print(f"[index] {iid} 입력이 바뀜({', '.join(k for k in inputs if done['inputs'].get(k) != inputs[k])}) — 다시 빌드", flush=True)
    if not a.skip_contract:
        from common.core import contract

        bad = contract.check_parse(rep, sample=500)
        if bad:
            print(
                "[index] 파싱 인계 폴더가 계약과 다름 — " + " · ".join(bad[:5]) + " (실험 저장소 _rep면 --skip-contract)", file=sys.stderr
            )
            raise SystemExit(3)
    if conf["embed"] == "api" and not cfg().models.embed.base_url:
        print("[index] embed=api인데 임베딩 연결 없음(EMBED_BASE_URL)", file=sys.stderr)
        raise SystemExit(5)
    if conf["embed"] == "none" and a.pg:
        print("[index] embed=none(벡터 없음) 색인은 PostgreSQL에 안 넣음 — --pg 빼고 로컬 묶음으로", file=sys.stderr)
        raise SystemExit(5)
    d = IC.root() / iid
    (d / "index.json").unlink(missing_ok=True)  # 다시 만드는 동안은 '미완료'(MCP가 반쯤 바뀐 색인을 안 씀)
    d.mkdir(parents=True, exist_ok=True)
    (d / "conf.json").write_text(json.dumps(conf, ensure_ascii=False, indent=1), encoding="utf-8")
    env = ICS.env_for(conf)
    bundle = IC.bundle_dir(iid)
    _run(
        "pipeline.transform.structure.build_bundle",
        [
            "--parse-dir",
            a.parse_dir,
            "--src",
            a.src,
            "--embed",
            conf["embed"],
            "--summary",
            conf["summary"],
            "--chunk",
            conf["chunker"],
            *stack_args,
            "--out",
            bundle,
            *(["--path-prefix", a.path_prefix] if a.path_prefix else []),
        ],
        env,
    )
    meta = json.loads((bundle / "meta.json").read_text(encoding="utf-8"))
    if conf["dim"] is not None and meta["dim"] != conf["dim"]:
        print(
            f"[index] {iid}: 설정 dim {conf['dim']} ≠ 실제 {meta['dim']}(모델 {meta.get('embed_model')}) — 완료 표시 안 함", file=sys.stderr
        )
        raise SystemExit(3)
    schema = None
    if a.pg:
        schema = ICS.pg_schema(iid)
        penv = settings_env(env, PG_SCHEMA=schema)  # 색인 스키마 — 덮기 파일(S7e3 B-1: env dict의 설정 이름은 자식이 안 읽음)
        _run("pipeline.load.pgvector_load", ["deploy", "--bundle", bundle], penv)
        _run(
            "pipeline.load.pgvector_load", ["load", "--bundle", bundle, "--replace"], penv
        )  # pl-13 — 다시 빌드면 같은 문서도 새 묶음으로 고침(안 붙이면 건너뛰어 옛 청크가 남음)
    info = {
        "index_id": iid,
        "conf": conf,
        "inputs": inputs,
        "pg_schema": schema,
        "embed": meta["embed"],
        "embed_model": meta.get("embed_model"),
        "dim": meta["dim"],
        "docs": meta["docs"],
        "chunks": meta["chunks"],
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (d / "index.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[index] {iid} 완료 — 청크 {meta['chunks']} · 차원 {meta['dim']}" + (f" · PG {schema}" if schema else ""), flush=True)
    return iid


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_id = sub.add_parser("id")
    p_id.add_argument("conf", nargs="+")
    sub.add_parser("list")
    b = sub.add_parser("build", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    b.add_argument("--conf", action="append", required=True, help="색인 설정 JSON(여러 번 — 같은 _rep에서 차례로)")
    b.add_argument("--parse-dir", default="output/parse")
    b.add_argument("--src", default="output/prepared")
    b.add_argument("--stack", default=None, help="엔진 구성 파일(PC 실험·시험 — 비우면 넘겨받은 판·활성 판, pl-32)")
    b.add_argument("--path-prefix", default=pc.cfg().load.edw_path_prefix)
    b.add_argument("--pg", action="store_true", help="PostgreSQL 스키마 <PG_SCHEMA>_<index_id>에 적재")
    b.add_argument("--force", action="store_true")
    b.add_argument("--skip-contract", action="store_true", help="_rep 계약 점검(_DONE·sources) 건너뜀 — stack_matrix 실험 저장소 _rep용")
    a = ap.parse_args(args)
    if a.cmd == "id":
        for c in a.conf:
            try:
                print(ICS.index_id(ICS.load(c)), c)
            except ValueError as e:
                print(f"[index] {e}", file=sys.stderr)
                raise SystemExit(2) from e
    elif a.cmd == "list":
        for i in IC.list_ids():
            d = IC.info(i)
            print(json.dumps({k: d.get(k) for k in ("index_id", "conf", "dim", "chunks", "pg_schema", "created")}, ensure_ascii=False))
    else:
        # ponytail: 차례로 — 병렬은 CPU·임베딩 서버를 다툼, 필요하면 프로세스를 나눠 띄움(폴더·스키마가 달라 충돌 없음)
        for c in a.conf:
            build_one(c, a)


if __name__ == "__main__":
    utf8_stdout()
    main()
