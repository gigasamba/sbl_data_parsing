"""mcp_server.services.search.search_svc 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.search_svc`."""

import json
import sys
import time
from pathlib import Path

from mcp_server import config as mc
from mcp_server.schemas.evidence import _EVIDENCE_BASE_KEYS, _MANIFEST_EXTRA_KEYS
from mcp_server.services.search import search_svc as M
from mcp_server.services.search.search_svc import do_search
from mcp_server.services.search.server_state import _STATE, CALLER
from mcp_server.services.search.shaping import evidence_status
from tests.server.mcp.test_server_state import _mk_bundle  # 옛 server_state._mk_bundle(자기 점검 공용 — S9에 server_state 시험 파일로 옮김)

ROOT = (
    Path(M.__file__).resolve().parents[3]
)  # 옛 main.py의 ROOT(= mcp_server/의 부모, 저장소 루트)와 같은 값 — selftest만 씀(옛 search_svc.py의 줄 — `__file__`은 모듈 것으로)


def _selftest_search_notes_no_race():
    """be-qa 리뷰(S12) — do_search가 공유 Retriever의 note(임베딩 실패·확장·재순위·최신성)를 self 속성이 아니라
    search_ex() 반환값으로 읽는지(동시 요청에서 A의 note가 B 응답에 섞이면 안 됨). embed_query를 질문별로 다르게(절반은
    느린 실패) 만들어 섞일 여지를 늘려 놓고 다수 스레드로 동시 호출 — 각 응답의 note가 자기 질문 것인지 확인."""
    import tempfile
    import threading

    import numpy as np

    from mcp_server.services.search import retriever as RT

    d = Path(tempfile.mkdtemp())
    (d / "meta.json").write_text(json.dumps({"dim": 4, "embed": "api"}), encoding="utf-8")
    (d / "docs.jsonl").write_text(
        json.dumps({"file_path": "x.txt", "file_name": "x.txt", "file_sha256": "f" * 64, "doc_format": ".txt"}) + "\n", encoding="utf-8"
    )
    (d / "chunks.jsonl").write_text(
        json.dumps(
            {
                "doc": 0,
                "seq": 0,
                "page": 1,
                "line_start": 1,
                "line_end": 1,
                "chunk_text": "단가 100 USD",
                "n_terms": 2,
                "bbox": None,
                "section": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    np.save(d / "vectors.npy", np.zeros((1, 4), dtype="float32"))

    n_threads = 80
    barrier = threading.Barrier(n_threads)

    def fake_embed(meta, text):
        barrier.wait(timeout=30)  # 다 같이 시작 — 겹칠 확률을 최대로(한 스레드가 죽어도 나머지가 영원히 기다리지 않게)
        if "FAIL" in text:
            time.sleep(0.03)  # 레이스가 있으면 이 사이에 다른 스레드가 note를 덮어씀(스크래치 시험으로 36/80 재현 확인)
            raise RuntimeError("가짜 임베딩 장애")
        time.sleep(0.03)
        return np.zeros(4, dtype="float32")

    real_embed, real_switch = RT.embed_query, sys.getswitchinterval()
    RT.embed_query = fake_embed  # retriever.py가 이 전역 이름으로 부름(모듈 내 교체)
    sys.setswitchinterval(0.0001)  # GIL을 자주 넘겨 스레드 전환을 늘림(레이스 노출 확률 ↑)
    old = {k: _STATE.get(k) for k in ("R", "bundle", "checked_at")}
    bad = []
    # PC 루트 settings.yaml(mcp.server.store: pg 등)이 새지 않게 — 30초 뒤 재적재가 실제 PG로 가면 한 스레드가 죽어 barrier가 멈췄음(10-29)
    _env = mc.senv(MCP_STORE="local", MCP_BUNDLE=str(d), MCP_QUERY_LOG_DIR=str(d / "qa_log"))
    try:
        R = RT.Retriever(d)
        _STATE["R"], _STATE["bundle"], _STATE["checked_at"] = R, d, time.time()

        def worker(i):
            q = f"FAIL-{i} 질문" if i % 2 == 0 else f"OK-{i} 질문"
            out = do_search(
                q, k=3, methods=["vector", "bm25"], decompose=False
            )  # vector를 넣어야 질의 임베딩이 불림(S85 — bm25만이면 임베딩 생략)
            has_note = any("임베딩 실패" in n for n in out.get("notes", []))
            if has_note != (i % 2 == 0):
                bad.append((q, out.get("notes")))

        ths = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        assert not bad, f"note가 다른 요청과 섞임: {bad[:5]}"
    finally:
        _env.close()
        RT.embed_query = real_embed
        sys.setswitchinterval(real_switch)
        _STATE.clear()
        for k, v in old.items():
            if v is not None:
                _STATE[k] = v
    print(f"[selftest] do_search — 동시 {n_threads}건에서 note가 자기 요청 것(안 섞임) 통과")


def _selftest_copy_group():
    """R2-c 요건① — 같은 메일의 다른 형식(.eml/.msg)이 evidence 슬롯을 독점하지 않고 한 슬롯(대표) + variants로
    묶이는지."""
    from mcp_server.services.search import retriever as RT

    body = "MRH-MAB-01 기술이전 관련 문의드립니다 1차 트랜스퍼 배치 완료 추가 배치 3회 계획 단가 434000000 KRW"
    docs = [
        {"file_path": "MAIL-X.eml", "file_name": "MAIL-X.eml", "file_sha256": "1" * 64, "doc_format": ".eml"},
        {"file_path": "MAIL-X.msg", "file_name": "MAIL-X.msg", "file_sha256": "2" * 64, "doc_format": ".msg"},
    ]
    chunks = [
        {"doc": 0, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "chunk_text": body, "n_terms": 10, "bbox": None, "section": None},
        {
            "doc": 1,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "Date: 2025-04-08\n" + body,
            "n_terms": 10,
            "bbox": None,
            "section": None,
        },
    ]
    d = _mk_bundle(docs, chunks)
    old = {k: _STATE.get(k) for k in ("R", "bundle", "checked_at")}
    try:
        _STATE["R"], _STATE["bundle"], _STATE["checked_at"] = RT.Retriever(d), d, time.time()
        out = do_search("단가는?", k=5, methods=["bm25"], decompose=False)
        assert [e["file_name"] for e in out["evidence"]] == ["MAIL-X.eml"], out["evidence"]
        assert out["evidence"][0]["variants"] == ["MAIL-X.msg"], out["evidence"][0]
        assert any("사본 그룹" in n for n in out["notes"]), out["notes"]
    finally:
        _STATE.clear()
        _STATE.update({k: v for k, v in old.items() if v is not None})
    print("[selftest] R2-c 사본 그룹 — 한 슬롯 + variants 통과")


def _selftest_copy_group_rep_text():
    """engine-qa CONCERN(QA066) 재발 방지 — 최상위 순위가 이미지(OCR) 청크라 배치 수 문장이 빠진 실제 사례를
    재현: mailshot(.png)이 더 짧아 BM25 1위로 뽑혀도, 대표 슬롯(자리는 그대로 1위)의 내용은 형식이 더 믿을만한
    eml·msg 중에서 고르고(QA066에선 eml) 그 안에 빠진 문장(배치)이 있는지. 대표 자신의 파일명은 variants에
    없어야(요건②)."""
    from mcp_server.services.search import retriever as RT

    docs = [
        {"file_path": "mailshot_MAIL-X.png", "file_name": "mailshot_MAIL-X.png", "file_sha256": "1" * 64, "doc_format": ".png"},
        {"file_path": "MAIL-X.eml", "file_name": "MAIL-X.eml", "file_sha256": "2" * 64, "doc_format": ".eml"},
        {"file_path": "MAIL-X.msg", "file_name": "MAIL-X.msg", "file_sha256": "3" * 64, "doc_format": ".msg"},
    ]
    full_body = (
        "From 박지아 To 김서윤 Subject MRH-MAB-01 기술이전 일정 공유 단가는 434000000 KRW 입니다 "
        "1차 트랜스퍼 배치 완료 추가 배치 3회 계획입니다 첨부 일정표 확인 부탁드립니다"
    )
    png_text = "From 박지아 To 김서윤 Subject MRH-MAB-01 기술이전 일정 공유 단가는 434000000 KRW 입니다 첨부 일정표 확인 부탁드립니다"  # OCR — 배치 문장 빠짐
    chunks = [
        {
            "doc": 0,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": png_text,
            "n_terms": len(png_text.split()),
            "bbox": None,
            "section": None,
        },
        {
            "doc": 1,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": full_body,
            "n_terms": len(full_body.split()),
            "bbox": None,
            "section": None,
        },
        {
            "doc": 2,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": full_body,
            "n_terms": len(full_body.split()),
            "bbox": None,
            "section": None,
        },
    ]
    d = _mk_bundle(docs, chunks)
    old = {k: _STATE.get(k) for k in ("R", "bundle", "checked_at")}
    try:
        _STATE["R"], _STATE["bundle"], _STATE["checked_at"] = RT.Retriever(d), d, time.time()
        out = do_search("단가는?", k=5, methods=["bm25"], decompose=False)
        rep = out["evidence"][0]
        assert rep["file_name"] in ("MAIL-X.eml", "MAIL-X.msg"), rep  # ① 대표 텍스트는 형식 우선(이미지 아님)
        assert "배치" in rep["text"], rep["text"]  # ① 이미지에만 없던 문장이 대표 텍스트에 있음
        assert rep["file_name"] not in rep["variants"] and "mailshot_MAIL-X.png" in rep["variants"]  # ② 대표 자신은 variants에 없음
    finally:
        _STATE.clear()
        _STATE.update({k: v for k, v in old.items() if v is not None})
    print("[selftest] R2-c 사본 대표 텍스트 — 형식 우선(QA066 재발 방지)·대표 자신 variants 제외 통과")


def _selftest_query_log():
    """OP6 — do_search가 output/qa_log/qa_log.jsonl(여기선 임시 폴더)에 호출자·질문·근거 id·지연을 남기는지(PG 없는
    로컬 묶음도) · MCP_QUERY_LOG=0이면 아무것도 안 남는지(바이트 동일 — 파일 자체가 생기지 않음)."""
    import tempfile

    from mcp_server.services.search import qa_log

    d = _mk_bundle(
        [{"file_path": "x.txt", "file_name": "x.txt", "file_sha256": "8" * 64, "doc_format": ".txt"}],
        [
            {
                "doc": 0,
                "seq": 0,
                "page": 1,
                "line_start": 1,
                "line_end": 1,
                "chunk_text": "단가는 100 USD",
                "n_terms": 3,
                "bbox": None,
                "section": None,
            }
        ],
    )
    logdir = Path(tempfile.mkdtemp())
    _STATE.clear()
    _env = mc.senv(MCP_STORE="local", MCP_BUNDLE=str(d), MCP_QUERY_LOG_DIR=str(logdir))  # 설정 객체 덮기(S7d)
    tok = CALLER.set("mcp:selftest")
    try:
        do_search("단가는?", k=3, methods=["bm25"], decompose=False)
        recs = [json.loads(x) for x in qa_log.log_path().read_text(encoding="utf-8").splitlines()]
        assert len(recs) == 1 and recs[0]["question"] == "단가는?" and recs[0]["asked_by"] == "mcp:selftest", recs
        assert recs[0]["hits"] and recs[0]["hits"][0]["via"] == "k", recs[0]["hits"]  # 근거 via(검색 방법) 남음

        with mc.senv(MCP_QUERY_LOG="0"):
            do_search("단가는?", k=3, methods=["bm25"], decompose=False)
            recs2 = qa_log.log_path().read_text(encoding="utf-8").splitlines()
            assert len(recs2) == 1, recs2  # 끔 — 더 안 늘어남(새 줄 없음)
    finally:
        CALLER.reset(tok)
        _env.close()
        _STATE.clear()
    print("[selftest] OP6 — 질의 기록(output/qa_log, 호출자·질문·근거 id·지연) · MCP_QUERY_LOG=0이면 기록 없음 통과")


def _selftest_evidence_rep_path():
    """OP21(S78) — do_search 근거에 AI.ParsingMeta의 '파싱 결과 경로'(rep_uri, find_rep_path가 쓴 같은 rep_key) —
    가짜 EDW(RDB_SQLITE)에 그 문서의 doc_key 행이 있을 때만 붙고(원본 경로는 기존 source_uri 칸 그대로,
    바이트 동일) · 없는 문서·RDB_SQLITE 미설정(기본 서버)은 칸 자체가 없음(바이트 동일, 새 칸 0개) ·
    rep_bucket이 "file://<폴더>"(폴더 저장소 환경 시험, 사용자 결정 10-08)면 s3:// 접두를 덧씌우지 않고 그
    값 그대로 rep_key를 이음(find_rep_path)."""
    import tempfile

    from common.store import parsing_meta_db as PM

    doc_key = "a" * 64
    docs = [
        {"file_path": "x.txt", "file_name": "x.txt", "file_sha256": doc_key, "doc_format": ".txt", "source_uri": "s3://src-bkt/orig/x.txt"},
        {"file_path": "y.txt", "file_name": "y.txt", "file_sha256": "b" * 64, "doc_format": ".txt"},
    ]
    chunks = [
        {
            "doc": i,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "단가는 100 USD",
            "n_terms": 3,
            "bbox": None,
            "section": None,
        }
        for i in range(2)
    ]
    d = _mk_bundle(docs, chunks)

    pm_path = Path(tempfile.mkdtemp()) / "edw.sqlite"
    db = PM.SqliteStore(str(pm_path))
    row = {
        **{c: None for c in PM.COLUMNS},
        "source_system": "FSM",
        "source_key": "k/x.txt",
        "doc_key": doc_key,
        "parse_date": "2026-10-08",
        "status": "active",
        "status_at": None,
        "parse_status": "ok",
        "rep_bucket": "rep-bkt",
        "rep_key": "Parsing-Result/FSM/k/x.txt/",
        "_reparse": False,
    }
    db.insert_new([row])
    db.close()

    _STATE.clear()
    _env = mc.senv(
        MCP_STORE="local", MCP_BUNDLE=str(d), RDB_SQLITE=str(pm_path), RUN_ENV="local"
    )  # 설정 객체 덮기(S7d) · 가짜 EDW(RDB_SQLITE)는 local 전용 — 이미지에서도 시험 안에서만 local(이미지 관문 10-30)
    try:
        on = do_search("단가는?", k=5, methods=["bm25"], decompose=False)
        by_name = {e["file_name"]: e for e in on["evidence"]}
        assert by_name["x.txt"]["rep_uri"] == "s3://rep-bkt/Parsing-Result/FSM/k/x.txt/", by_name["x.txt"]
        assert by_name["x.txt"]["source_uri"] == "s3://src-bkt/orig/x.txt", by_name["x.txt"]  # 원본 경로 칸 불변
        assert "rep_uri" not in by_name["y.txt"], by_name["y.txt"]  # ParsingMeta에 없는 문서 — 새 칸 없음

        _STATE.clear()
        with mc.senv(RDB_SQLITE=None):  # 설정 자체가 없음(기본 서버) — 바이트 동일(새 칸 0개)
            off = do_search("단가는?", k=5, methods=["bm25"], decompose=False)
            for e in off["evidence"]:
                assert "rep_uri" not in e, e

        _STATE.clear()
        with mc.senv(RDB_SQLITE=str(pm_path), MCP_EVIDENCE_PATHS="0"):  # 명시적으로 꺼도 바이트 동일
            gated = do_search("단가는?", k=5, methods=["bm25"], decompose=False)
            for e in gated["evidence"]:
                assert "rep_uri" not in e, e

        # 폴더 저장소 환경 시험(사용자 결정 10-08) — PM_BUCKET=file://<폴더>로 게시된 행은 rep_bucket에 그
        # "file://..." 값이 그대로 들어감(parsing_meta.plan()) — find_rep_path가 s3:// 접두를 덧씌우지 않아야 함
        pm_path2 = Path(tempfile.mkdtemp()) / "edw2.sqlite"
        db2 = PM.SqliteStore(str(pm_path2))
        doc_key2 = "c" * 64
        row2 = {
            **{c: None for c in PM.COLUMNS},
            "source_system": "FSM",
            "source_key": "k/z.txt",
            "doc_key": doc_key2,
            "parse_date": "2026-10-08",
            "status": "active",
            "status_at": None,
            "parse_status": "ok",
            "rep_bucket": "file:///srv/rag/publish",
            "rep_key": "FSM/k/z.txt/2026-10-08/rep.md",
            "_reparse": False,
        }
        db2.insert_new([row2])
        assert PM.find_rep_path(db2, doc_key2) == "file:///srv/rag/publish/FSM/k/z.txt/2026-10-08/rep.md"
        db2.close()
    finally:
        _env.close()
        _STATE.clear()
    print(
        "[selftest] OP21 — do_search 근거 rep_uri(AI.ParsingMeta, find_rep_path 같은 키) 있을 때만 붙음 · "
        "원본 경로(source_uri) 불변 · 미설정·MCP_EVIDENCE_PATHS=0은 바이트 동일 통과"
    )


def _selftest_evidence_gate():
    """R3(AD42) — found/weak/none·근거별 low_score 계산·표시."""
    ev_found = [{"text": "계약 C-001 금액은 100 USD", "score": 0.9}]
    assert evidence_status("C-001 계약 금액은?", ev_found, min_score=0.1) == ("found", [False])
    ev_off_topic = [{"text": "관련 없는 내용", "score": 0.9}]  # 핵심어(C-001) 없음 → weak
    assert evidence_status("C-001 계약 금액은?", ev_off_topic, min_score=0.1) == ("weak", [False])
    ev_low = [{"text": "계약 C-001 금액은 100 USD", "score": 0.01}]  # 점수 문턱 미달 → weak·low_score
    assert evidence_status("C-001 계약 금액은?", ev_low, min_score=0.1) == ("weak", [True])
    assert evidence_status("C-001 계약 금액은?", [], min_score=0.1) == ("none", [])
    assert evidence_status("아무 질문", ev_found, min_score=None) == ("found", [None])  # 문턱 없으면 low_score 안 매김

    sha = "9" * 64
    d = _mk_bundle(
        [{"file_path": "x.txt", "file_name": "x.txt", "file_sha256": sha, "doc_format": ".txt"}],
        [
            {
                "doc": 0,
                "seq": 0,
                "page": 1,
                "line_start": 1,
                "line_end": 1,
                "chunk_text": "단가는 100 USD",
                "n_terms": 3,
                "bbox": None,
                "section": None,
            }
        ],
    )
    _STATE.clear()
    _env = mc.senv(MCP_STORE="local", MCP_BUNDLE=str(d))  # 설정 객체 덮기(S7d)
    try:
        none = do_search("색인에 없는 XYZ999-계약은?", k=3, methods=["bm25"], decompose=False)  # BM25 0건
        assert none["evidence_status"] == "none", none

        with mc.senv(SEARCH_MIN_SCORE="99999"):  # 무조건 문턱 미달
            weak = do_search("단가는?", k=3, methods=["bm25"], decompose=False)
            assert weak["evidence_status"] == "weak" and weak["evidence"][0]["low_score"] is True, weak
    finally:
        _env.close()
        _STATE.clear()
    print("[selftest] R3 근거 게이트 — found/weak/none·근거별 low_score 통과")


def _selftest_index_id():
    """AD41 — search(index_id): 같은 질문이 색인마다 그 색인의 청크로 답함 · 없음/형식 위반/미완료 → {"error","indexes"} ·
    index_id 없으면 기본 색인(응답에 index_id 칸 없음 — 전과 같음) · api 색인인데 EMBED_MODEL이 다르면 거부."""
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp())
    docs = [{"file_path": "x.txt", "file_name": "x.txt", "file_sha256": "7" * 64, "doc_format": ".txt"}]
    row = {"doc": 0, "page": 1, "line_start": 1, "line_end": 1, "n_terms": 3, "bbox": None, "section": None}
    base = _mk_bundle(docs, [{**row, "seq": 0, "chunk_text": "기본 색인 단가는 100 USD"}])
    ids = {"0000aaaa": "작은 청크 단가는 200 USD", "0000bbbb": "큰 청크 단가는 300 USD"}
    for iid, txt in ids.items():
        shutil.copytree(_mk_bundle(docs, [{**row, "seq": 0, "chunk_text": txt}]), root / iid / "bundle")
        (root / iid / "index.json").write_text(
            json.dumps(
                {"index_id": iid, "pg_schema": None, "inputs": {"glossary": "0badf00d" if iid == "0000bbbb" else "none", "roster": "none"}}
            ),
            encoding="utf-8",
        )
    (root / "0000cccc" / "bundle").mkdir(parents=True)  # 만드는 중(완료 표시 없음)
    api = root / "0000dddd"
    shutil.copytree(_mk_bundle(docs, [{**row, "seq": 0, "chunk_text": "api 색인"}]), api / "bundle")
    (api / "bundle" / "meta.json").write_text(json.dumps({"dim": 4, "embed": "api", "embed_model": "m-a"}), encoding="utf-8")
    (api / "index.json").write_text(json.dumps({"index_id": "0000dddd", "pg_schema": None}), encoding="utf-8")
    _STATE.clear()
    # 설정 객체 덮기(S7d) — GLOSSARY_DIR·CLIENT_ROSTER는 인계 파일(common.core.terms)이 env로 읽어 senv가 os.environ에도 쓰고 되돌림
    _env = mc.senv(GLOSSARY_DIR=None, CLIENT_ROSTER=None, MCP_STORE="local", MCP_BUNDLE=str(base), INDEX_ROOT=str(root), EMBED_MODEL="m-b")
    try:
        d0 = do_search("단가는?", k=3, methods=["bm25"], decompose=False)
        assert "index_id" not in d0 and "100 USD" in d0["evidence"][0]["text"], d0
        for iid, txt in ids.items():
            r = do_search("단가는?", k=3, methods=["bm25"], decompose=False, index_id=iid)
            assert r["index_id"] == iid and r["evidence"][0]["text"] == txt, r
            drift = [n for n in r["notes"] if "용어 사전" in n]  # 0000bbbb만 다른 사전으로 만든 색인 → 경고 1줄(거부 아님)
            assert len(drift) == (1 if iid == "0000bbbb" else 0), (iid, r["notes"])
        again = do_search("단가는?", k=3, methods=["bm25"], decompose=False, index_id="0000aaaa")
        assert again["evidence"][0]["text"] == ids["0000aaaa"]  # 캐시된 Retriever 재사용
        for bad in ("0000ffff", "0000cccc", "../x", "ABCDEF12"):
            e = do_search("단가는?", k=3, methods=["bm25"], decompose=False, index_id=bad)
            assert "error" in e and e["indexes"] == ["0000aaaa", "0000bbbb", "0000dddd"], (bad, e)
        e = do_search("단가는?", k=3, methods=["bm25"], decompose=False, index_id="0000dddd")
        assert "error" in e and "m-a" in e["error"], e  # 질의·색인 임베딩 모델 불일치 거부
        assert "100 USD" in do_search("단가는?", k=3, methods=["bm25"], decompose=False)["evidence"][0]["text"]  # 기본 색인은 그대로
    finally:
        _env.close()
        _STATE.clear()
    print("[selftest] AD41 index_id — 색인별 검색·캐시·없음/미완료/형식 오류·모델 불일치 거부·사전 차이 경고·기본 색인 불변 통과")


def _selftest_search_client_arg():
    """AD38 — do_search(client=...)가 Retriever.search_ex로 그대로 전달되는지(MCP 계층 통합 확인).
    꺼짐(기본)이면 바이트 동일(둘 다 나옴, 앞으로만) · SEARCH_CLIENT_HARD=1이면 다른 고객은 근거에서 완전히 빠짐."""
    docs = [
        {"file_path": "a.txt", "file_name": "a.txt", "file_sha256": "a" * 64, "doc_format": ".txt", "client": "Acme Co"},
        {"file_path": "b.txt", "file_name": "b.txt", "file_sha256": "b" * 64, "doc_format": ".txt", "client": "Other Co"},
    ]
    chunks = [
        {
            "doc": i,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "단가는 100 USD",
            "n_terms": 3,
            "bbox": None,
            "section": None,
        }
        for i in range(2)
    ]
    d = _mk_bundle(docs, chunks)
    _STATE.clear()
    _env = mc.senv(MCP_STORE="local", MCP_BUNDLE=str(d))  # 설정 객체 덮기(S7d)
    try:
        with mc.senv(SEARCH_CLIENT_HARD=None):
            off = do_search("단가는?", k=5, methods=["bm25"], decompose=False, client="Acme Co")
            assert {e["file_name"] for e in off["evidence"]} == {"a.txt", "b.txt"}, off["evidence"]  # 꺼짐 — 둘 다(앞으로만, 안 빠짐)

        with mc.senv(SEARCH_CLIENT_HARD="1"):
            on = do_search("단가는?", k=5, methods=["bm25"], decompose=False, client="Acme Co")
            assert {e["file_name"] for e in on["evidence"]} == {"a.txt"}, on["evidence"]  # 켬 — Other Co는 완전히 빠짐
    finally:
        _env.close()
        _STATE.clear()
    print("[selftest] AD38 do_search(client=) — MCP 계층에서도 SEARCH_CLIENT_HARD 꺼짐/켬 전달 통과")


def _selftest_entity_split():
    """BR23 — 비교 질문(고객 2명이 같이 나옴)에서 한쪽 고객 문서 3개가 점수를 다 차지해 다른 쪽 고객 문서 1개가
    top-k 밖으로 밀리는 재현(a1~a3=Acme Co, b1=Beta Inc, 질문 용어는 a쪽과 더 많이 겹침).
    고객별 하위 검색(search_svc._gather)이 b1을 끌어와 근거에 포함."""
    docs = [
        {"file_path": f"a{i}.txt", "file_name": f"a{i}.txt", "file_sha256": str(i) * 64, "doc_format": ".txt", "client": "Acme Co"}
        for i in range(1, 4)
    ] + [{"file_path": "b1.txt", "file_name": "b1.txt", "file_sha256": "b" * 64, "doc_format": ".txt", "client": "Beta Inc"}]
    chunks = [
        {
            "doc": i - 1,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "단가 비교 안내",
            "n_terms": 3,
            "bbox": None,
            "section": None,
        }
        for i in range(1, 4)
    ] + [{"doc": 3, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "chunk_text": "단가", "n_terms": 1, "bbox": None, "section": None}]
    d = _mk_bundle(docs, chunks)
    q = "Acme Co와 Beta Inc 중 단가 비교 안내 문서를 찾아줘."  # '문서를 찾아'(FIND_DOC_RE) — 집계 경로로 안 새게(aggregate.py 기존 규칙)
    _STATE.clear()
    _env = mc.senv(MCP_STORE="local", MCP_BUNDLE=str(d))  # 설정 객체 덮기(S7d)
    try:
        on = do_search(q, k=2, methods=["bm25"], decompose=False)
        assert "b1.txt" in {e["file_name"] for e in on["evidence"]}, on["evidence"]  # Beta Inc 근거가 끌려옴
        assert any("엔티티 분해" in n for n in on["notes"]), on["notes"]
    finally:
        _env.close()
        _STATE.clear()
    print("[selftest] BR23 엔티티 분해 — 고객 2명 비교 질문의 한쪽 고객 누락을 하위 검색으로 보정 통과")


def _selftest_br50_client_scope():
    """BR50 — 고객 범위 단일 규칙(clientscope.py) 종단 점검. 합성 2고객 묶음(Acme Co·Beta Inc)으로:
    꺼짐(기본, SEARCH_CLIENT_HARD 미설정)이면 client 인자를 줘도 core 검색·개념(concept)·그림(image)·집계(aggregate)·
    키 기반 단건 조회(get_document·get_image·lookup_term) 전부 바이트 동일(둘 다 그대로 나옴, 알려진 한계 — I류 도구는
    client를 안 줘도 바이트 동일) · SEARCH_CLIENT_HARD=1 + client="Acme Co" 명시면 다른 고객(Beta Inc) 근거·그림·
    구조화 집계 행이 전부 빠지고, 키 조회는 거부(error)된다."""
    import csv

    sha_a, sha_b = "a" * 64, "b" * 64
    docs = [
        {
            "file_path": "a.txt",
            "file_name": "a.txt",
            "file_sha256": sha_a,
            "doc_format": ".txt",
            "client": "Acme Co",
            "contract_no": "C-A01",
            "meta_confirmed": True,
            "contract": {"amount": 1000, "currency": "USD"},
        },
        {
            "file_path": "b.txt",
            "file_name": "b.txt",
            "file_sha256": sha_b,
            "doc_format": ".txt",
            "client": "Beta Inc",
            "contract_no": "C-B01",
            "meta_confirmed": True,
            "contract": {"amount": 500, "currency": "USD"},
        },
    ]
    chunks = [
        {
            "doc": 0,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "바이러스 불활화 공정 Acme 전용",
            "n_terms": 5,
            "bbox": None,
            "section": None,
        },
        {
            "doc": 1,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "바이러스 불활화 공정 Beta 전용",
            "n_terms": 5,
            "bbox": None,
            "section": None,
        },
    ]
    d = _mk_bundle(docs, chunks)
    (d / "concept_chunk.jsonl").write_text(
        "\n".join(
            json.dumps(x)
            for x in [
                {"concept_id": "PROC.VI", "chunk_key": f"{sha_a}:0", "count": 3},
                {"concept_id": "PROC.VI", "chunk_key": f"{sha_b}:0", "count": 2},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gdir = d / "glossary"
    gdir.mkdir()
    fields = [
        "concept_id",
        "canonical",
        "category",
        "synonyms",
        "abbreviations",
        "weak_synonyms",
        "broader",
        "related",
        "context_required",
        "case_sensitive",
        "definition_ko",
        "definition_en",
        "source",
        "owner",
        "status",
        "updated",
    ]
    with (gdir / "domain_terms.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerow(
            {
                "concept_id": "PROC.VI",
                "canonical": "Viral Inactivation",
                "category": "process",
                "synonyms": "바이러스 불활화",
                "abbreviations": "VI",
                "weak_synonyms": "",
                "broader": "",
                "related": "",
                "context_required": "",
                "case_sensitive": "Y",
                "definition_ko": "",
                "definition_en": "",
                "source": "",
                "owner": "",
                "status": "approved",
                "updated": "",
            }
        )

    _STATE.clear()
    # 설정 객체 덮기(S7d) — GLOSSARY_DIR는 인계 파일이 env로 읽어 senv가 os.environ에도 쓰고 되돌림 · SEARCH_CLIENT_HARD=None은 옛 pop
    _env = mc.senv(MCP_STORE="local", MCP_BUNDLE=str(d), GLOSSARY_DIR=str(gdir), SEARCH_CLIENT_HARD=None)
    _hard = None
    try:
        # 꺼짐(기본) — client를 줘도 전과 바이트 동일
        off = do_search("바이러스 불활화 공정", k=5, methods=["bm25"], decompose=False, client="Acme Co")
        assert {e.get("file_name") for e in off["evidence"] if e.get("file_name")} >= {"a.txt", "b.txt"}, off["evidence"]

        # 켬 — SEARCH_CLIENT_HARD=1 + client="Acme Co" 명시
        _hard = mc.senv(SEARCH_CLIENT_HARD="1")
        on = do_search("바이러스 불활화 공정", k=5, methods=["bm25"], decompose=False, client="Acme Co")
        assert "b.txt" not in {e.get("file_name") for e in on["evidence"]}, on["evidence"]  # core·concept 둘 다 빠짐(F)
        assert "a.txt" in {e.get("file_name") for e in on["evidence"]}, on["evidence"]  # 자기 고객 근거는 그대로

    finally:
        if _hard is not None:
            _hard.close()
        _env.close()
        _STATE.clear()
    print(
        "[selftest] BR50 — clientscope 종단 점검: 꺼짐(client만 줘도) 바이트 동일(core·concept·image·"
        "get_document·get_image·lookup_term) · SEARCH_CLIENT_HARD=1+client 명시면 다른 고객 근거·그림·구조화 집계 "
        "전부 제외, 키 조회는 거부 · client 안 주면(I류) 알려진 한계로 그대로 통과"
    )


def _selftest_evidence_rdb_meta():
    """AD44 — do_search 근거(_evidence)에 RDB manifest 메타(doc_type·supersedes_doc_id·is_deleted·contract_id·updated_at·
    company, version은 있으면 우선) 붙는지 — 실제 synth-meta-rdb 표(contract_sjm_mab_2025 행, pipeline import 안 함).
    manifest가 그 문서를 모르면(두 번째 문서) 칸 자체가 없고, manifest가 아예 없으면 바이트 동일(새 칸 0개)."""
    import csv

    base = ROOT / "valid_env" / "edw" / "meta_rdb" / "doc_location.csv"
    if not base.exists():  # 이미지에는 예시 데이터 없음 → 건너뜀(10-14)
        print(f"[selftest] AD44 근거 RDB 메타 건너뜀 — 예시 표 없음({base})")
        return
    with open(base, encoding="utf-8-sig", newline="") as f:
        row = next(r for r in csv.DictReader(f) if r["doc_id"] == "contract_sjm_mab_2025")

    man_doc = "contract_sjm_mab_2025"
    other_doc = "no_manifest_doc"
    docs = [
        {"file_path": f"{man_doc}.txt", "file_name": man_doc, "file_sha256": "c" * 64, "doc_format": ".txt"},
        {"file_path": f"{other_doc}.txt", "file_name": other_doc, "file_sha256": "d" * 64, "doc_format": ".txt"},
    ]
    chunks = [
        {
            "doc": i,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "계약기준금액 안내",
            "n_terms": 2,
            "bbox": None,
            "section": None,
        }
        for i in range(2)
    ]
    d = _mk_bundle(docs, chunks)

    man_path = d / "manifest.jsonl"
    man_path.write_text(
        json.dumps(
            {
                "file_name": man_doc,
                "doc_type": row["doc_type"],
                "version": row["version"],
                "supersedes_doc_id": row["supersedes_doc_id"],
                "contract_id": row["contract_id"],
                "updated_at": row["updated_at"],
                "company_id": row["company_id"],
                "is_deleted": row["is_deleted"].strip().lower() in ("1", "true", "t"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    _STATE.clear()
    _env = mc.senv(MCP_STORE="local", MCP_BUNDLE=str(d), MCP_MANIFEST=str(man_path))  # 설정 객체 덮기(S7d)
    try:
        on = do_search("계약기준금액은?", k=5, methods=["bm25"], decompose=False)
        by_name = {e["file_name"]: e for e in on["evidence"]}
        assert set(by_name) == {man_doc, other_doc}, by_name
        m = by_name[man_doc]
        assert m["doc_type"] == "CONTRACT" and m["version"] == "1" and m["contract_id"] == "C-RDB-2025-005", m
        assert m["updated_at"] == "2025-05-01T00:00:00Z" and m["company"] == "CL-2002" and m["is_deleted"] is False, m
        assert not m["supersedes_doc_id"], m
        o = by_name[other_doc]
        assert not (_MANIFEST_EXTRA_KEYS & set(o)), o  # manifest에 없는 문서 — 새 칸 0개

        _STATE.clear()
        with mc.senv(MCP_MANIFEST=str(d / "no_such_manifest.jsonl")):  # manifest 자체가 없음 — 전부 바이트 동일(새 칸 0개)
            off = do_search("계약기준금액은?", k=5, methods=["bm25"], decompose=False)
            for e in off["evidence"]:
                assert set(e) == _EVIDENCE_BASE_KEYS, e
    finally:
        _STATE.clear()
        _env.close()
    print("[selftest] AD44 _evidence — RDB manifest 메타 붙음(문서 있을 때만) · manifest 없음/문서 없음은 새 칸 0개 통과")


def test_main():  # 옛 main.py selftest가 부르던 순서(이 모듈 몫만) — search_svc.py엔 __main__이 없었음
    from common.core.paths import STACK_FILE
    from common.store.db import cfgtables

    cfgtables._CACHE.setdefault(
        "stack", cfgtables.read_file("stack", STACK_FILE)
    )  # test_mcp_main과 같은 준비(S8b — 이미지 selftest엔 PG가 없어 판 표 대신 파일, S9 따로 사례가 되며 더함)
    _selftest_search_notes_no_race()
    _selftest_evidence_gate()
    _selftest_search_client_arg()
    _selftest_entity_split()
    _selftest_br50_client_scope()
    _selftest_evidence_rdb_meta()
    _selftest_query_log()
    _selftest_evidence_rep_path()
    _selftest_index_id()
    _selftest_copy_group()
    _selftest_copy_group_rep_text()
