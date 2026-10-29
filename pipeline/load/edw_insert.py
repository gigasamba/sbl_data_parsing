#!/usr/bin/env python3
"""EDW(SQL Server) = **벡터만** — 청크 키 + 임베딩 벡터만 넣고, 본문·출처·고객·계약·요약·그래프·키워드·질문 기록은 넣지 않는다
(사용자 2026-10-01: "edw에 vector 정보 말고 다른 메타 정보들 넣지 않게"). 본문·메타는 개발 서버(pgvector 또는 로컬 묶음)에만.

  chunk_key = '<원본 파일 sha256>:<청크 순번>' — 개발 서버 묶음(output/edw/bundle)·pgvector의 같은 청크를 가리킴(내용을 담지 않는 키)
  벡터 저장 = VECTOR 형(SQL Server 2025+, 차원 ≤1,998) 또는 narrow(차원마다 한 행 — 4,096차원 qwen3-vl-embedding은 이쪽, 자동 선택)
  검색: --edw        EDW 안에서 벡터 상위 k(usp_vec_topk) → 키를 개발 서버 청크로 바꿔 본문·출처·BM25·ID는 개발 서버에서
        --edw-client EDW 벡터를 개발 서버로 한 번 가져와(캐시) 코사인 → 같은 방식(현재 서버 방식)

접속(서버에서 파일·환경변수로):  EDW_CONN_FILE=<KEY=VALUE 파일>  또는 환경변수
  EDW_SERVER · EDW_PORT(1433) · EDW_DATABASE · EDW_USER(필수 — 서버 settings.yaml, S7e2: 코드 기본값 없앰) · EDW_PASSWORD · EDW_SCHEMA(AI)
  EDW_DRIVER = pymssql(기본, 시스템 ODBC 불필요) | pyodbc(+ EDW_ODBC_DRIVER, 예 "ODBC Driver 18 for SQL Server", EDW_ENCRYPT·EDW_TRUST_CERT)
  비밀번호는 파일·환경변수에만 — 로그·결과 파일에 남기지 않는다.

명령:
  check    접속·버전·VECTOR 형 · 권한
  deploy   벡터 테이블·프로시저(--vec native|narrow|auto) — 다시 실행해도 안전
  load     묶음 벡터 적재(이미 있는 키는 건너뜀, --replace면 그 문서 키를 지우고 다시)
  (검색·bench는 python -m mcp_server.services.search.edw_search)
"""

import argparse
import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
SQL = HERE / "sql"
from common.core.console import utf8_stdout  # noqa: E402 — 옆 import들과 같은 자리(앞 코드 뒤)
from common.store.edwdb import DB, conf, vec_table  # noqa: E402
from pipeline import config as pc  # noqa: E402 — pipeline 칸 설정 객체(S7c)

NATIVE_MAX = 1998  # SQL Server VECTOR(float32) 차원 상한 — 넘으면 narrow(적재 전용 — 10-14 edwdb에서 옮김)


def caps(db):
    v = db.q(
        "SELECT CAST(SERVERPROPERTY('ProductMajorVersion') AS INT) AS major, @@VERSION AS ver, DB_NAME() AS db, SUSER_SNAME() AS login"
    )[0]
    try:
        db.q("DECLARE @v VECTOR(2) = CAST('[1,2]' AS VECTOR(2)); SELECT 1 AS ok")
        v["vector"] = True
    except Exception:
        v["vector"] = False
    v["perms"] = [r["permission_name"] for r in db.q("SELECT permission_name FROM fn_my_permissions(NULL, 'DATABASE')")]
    return v


from common.core.contract import bundle_chunk_keys  # noqa: E402


def deploy(db, dim, vec="auto"):
    mode = vec if vec != "auto" else ("native" if caps(db)["vector"] and int(dim) <= NATIVE_MAX else "narrow")
    if mode == "native" and int(dim) > NATIVE_MAX:
        raise SystemExit(f"VECTOR 형은 {NATIVE_MAX}차원까지 — {dim}차원은 --vec narrow(또는 auto)")
    db.run_file(SQL / f"vec_{mode}.sql", DIM=int(dim))
    return mode


def existing_keys(db):
    mode, t = vec_table(db)
    if not t:
        raise SystemExit("EDW 벡터 테이블 없음 — 먼저 python -m pipeline.load.edw_insert deploy")
    return (
        mode,
        t,
        {
            r["chunk_key"]
            for r in db.q(f"SELECT DISTINCT chunk_key FROM [{db.schema}].[{t}]" + (" WHERE d = 0" if mode == "narrow" else ""))
        },
    )


def load(db, bundle, replace=False):
    import numpy as np

    B = Path(bundle)
    meta = json.loads((B / "meta.json").read_text(encoding="utf-8"))
    keys, vecs = bundle_chunk_keys(B), np.load(B / "vectors.npy")
    mode, t, have = existing_keys(db)
    s, t0 = db.schema, time.time()
    shas = sorted({k.split(":")[0] for k in keys})
    db.q("BEGIN TRANSACTION", fetch=False)  # 한 트랜잭션 — 실패하면 반쯤 들어간 벡터가 남지 않게
    try:
        deleted = 0
        if replace:
            for sha in shas:
                if any(k.startswith(sha + ":") for k in have):
                    db.q(f"DELETE [{s}].[{t}] WHERE chunk_key LIKE %s", (sha + ":%",), fetch=False)
                    deleted += 1
            have = {k for k in have if k.split(":")[0] not in shas}
        rows = [{"key": k, "v": [round(float(x), 6) for x in vecs[i]]} for i, k in enumerate(keys) if k not in have]
        for i in range(0, len(rows), 50):
            db.q(f"EXEC [{s}].[usp_vec_load] %s", (json.dumps(rows[i : i + 50]),), fetch=False)
        db.q("COMMIT", fetch=False)
    except Exception:
        db.q("IF @@TRANCOUNT > 0 ROLLBACK", fetch=False)
        raise
    return {
        "mode": mode,
        "dim": meta["dim"],
        "vectors_sent": len(rows),
        "skipped_existing": len(keys) - len(rows),
        "docs_replaced": deleted,
        "sec": round(time.time() - t0, 1),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "deploy", "load"])
    ap.add_argument("--bundle", default="output/edw/bundle")
    ap.add_argument("--vec", default="auto", choices=["auto", "native", "narrow"])
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--q", help="search 질의")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--questions", default="output/eval/questions.jsonl")
    ap.add_argument("--limit", type=int, default=50)
    a = ap.parse_args(argv)
    if a.cmd in ("deploy", "load") and not pc.cfg().load.edw_load:
        raise SystemExit(
            "개발 서버 구성은 EDW에 적재하지 않는다(사용자 결정 2026-10-01) — 벡터·메타는 PostgreSQL(pgvector)·로컬 묶음. "
            "EDW 벡터 적재가 꼭 필요하면 EDW_LOAD=1을 명시"
        )
    with DB(conf()) as db:  # VS8b R-7 — 끝나면 연결 닫음
        if a.cmd == "check":
            cp = caps(db)
            print(json.dumps({k: (v if k != "ver" else v.splitlines()[0]) for k, v in cp.items()}, ensure_ascii=False, indent=1))
            return
        meta = json.loads((Path(a.bundle) / "meta.json").read_text(encoding="utf-8"))
        if a.cmd == "deploy":
            mode = deploy(db, meta["dim"], a.vec)
            print(f"배포 완료: 스키마 {db.schema} · 벡터만 {mode}(차원 {meta['dim']}) — 본문·메타는 EDW에 넣지 않음")
        elif a.cmd == "load":
            print(json.dumps(load(db, a.bundle, a.replace), ensure_ascii=False))


if __name__ == "__main__":
    utf8_stdout()
    main()
