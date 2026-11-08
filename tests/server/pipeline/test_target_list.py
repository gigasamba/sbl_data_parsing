"""rn-05 — 대상 목록 `python -m pipeline.extract.candidate_pick list`(run_pipeline이 컨테이너 안에서 한 번 부름): EDW FileStorageMap에서
이름 키워드로 고르고(--filter — 없으면 모든 문서, 파일 크기 오름차순, 크기 없는 행 뺌) → 시작 자리·시험 개수·골라 돌리기 → 끝난 문서(gold doc)·영구 뺌(except_doc_info skip)
빼기 → FAQ 먼저(새 FAQ면 교체 + 전체, 아니면 gold에 없는 것만, 결과 없으면 전체) → 앞 max-docs개. 임시 SQLite EDW · gold는 실 pgvector 임시 스키마(goldseed.gold).
op-17 — 원천 목록(required.source.source_systems)이 있으면 그 원천 행만(대소문자 무관 — FAQ가 없으면 FAQ 교체도 안 함), 비우면 운영 5개 원천
(DEV-<n> 행 뺌), 목록 파일 docs는
FileStorageMap.source_system 값을 그대로 든다(키 첫 마디와 달라도)."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from common.config.settings import COMMON
from pipeline import config as pc
from pipeline.extract import candidate_pick as CP
from tests.server.pipeline.goldseed import gold, seed

# FileStorageMap 행 (id, s3_key, original_filename, file_size, source_system)
FSM = [
    (1, "SFDC/a/rfp_big.pdf", "RFP_big.pdf", 500, "SFDC"),
    (2, "SFDC/b/prop.docx", "proposal.docx", 100, "SFDC"),
    (3, "SFDC/c/x.pdf", "x.pdf", 50, "SFDC"),  # 키워드 없음
    (4, "SFDC/d/rfp_nosize.pdf", "rfp_nosize.pdf", None, "SFDC"),  # 크기 없음 — 빠짐
    (5, "SFDC/e/rfp_ok.pdf", "RFP_ok.pdf", 200, "SFDC"),
    (6, "SFDC/f/rfp_dup.pdf", "rfp_dup.pdf", 300, "SFDC"),
    (7, "SFDC/g/rfp_nogold.pdf", "rfp_nogold.pdf", 400, "SFDC"),
    (8, "FAQ/u1/q.xlsx", "q.xlsx", 10, "FAQ"),  # FAQ — 키워드 없음(FAQ 먼저일 때 덧붙음)
    (9, "FAQ/u2/rfp_faq.xlsx", "rfp_faq.xlsx", 20, "Faq"),  # FAQ이면서 키워드 — 원천 칸 대소문자 섞임(FAQ로 읽음)
    (10, "SFDC/h/dev_note.pdf", "dev_note.pdf", 30, "dev-1"),  # 원천은 칸 값(키 첫 마디 SFDC와 다름) — 키워드 없음
]
SRC = {k: src.upper() for _i, k, _n, size, src in FSM if size is not None}  # 키 → 원천(칸 값을 대문자로)
GOLD = ["SFDC/e/rfp_ok.pdf", "FAQ/u2/rfp_faq.xlsx"]  # gold doc 행 — 끝남
NEVER = {"SFDC/f/rfp_dup.pdf", "FAQ/u1/q.xlsx"}  # except_doc_info skip(내용 중복) — 영구 뺌 · rfp_nogold는 둘 다 아님(실패 — 다시 고름)
# 키워드 목록(크기순) = rfp_faq · prop · rfp_ok · rfp_dup · rfp_nogold · rfp_big (자리 0~5), FAQ 덧붙임 q.xlsx = 자리 6
K = {
    "faq2": "FAQ/u2/rfp_faq.xlsx",
    "prop": "SFDC/b/prop.docx",
    "ok": "SFDC/e/rfp_ok.pdf",
    "dup": "SFDC/f/rfp_dup.pdf",
    "nogold": "SFDC/g/rfp_nogold.pdf",
    "big": "SFDC/a/rfp_big.pdf",
    "faq1": "FAQ/u1/q.xlsx",
    "x": "SFDC/c/x.pdf",
    "dev": "SFDC/h/dev_note.pdf",
}
BOTH = [K["faq1"], K["faq2"]]
KW = ["--filter", "RFP,proposal"]  # 이름 키워드로 좁힘(기본은 모든 문서)
# (인자, 교체를 마친 FAQ 키(None이면 --faq-seen 없음), faq-sync 결과, 기대 키 순서, 실행 뒤 교체를 마친 키, 기대 faq-sync reset[, 원천 목록 설정])
CASES = [
    (
        [],
        None,
        None,
        ["faq1", "faq2", "x", "prop", "ok", "dup", "nogold", "big"],
        None,
        None,
    ),  # 기본(원천 목록 비움) = 운영 5개 원천 — DEV-<n> 행은 뺌(op-17 규칙 8) · 크기순 · 크기 없음 뺌
    ([], [], None, ["dev"], [], None, "dev-1"),  # 원천 DEV-1만(대소문자 무관) — FAQ가 목록에 없어 교체 확인도 안 함
    (
        [],
        [],
        {"faq_reset": 1, "gold": []},
        ["x", "prop", "ok", "dup", "nogold", "big"],
        [],
        None,
        "sfdc",
    ),  # SFDC만 — 키 첫 마디가 SFDC여도 dev-1 행은 빠짐
    ([], [], {"faq_reset": 1, "gold": []}, ["faq1", "faq2", "dev"], BOTH, True, "FAQ,DEV-1"),  # FAQ가 목록에 있으면 FAQ 교체
    (KW, None, None, ["faq2", "prop", "ok", "dup", "nogold", "big"], None, None),  # 키워드(대소문자 무시) · 크기순 · 크기 없음 뺌
    ([*KW, "--start-offset", "2", "--limit", "2"], [], None, ["ok", "dup"], [], None),  # 시험 개수 — FAQ 교체 건너뜀
    ([*KW, "--seqs", "5,1"], [], None, ["prop", "big"], [], None),  # 골라 돌리기(자리 정렬) — FAQ 건너뜀
    ([*KW, "--start-offset", "9"], None, None, [], None, None),  # 시작 자리가 목록 밖 — 빈 목록
    ([*KW, "--skip-done"], None, None, ["prop", "nogold", "big"], None, None),  # gold·영구 뺌 키를 뺌, 실패한 문서는 남음
    ([*KW, "--skip-done"], [], {"faq_reset": 1, "gold": []}, ["faq1", "faq2", "prop", "nogold", "big"], BOTH, True),  # 새 FAQ — 교체+전체
    (
        [*KW, "--skip-done"],
        BOTH,
        {"faq_reset": 0, "gold": [K["faq2"]]},
        ["prop", "nogold", "big"],
        BOTH,
        False,
    ),  # gold에 없는 q는 영구 뺌 — 안 채움
    ([*KW, "--skip-done"], BOTH, {"faq_reset": 0, "gold": []}, ["faq2", "prop", "nogold", "big"], BOTH, False),  # gold에 없는 FAQ만 채움
    (
        [*KW, "--skip-done"],
        [K["faq2"]],
        None,
        ["faq1", "faq2", "prop", "nogold", "big"],
        [K["faq2"]],
        True,
    ),  # 교체 결과 없음 — 전체, 기록 그대로
    ([*KW, "--skip-done", "--max-docs", "2"], None, None, ["prop", "nogold"], None, None),  # 앞 max-docs개
]


def _edw(tmp):
    """EDW 대역 sqlite 하나(FileStorageMap — 스키마 AI로 붙여 읽음) + gold doc 행(GOLD — gold() 안에서)."""
    path = Path(tmp) / "edw.sqlite"
    with COMMON.env(RUN_ENV="local"):
        seed([{"file_path": k, "source_system": k.split("/")[0]} for k in GOLD])
    cn = sqlite3.connect(path)
    cn.execute("CREATE TABLE FileStorageMap (id INTEGER, s3_key TEXT, original_filename TEXT, file_size INTEGER, source_system TEXT)")
    cn.executemany("INSERT INTO FileStorageMap VALUES (?, ?, ?, ?, ?)", FSM)
    cn.execute("CREATE TABLE DocFiles (id INTEGER, s3_key TEXT, original_filename TEXT, file_size INTEGER, source_system TEXT)")
    cn.executemany("INSERT INTO DocFiles VALUES (?, ?, ?, ?, ?)", [r for r in FSM if r[0] in (2, 3)])  # 다른 표(edw_file_table)
    cn.commit()
    cn.close()
    return path


def test_target_list():
    with tempfile.TemporaryDirectory() as tmp, gold():
        edw = _edw(tmp)
        out, seen_f = Path(tmp) / "targets.json", Path(tmp) / "faq_seen.txt"
        for args, seen, sync_out, want, seen_after, reset, *systems in CASES:
            resets = []
            argv = [*args, "--out", str(out)]
            if seen is not None:
                seen_f.write_text("".join(f"{k}\n" for k in seen), encoding="utf-8")
                argv += ["--faq-seen", str(seen_f)]
            with (
                COMMON.env(RUN_ENV="local", RDB_SQLITE=str(edw)),
                pc.PIPE.env(SOURCE_SYSTEMS=(systems or [None])[0]),
                mock.patch.object(CP, "faq_sync", lambda r, _p, so=sync_out, rs=resets: rs.append(r) or so),
                mock.patch("pipeline.shared.except_docs.skipped_keys", lambda: set(NEVER)),  # 기록 자체는 test_skip_docs
            ):
                assert CP._list_cmd(argv) == 0
            got = json.loads(out.read_text(encoding="utf-8"))
            assert [d["s3_key"] for d in got["docs"]] == [K[w] for w in want], (args, seen, got["docs"])
            allowed = {x.upper() for x in systems[0].split(",")} if systems else None
            total = (
                sum(1 for src in SRC.values() if (src in allowed if allowed else not src.startswith("DEV-")))
                if "--filter" not in args
                else 6
            )
            assert got["total"] == total and all(set(d) == {"seq", *CP.DOC_COLS} for d in got["docs"]), (args, got["total"])
            assert all(d["source_system"] == SRC[d["s3_key"]] for d in got["docs"])  # 칸 값을 대문자로(키에서 구하지 않음)
            if seen_after is not None:
                assert sorted(seen_f.read_text(encoding="utf-8").split()) == sorted(seen_after), args
            assert resets == ([] if reset is None else [reset]), (args, resets)


# required.edw.edw_file_table(RDB_FILE_TABLE) → 기대 키 순서(None = 설정 거부 — <스키마>.<표> 식별자만, SQL에 그대로 들어감)
TABLES = [
    ("SFDC.DocFiles", ["x", "prop"]),
    ("AI.FileStorageMap", ["faq1", "faq2", "x", "prop", "ok", "dup", "nogold", "big"]),  # 원천 목록 비움 — DEV 행 뺌
    ("AI.FileStorageMap WHERE 1=1 --", None),
    ("FileStorageMap", None),
]


def test_file_table():
    from common.config.settings import require_run_env

    with tempfile.TemporaryDirectory() as tmp, gold():
        edw, out, f = _edw(tmp), Path(tmp) / "targets.json", Path(tmp) / "settings.yaml"
        for table, want in TABLES:
            if want is None:  # 설정 파일에 적으면 시작 거부(시험 덮기 env.(…)는 틀린 꼴을 무시하므로 파일로)
                f.write_text(f"required:\n  env:\n    run_env: local\n  edw:\n    edw_file_table: '{table}'\n", encoding="utf-8")
                try:
                    require_run_env("시험", {"SETTINGS_FILE": str(f)}, sections=("pipeline",))
                    code = None
                except SystemExit as e:
                    code = e.code
                assert code == 2, (table, code)
                with COMMON.env(RUN_ENV="local", RDB_SQLITE=str(edw)), pc.PIPE.env(RDB_FILE_TABLE=table):
                    try:  # 덮은 값(--set·시험)이 틀리면 읽는 자리에서 실패(조용히 기본 표로 돌지 않게)
                        CP._list_cmd(["--out", str(out)])
                        raised = False
                    except ValueError:
                        raised = True
                assert raised, table
                continue
            with (
                COMMON.env(RUN_ENV="local", RDB_SQLITE=str(edw)),
                pc.PIPE.env(RDB_FILE_TABLE=table),
            ):
                assert CP._list_cmd(["--out", str(out)]) == 0, table
            got = json.loads(out.read_text(encoding="utf-8"))
            assert [d["s3_key"] for d in got["docs"]] == [K[w] for w in want], (table, got["docs"])


# op-17 — 원천 목록 값과 실행 환경(시작 관문 require_run_env): (run_env, source_systems, 기대 종료 코드 — None = 시작함)
GATE = [
    ("prd", "[DEV-1]", 2),  # 운영에서 DEV 원천 — 시작 거부
    ("prd", "[dev-3]", 2),  # 대소문자 무관
    ("prd", "[SFDC, faq, Other]", None),
    ("prd", "[]", None),  # 빈 목록 = 모든 원천
    ("dev", "[DEV-1]", None),
    ("local", "[dev-1, CRMS]", None),
    ("local", "[XYZ]", 2),  # 모르는 원천 — 설정 오류
    ("dev", "[DEV-100]", 2),  # DEV-<1~99>만
]


def test_source_systems_gate():
    from common.config.settings import require_run_env

    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "settings.yaml"
        for run_env, systems, want in GATE:
            f.write_text(f"required:\n  env:\n    run_env: {run_env}\n  source:\n    source_systems: {systems}\n", encoding="utf-8")
            try:
                got = require_run_env("시험", {"SETTINGS_FILE": str(f)}, sections=("pipeline",))
                code = None
            except SystemExit as e:
                got, code = None, e.code
            assert code == want and (want is not None or got == run_env), (run_env, systems, code)
