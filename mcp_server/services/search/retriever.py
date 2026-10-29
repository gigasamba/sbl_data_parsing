"""검색(모듈 ④) — 같은 질의 → 저장소(PostgreSQL+pgvector 또는 로컬 묶음)에서 하이브리드(벡터 + BM25 + 드문 ID → RRF) + 그래프 이웃.
pipeline.py(ask·test-stack)와 검색 MCP(modules/search/mcp_server.py)가 같이 씀. 오케스트레이터(pipeline.py)를 import하지 않음(모듈 분리)."""

import json
import sys
import time
from pathlib import Path

from common.core import docmeta as DM  # 날짜·개정·구판·문서군(L3-1, structure·search 공용 규칙)
from common.core.contract import (
    jl,
    make_chunk_key,
    uri_from_path,  # 원본 위치 규칙(모듈 계약)
)
from mcp_server import config as mc  # 설정 객체(mcp 칸 — S7d)
from mcp_server.services.search import (
    clientscope as CS,  # BR50 고객 범위 단일 규칙(client_scope·allows, local.py·pgsearch.py·mcp_server.py와 공용)
)
from mcp_server.services.search.local import Local, embed_query
from mcp_server.services.search.terms import (  # 용어 사전(X3·X4, 구조화와 같은 규칙) · SI43⑤ 벡터 질의 별칭 덧붙이기(10-16 검색 전용으로 분리)
    expand_query,
    vector_alias_text,
)


def evidence_gate_on():
    """R3(AD42) SEARCH_EVIDENCE_GATE(기본 켬, =0으로 끔) — 단일 읽기 지점(mcp_server.py do_search도 이 함수를 씀).
    켜지면 hits에 score 칸이 실리고(mcp_server.evidence_status의 근거), 꺼지면(=0) 예전처럼 score 없음(바이트 동일)."""
    return mc.cfg().search.evidence_gate  # S7d — 설정 객체(켜기 칸 off=("0",) = 옛 != "0")


def _name(file_path):
    """파일 이름 = file_path의 마지막 '/' 뒤 — v_chunk_source 뷰(`regexp_replace(file_path, '^.*/', '')`)와 같은 규칙(Windows 역슬래시는 안 나눔)."""
    return file_path.rsplit("/", 1)[-1]


def _fill_doc(d):
    """mc-10 — 묶음 docs.jsonl 행에 doc_key·file_name을 한 번 채운다(있으면 그대로). 2026-10-20 축소 스키마 뒤 묶음은 doc_key(=file_path,
    pg 근거의 doc_key와 같은 값)·file_path만 있고 옛 묶음은 file_sha256·file_name이 있다 — 읽는 곳마다 갈래를 두지 않게 Retriever가
    묶음을 읽을 때 한 곳에서(local.py·internal_docs도 같은 dict를 봄). 전에는 서버에서 d["file_sha256"]로 읽어 search가 멈췄음."""
    d.setdefault("doc_key", d.get("file_sha256") or d["file_path"])
    d.setdefault("file_name", _name(d["file_path"]))


class Retriever:
    """같은 질의 → 본문·출처 저장소(pgvector 또는 로컬 묶음)에서 하이브리드(벡터 + BM25 + 드문 ID → RRF).
    벡터는 pgvector에만 둔다(사용자 10-29 — EDW 벡터 경로 삭제, docs/prd/ops.md#op-03)."""

    def __init__(self, bundle, retrieve="cosine", pg=False, hidden_db=None, pg_schema=None):
        """hidden_db(OP1, 기본 None — 안 주면 전과 바이트 동일) = 문서 대장 연결(common.store.registry.try_open_db()) —
        주어지면 지금 숨김 상태인 doc_key 집합을 한 번 읽어 self.hidden에 캐시하고 바로 닫는다(연결을 오래 들고
        있지 않음 — pg=False인 로컬 검색도 이 연결은 pg 인자와 무관하게 독립적으로 받는다, 문서 대장은 다른 스키마)."""
        self.bundle, self.retrieve = Path(bundle), retrieve
        self.meta = json.loads((self.bundle / "meta.json").read_text(encoding="utf-8"))
        self.local = Local(bundle)
        for d in self.local.docs:
            _fill_doc(d)
        self.key_local = {make_chunk_key(self.local.docs[c["doc"]]["doc_key"], c["seq"]): i for i, c in enumerate(self.local.chunks)}
        self.doc_meta = {
            d["doc_key"]: {
                "doc_date": d.get("doc_date"),
                "version": d.get("version"),
                "superseded": bool(d.get("superseded")),
                "family": d.get("family"),
            }
            for d in self.local.docs
        }  # L3-1: pgvector 저장소도 이 로컬 묶음 문서 메타로 최신성 순위(항상 로드됨)
        self.pg = None
        if pg:  # 개발 서버 PostgreSQL + pgvector(기본 저장소)
            from mcp_server.services.search import pg_mcp_connect as PGM
            from mcp_server.services.search import pgsearch

            # AD41 단일 전환점(PGM.connect_pool) — PG_PASSWORD·PG_CONN_FILE 있으면 PGPool(실 PG, S12 풀),
            # 없으면 스탠드인(sqlite, common/pg_standin.py) — 서버는 pipeline.env만 채우면 코드 변경 없이 실 PG로.
            # pg_schema(AD41) — 이름 있는 색인은 자기 스키마(<PG_SCHEMA>_<index_id>, common.index_cfg가 검증), 없으면 PG_SCHEMA 그대로.
            self.pgmod, self.pg = pgsearch, PGM.connect_pool(pg_schema=pg_schema)
        self._g = None
        self._cc = None  # 개념→청크 역색인(X4, concept_chunk.jsonl) — 처음 쓸 때 한 번 읽음
        self.hidden = set()
        if hidden_db is not None:  # OP1 — 숨김 집합(비면 전과 바이트 동일, _search_ex가 hidden=None으로 건넴)
            from mcp_server.services.search import registry as RREG  # 10-14 — hidden_set은 common.store.registry에서 옮김(R만 씀)

            try:
                self.hidden = RREG.hidden_set(hidden_db)
            finally:
                hidden_db.close()

    def refresh_hidden(self, db=None):
        """OP1(독립 검토 BLOCK 반영, 10-08) — 전체 재적재(Retriever 새로 만들기) 없이 숨김 집합만 다시 읽는다 —
        mcp_server._retriever()가 MCP_RELOAD_CHECK_SEC 간격으로 호출(적재 버전은 안 바뀌어도 hide·unhide는 그
        간격 안에 반영되게, 같은 비차단 잠금 안에서 — 추가 전체 재적재 없음).
        db를 직접 주면 그 연결을 그대로 쓰고 안 닫는다(시험용 — 호출자 책임) · 안 주면 common.store.registry.try_open_db()
        로 best-effort(문서 대장을 못 열면 조용히 그대로 — 바뀐 적 없음으로 봄, 호출을 막지 않음)."""
        from common.store import registry as REG
        from mcp_server.services.search import registry as RREG  # 10-14 — hidden_set은 common.store.registry에서 옮김(R만 씀)

        owns = db is None
        if owns:
            db = REG.try_open_db()
            if db is None:
                return
        try:
            self.hidden = RREG.hidden_set(db)
        except Exception:
            pass
        finally:
            if owns:
                db.close()

    def hidden_names(self):
        """OP1 — 숨김 문서의 file_name 집합(self.hidden=doc_key에서 파생) — 그림 기록처럼 이름으로만 연결된
        산출물을 거를 때 씀(get_image 등). self.hidden이 비었으면 빈 집합 그대로(질의 안 함)."""
        if not self.hidden:
            return set()
        if self.pg:
            rows = self.pg.q(f"SELECT file_name FROM {self.pg.schema}.doc WHERE file_sha256 = ANY(%s)", (sorted(self.hidden),))
            return {r["file_name"] for r in rows}
        return {d["file_name"] for d in self.local.docs if d.get("file_sha256") in self.hidden}

    def _chunk_key_hidden(self, chunk_key):
        """OP1 — chunk_key(file_sha256:seq) 앞부분이 self.hidden에 있는지(그래프 이웃·개념 검색처럼 chunk_key로만
        들고 있는 결과를 거를 때 공용으로 씀 — doc 조회 없이 문자열만 비교, 추가 질의 없음)."""
        return bool(self.hidden) and chunk_key.split(":", 1)[0] in self.hidden

    def _client_rows(self):
        """BR52 — PG doc 표(file_path·clients — 10-20 축소 스키마, mc-10)를 부를 때마다 새로 읽는다(client_map이 씀). 캐시하지 않음
        (security 검토 10-12): 서버가 도는 중 새 문서가 적재되면 캐시에 없는 문서가 '고객 미상'으로 보여
        엄격 격리(비엄격 모드)에서 다른 고객 문서가 허용될 수 있었음 — 정확성이 우선, 문서 단위 행이라 읽는 비용은 작음."""
        return self.pg.q(f"SELECT file_path, clients FROM {self.pg.schema}.doc")

    def client_map(self):
        """BR50(F·I) — file_name → 고객 라벨(단일 또는 다중 목록, clientscope.doc_clients) 전체 맵(그림 기록·
        OpenViking처럼 이름으로만 연결된 산출물의 고객 범위를 확인할 때 씀, hidden_names()와 같은 방식으로
        한 번만 질의 — N+1 없음). 비어 있는 store라도 빈 dict. file_name 키라 같은 이름이 고객마다 있으면
        충돌(먼저 온 쪽만 남음) — hidden_names()와 같은 남은 한계(고유 키는 file_sha256:client쌍인데 그림
        기록·OpenViking이 이름으로만 연결돼 있어 아직 못 바꿈). BR52: PG는 _client_rows()(매번 새로 읽음).
        독립 검토 CONCERN(10-14) — 전엔 client(단일)만 읽어 다중 라벨 문서의 그림·OV가 두 번째 이하 고객
        범위에선 안 걸렸다 — 이제 CS.doc_clients로 clients 우선·client 낙하(allows()의 ANY-match를 그대로 씀)."""
        if self.pg:
            return {_name(r["file_path"]): CS.doc_clients(None, r.get("clients")) for r in self._client_rows()}
        return {d["file_name"]: CS.doc_clients(d.get("client"), d.get("clients")) for d in self.local.docs}

    def search(self, q, k, methods=None, client=None):
        """methods ⊂ {vector, bm25, id}(없으면 retrieve 설정대로) — 검색 MCP가 방법을 골라 씀(G3).
        G12 메타 먼저 거르기: 질문에 고객(이름·별칭 — 용어 사전 T3)이 나오면 그 고객 문서(고객 미상 포함)를 앞으로, 못 찾으면 전체.
        ponytail: 후보를 넓게(k×5) 뽑아 거르는 방식(기본) — 고객 문서가 후보 밖이면 못 잡음, SEARCH_CLIENT_HARD=1이면
        저장소 질의 단계에서 진짜 제한(client 참조).
        L3-1: 마지막으로 같은 문서군(family) 최신성 순위(demote, 안 지움) — self.recency_note에 결과(SEARCH_RECENCY=0이면 끔).
        단일 스레드 호출부(pipeline.py·stack_matrix.py 등)용 — note류를 self 속성에도 채운다. 공유 인스턴스를 여러 스레드가 쓰면(검색 MCP) search_ex를 쓴다(S12)."""
        hits, ms, notes = self.search_ex(q, k, methods, client=client)
        self.expand_notes, self.note = notes.get("expand_notes"), notes.get("note")
        self.recency_note = notes.get("recency_note")
        return hits, ms

    def search_ex(self, q, k, methods=None, recency=None, client=None, client_only=False, client_strict=None, scope=None):
        """search()와 같은 동작이지만 note류(expand_notes·note·recency_note)를 self 속성이 아니라
        반환값 notes(dict)로 준다 — 검색 MCP처럼 같은 Retriever를 여러 스레드가 동시에 쓸 때 A 요청 응답에 B의 note가
        섞이는 것을 막음(S12). recency: 이 질의 1건만 docmeta.recency_rerank 모드를 강제(None이면 env, AG1 engine-qa
        보완 — 전역 env를 바꾸면 동시에 도는 다른 질의가 섞임, S12와 같은 원칙).
        client(AD38 — MCP search의 client 인자) = 질문에서 못 잡아도 강제로 더할 고객(이름 또는 이름 목록) — 용어 사전으로
        잡힌 고객(SEARCH_CLIENT_FILTER)과 합쳐진다(BR50 — 범위 계산은 clientscope.client_scope 한 곳, local.py·pgsearch.py·
        mcp_server.py와 공용). SEARCH_CLIENT_HARD=1이면 저장소 질의 단계에서 그 고객 문서만(고객 미상은 기본 포함 —
        SEARCH_CLIENT_STRICT=1이면 미상도 뺌) · 꺼짐(기본)이면 예전처럼 후보를 넓혀 앞으로만 올림(client 인자를 안 주면
        바이트 동일).
        client_only(BR23, 기본 False — 안 쓰면 바이트 동일) = True면 q에서 자동 잡히는 고객(SEARCH_CLIENT_FILTER)을
        무시하고 client 인자만으로 고객 집합을 정함 — 질문에 고객 2명이 같이 나올 때(비교) 한 쪽만 따로 떠서 돌리는
        하위 검색용(mcp_server.do_search BR23 엔티티 분해). SEARCH_CLIENT_HARD 꺼짐(기본)의 "후보 넓혀 앞으로만" 방식은
        q 전문이 여전히 다른 고객 이름까지 포함해 그 고객 후보가 넓힌 풀(n*5)에도 하나도 안 들면 그대로 못 잡으므로(실측
        — 한쪽 고객 점수가 전반적으로 높으면 widened pool 자체에 다른 고객 문서가 없음), client_only는 env와 무관하게
        항상 저장소 질의 단계에서 그 고객만(strict — 미상도 뺌, 반대쪽 고객 문서가 새지 않게)으로 제한.
        client_strict(BR50 E, 기본 None=env 그대로·바이트 동일) = SEARCH_CLIENT_STRICT을 무시하고 strict 여부를 강제
        — BR43 FX 근거 검색처럼 "같은 범위(client)는 쓰되 고객 미상 문서(일반 환율표 등)는 항상 포함"이 필요할 때
        False로 준다(client_only=True면 의미상 항상 strict라 이 값은 무시됨).
        scope(2026-10-20 통합 search) = 하드 필터 범위 **안** 문서 file_path 집합 — 주어지면 저장소 질의 단계부터 그
        문서의 청크만 후보로(PG는 pgsearch._scope_restrict·restrict, 로컬 묶음은 파이썬 거르기). None이면 전과 바이트 동일.
        반환: (hits, ms, notes)."""
        n = k
        allowed, strict, hard = CS.client_scope(q, client, self.clients(), client_only=client_only, strict_override=client_strict)
        if allowed is None:
            hits, ms, notes = self._search_ex(q, n, methods, scope=scope)
        elif hard:
            hits, ms, notes = self._search_ex(q, n, methods, client=allowed, client_strict=strict, scope=scope)
        else:
            hits, ms, notes = self._search_ex(q, max(n * 5, 50), methods, scope=scope)
            inn = [h for h in hits if CS.allows(h.get("clients") or h.get("client"), allowed, False)]
            if not inn:
                hits = hits[:n]
            else:
                top = (inn + [h for h in hits if h not in inn])[:n]
                hits = [{**h, "rank": i + 1} for i, h in enumerate(top)]
        if scope:  # 2026-10-20 통합 search — 로컬 묶음 경로·남는 새는 것 방지(안전망)
            hits = [h for h in hits if (h.get("file_path") or "") in scope]
        for h in hits:  # pgvector·EDW 경로도 로컬 묶음 문서 메타로(같은 규칙, 묶음은 항상 로드됨)
            m = self.doc_meta.get(h.get("doc_key")) or {}
            h["doc_date"], h["version"], h["superseded"] = m.get("doc_date"), m.get("version"), m.get("superseded")
        hits = hits[:k]
        hits, notes["recency_note"] = DM.recency_rerank(hits, self.doc_meta, q, mode=recency)
        return hits, ms, notes

    def _search_ex(self, q, k, methods=None, client=None, client_strict=False, scope=None):
        # X3: BM25 쪽만 용어 사전으로 확장({토큰: 가중치}) — 벡터 질의(qv)는 원문 q 그대로 임베딩(아래, 바뀌지 않음)
        terms, expand_notes = expand_query(q)
        qv, note = None, None
        if not self.meta.get("dim"):  # 임베딩 없는 묶음(PIPE_EMBED=none)이면 키워드·ID만
            note = "임베딩 없는 묶음 — 키워드·ID 검색만"
        elif methods and "vector" not in methods:  # 벡터를 안 쓰는 요청은 질의 임베딩도 안 함(S85 — 임베딩 없는 이미지·비용)
            pass
        else:
            try:
                qv = embed_query(self.meta, vector_alias_text(q))  # SI43⑤ — 임베딩 입력에만 명부 별칭 덧붙임(q 자체는 안 바뀜)
            except (
                OSError,
                RuntimeError,
                ImportError,
            ) as ex:  # 임베딩 서버 장애·라이브러리 없음(rag-core 이미지) — 검색을 멈추지 않고 키워드·ID로(근거 via에 v 없음, G11)
                note = f"질의 임베딩 실패 — 키워드·ID 검색만: {type(ex).__name__}: {str(ex)[:120]}"
                print(f"({note})", file=sys.stderr, flush=True)
        if qv is None:
            want = set(methods) if methods else ({"vector"} if self.retrieve == "cosine" else {"vector", "bm25", "id"})
            methods = sorted(want - {"vector"}) or ["bm25", "id"]
        t0 = time.perf_counter()
        if self.pg:
            rows = self.pgmod.search(
                self.pg,
                qv,
                terms,
                k,
                retrieve=self.retrieve,
                methods=methods,
                client=client,
                client_strict=client_strict,
                question=q,
                hidden=self.hidden or None,
                scope=scope,
            )
            # 2026-10-20 축소 스키마 — v_chunk_source에 file_sha256·source_uri·client가 없음: clients(JSON)에서 파싱, URI는 file_path에서 유도
            hits = [
                {
                    "rank": i + 1,
                    "score": r["rrf"],
                    "file_path": r["file_path"],
                    "page": r["page"],
                    "line": f"{r['line_start']}-{r['line_end']}",
                    "bbox": r["bbox"],
                    "section": r["section"],
                    "summary": r["summary"],
                    "text": r["chunk_text"],
                    "chunk_ref": r["chunk_id"],
                    "chunk_key": f"{r['file_path']}:{r['seq']}",
                    "doc_key": r["file_path"],
                    "doc_id": r["doc_id"],
                    "file_name": r["file_name"],
                    "source_uri": uri_from_path(r["file_path"]),
                    "clients": CS.doc_clients(None, r.get("clients")) or (r.get("clients") or "").strip(),
                    "via": r.get("via"),
                }
                for i, r in enumerate(rows)
            ]
        else:
            L = self.local
            order, via, score = L.search(
                qv,
                terms,
                k,
                retrieve=self.retrieve,
                methods=methods,
                client=client,
                client_strict=client_strict,
                question=q,
                hidden=self.hidden or None,
            )
            hits = []
            for i, ci in enumerate(order):
                c, d = L.chunks[ci], L.docs[L.chunks[ci]["doc"]]
                hits.append(
                    {
                        "rank": i + 1,
                        "file_path": d["file_path"],
                        "page": c["page"],
                        "line": f"{c['line_start']}-{c['line_end']}",
                        "bbox": c["bbox"],
                        "section": c["section"],
                        "summary": d.get("summary"),
                        "text": c["chunk_text"],
                        "chunk_ref": ci,
                        "chunk_key": make_chunk_key(d["doc_key"], c["seq"]),
                        "doc_key": d["doc_key"],
                        "doc_id": c["doc"],
                        "file_name": d["file_name"],
                        "source_uri": d.get("source_uri") or uri_from_path(d["file_path"]),
                        "client": d.get("client"),
                        "clients": CS.doc_clients(d.get("client"), d.get("clients")),
                        "contract_no": d.get("contract_no"),
                        "via": via.get(ci),
                        **({"score": score.get(ci)} if evidence_gate_on() else {}),
                    }
                )  # 꺼짐(=0)이면 예전처럼 score 없음(AD42 검토)
        return hits, (time.perf_counter() - t0) * 1000, {"expand_notes": expand_notes, "note": note}

    def clients(self):
        """적재된 고객사 이름 — 하위 질문 고객 맥락 보정용(decompose.keep_context).
        2026-10-20 축소 스키마 — doc.clients(JSON 텍스트)에서 이름만 뽑아 합친다."""
        if self.pg:
            out = set()
            for r in self.pg.q(f"SELECT clients FROM {self.pg.schema}.doc WHERE clients IS NOT NULL"):
                out.update(CS.doc_clients(None, r["clients"]))
            return sorted(out)
        return sorted({d["client"] for d in self.local.docs if d.get("client")})

    def _concept_top(self, cid, k):
        """개념 → concept_chunk 상위(횟수 많은 순) [(chunk_key, count), ...] — 로컬 묶음 파일 또는 PostgreSQL 표(X4).
        OP1(독립 검토 BLOCK 반영) — 숨김 문서의 청크는 여기서 공용으로 빠짐(concept_hits·do_lookup_term 둘 다 이
        함수를 거치므로 한 곳에서만 거르면 됨) · LIMIT k는 거르기 전에 걸림(상위 몇 개가 숨김이면 k개보다 적게
        돌아올 수 있음 — 안전 쪽, 숨김 문서를 메우러 더 안 뽑음)."""
        if self.pg:
            s = self.pg.schema
            rows = self.pg.q(
                f"""SELECT cc.count, c.seq, d.file_sha256 FROM {s}.concept_chunk cc
                               JOIN {s}.chunk c ON c.chunk_id = cc.chunk_id JOIN {s}.doc d ON d.doc_id = c.doc_id
                               WHERE cc.concept_id = %s ORDER BY cc.count DESC LIMIT %s""",
                (cid, k),
            )
            pairs = [(f"{r['file_sha256']}:{r['seq']}", r["count"]) for r in rows]
        else:
            if self._cc is None:
                f = self.bundle / "concept_chunk.jsonl"
                self._cc = jl(f) if f.exists() else []
            rows = sorted((r for r in self._cc if r["concept_id"] == cid), key=lambda r: -r["count"])[:k]
            pairs = [(r["chunk_key"], r["count"]) for r in rows]
        return [(ck, c) for ck, c in pairs if not self._chunk_key_hidden(ck)]
