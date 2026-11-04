"""PC 가짜 EDW sqlite 하나 만들기 — valid_env/edw/*.sql(스키마마다 한 파일: ai·crms·las·sfdc)을 파일 하나에 넣는다
(docs/prd/ops.md#op-03). 코드는 이 파일을 스키마 이름마다 ATTACH해 `AI.FileStorageMap` 같은 이름으로 읽는다
(common.store.mssql.standin). 쓰려면 settings.yaml `required.edw.sqlite`에 경로를 적는다.
사용: python -m validation.e2e.edw_standin [--out valid_env/edw/edw.sqlite]
"""

import argparse
import sqlite3
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import PROJ_ROOT
from common.store.mssql import STANDIN_SCHEMAS

SRC = PROJ_ROOT / "valid_env" / "edw"


def build(out):
    out = Path(out)
    out.unlink(missing_ok=True)
    cn = sqlite3.connect(out)
    try:
        for s in STANDIN_SCHEMAS:
            cn.executescript((SRC / f"{s.lower()}.sql").read_text(encoding="utf-8"))
        cn.commit()
        return sorted(r[0] for r in cn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
    finally:
        cn.close()


def main(argv=None):
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(SRC / "edw.sqlite"))
    a = ap.parse_args(argv)
    print(f"씀: {a.out} — 표 {', '.join(build(a.out))}")


if __name__ == "__main__":
    main()
