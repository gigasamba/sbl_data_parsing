"""로컬 묶음 검색(검색 모듈) — numpy 정확 코사인 + BM25 + 드문 ID → RRF(PostgreSQL·EDW와 같은 규칙). 질의 임베딩."""

import math
from collections import Counter
from pathlib import Path

from common.ai.embed import embed_texts, query_model_mismatch
from common.core.contract import jl
from common.core.terms import load_id_patterns_typed, match_clients  # BR41 tie-break 엔티티(고객 명부·ID 모양)
from common.core.text import id_terms, index_text, tokens  # 색인·토큰 규칙(모듈 계약)
from mcp_server import config as mc  # 설정 객체(S7d)
from mcp_server.services.search import clientscope as CS  # BR50 고객 범위 단일 규칙(allows(), pgsearch.py와 공용)
from mcp_server.services.search.text import term_weights  # X3(10-16 검색 전용으로 분리)

ID_MAX_DF = 5  # ID 우선 검색에 쓰는 ID: 이 수 이하의 "문서"에만 나오는 것(로컬·pgvector 같은 값).
# BR32 — 청크 수가 아니라 문서 수로 센다(원래 의도 "여러 문서에 흔한 제품 코드는 문서를 특정 못 함"은 문서 단위
# 개념인데, 예전엔 청크 단위로 셌다 — 같은 문서를 청크 여러 개로 쪼개면(G9 머리말은 그 문서의 모든 청크에 같은
# ID 토큰을 반복) 문서 1개뿐인데도 문턱을 넘어 제외됐다. 실측(QA074): 메일 스크린샷(mailshot_*.png)이 OCR로
# 조각 4개로 쪼개져 메일 ID 토큰이 청크 6개(eml 1·msg 1·png 4)에 나타남 → 청크 기준 df=6 > 5로 걸러져 정작
# .msg 사본이 후보에도 못 들었다. 문서 기준이면 df=3(eml·msg·png 각 1문서) — 문턱 안.

TIE_EPS_REL = 1e-3  # BR41 — 동점으로 볼 상대 오차(기본, SEARCH_TIE_EPS로 조정)


def entity_hints(question, client_candidates):
    """BR41 — 질문에 나온 엔티티(동점 깨기용): 후보 문서들의 고객(client_candidates, 전체 명부 질의 없이 이
    질의의 후보에 실제 있는 고객만 — common.core.terms.match_clients) + 계약번호·제품코드(용어 사전 id_patterns.csv,
    load_id_patterns_typed) 중 질문 문자열에 그대로 나온 것. 질문이 비거나 후보가 없으면 빈 집합(동점 깨기 안 함)."""
    if not question:
        return set(), set()
    clients = sorted({c for c in client_candidates if c})
    matched_clients = set(match_clients(question, clients)) if clients else set()
    matched_ids = set()
    for id_type, pat in load_id_patterns_typed():
        if id_type in ("contract_no", "product_code"):
            matched_ids |= {m.group(0) for m in pat.finditer(question)}
    return matched_clients, matched_ids


def _doc_matches_entities(client, contract_no, product_code, matched_clients, matched_ids):
    """BR41 — 후보 문서(고객·계약번호·제품코드 — 구조화 메타 필드만)가 질문에 나온 엔티티와 맞는지.
    파일명 부분 일치는 안 씀(실측 QA093·R2Q005 회귀: 다른 제품의 QBR·보고서 파일명에 질문의 제품코드가 그대로
    적혀 있어도 그 문서가 정답은 아님 — 파일명 부분 일치는 오탐이 너무 쉬움, 구조화 필드의 정확 일치만 신뢰)."""
    if client and client in matched_clients:
        return True
    return bool((contract_no and contract_no in matched_ids) or (product_code and product_code in matched_ids))


def tie_break(ordered, scores, docmeta, question, eps=None):
    """BR41 — 결정적 문서 단위 동점 깨기: 이미 정해진 융합 순위(ordered, 내림차순) 안에서 연속한 구간의 점수가
    (구간 1위 대비) 상대 오차 eps(기본 TIE_EPS_REL, SEARCH_TIE_EPS로 조정) 안이면 — 그 구간만 질문에 나온
    엔티티(고객명·별칭 — 기존 용어 사전 확장, 계약번호, 제품코드 — 구조화 메타 필드의 정확 일치만)가 맞는
    후보를 앞으로(안 맞으면 그대로, 안정 정렬 — 같은 문서 청크끼리는 맞는지 여부가 같아 순서 안 바뀜).
    질문에 엔티티가 없거나 구간 안에 맞는 후보가 하나도 없으면 바이트 동일(그대로 반환).
    ordered: 현재 순위의 키 목록 · scores: {키: 융합 점수} · docmeta: {키: (file_name, client, contract_no, product_code)}
    (file_name은 entity_hints의 client 매칭엔 안 쓰지만 다른 호출자 호환을 위해 자리만 유지).
    local.py·pgsearch.py 공용(같은 함수 — 저장소 갈라지지 않음, enforcement §2)."""
    eps = TIE_EPS_REL if eps is None else eps
    matched_clients, matched_ids = entity_hints(question, (docmeta.get(k, (None, None, None, None))[1] for k in ordered))
    if not matched_clients and not matched_ids:
        return list(ordered)
    match = {k: _doc_matches_entities(*docmeta.get(k, (None, None, None, None))[1:], matched_clients, matched_ids) for k in ordered}
    if not any(match.values()):
        return list(ordered)
    out, i, n = [], 0, len(ordered)
    while i < n:
        j, top = i, scores.get(ordered[i])
        while (
            j + 1 < n and top is not None and scores.get(ordered[j + 1]) is not None and abs(scores[ordered[j + 1]] - top) <= eps * abs(top)
        ):
            j += 1
        group = ordered[i : j + 1]
        if j > i:
            group = sorted(group, key=lambda k: not match[k])  # 안정 정렬 — 맞는 후보 먼저, 나머지는 기존 순서 유지
        out.extend(group)
        i = j + 1
    return out


def weights(question=None):
    """RRF 가중치(검색 방법별) — SEARCH_W_VECTOR·SEARCH_W_BM25·SEARCH_W_ID(기본 1·1·2, 드문 ID 정확 일치를 우선).
    BR58(10-12)에서 SEARCH_W_BM25 기본 1.3을 시도했다가 되돌림 — 상위5 적중은 올랐지만(합본 terms-hard .70→.80)
    1위 정답이 여러 세트에서 떨어짐(hard64 .772→.719·r2 .85→.80·distractors 1.0→.944, 답변 단계 QA095 미스) —
    근접 중복 문서 구분은 재정렬(BR54) 쪽에서. 측정: dev_tools/perform_test/retrieval/measure.py --pooled·--hard-core-manifest.
    G14 — question이 주어지고 질문 유형 라우터(mcp_server.services.search.qtype.classify,
    새 분류기 안 만듦)가 "aggregate"(건수·합계·최대/최소·평균)로 보면 SEARCH_W_BM25 대신 SEARCH_W_BM25_TABLE을
    bm25 가중으로 쓴다 — 표 집계 질문은 같은 양식의 다른 고객·연도 표가 키워드로 같이 올라와 BM25가 벡터 1위 근거를
    끌어내리는 문제(dev/docs/backlog/search.md G14). local.py·pgsearch.py 둘 다 이 함수 하나만 써서 가중치가
    갈라지지 않는다(pgsearch.py가 이 함수를 import)."""
    s = mc.cfg().search  # 한 번 묶음(S7d — 가중치 칸들이 같은 판 값)
    w = {"vector": s.weights.vector, "bm25": s.weights.bm25, "id": s.weights.id}
    if question is not None:
        from mcp_server.services.search.qtype import classify

        if classify(question)[0] == "aggregate":
            w["bm25"] = s.weights.bm25_table
    return w


class IndexMismatch(ValueError):
    """AD41 — 질의 임베딩 모델이 색인(묶음 meta)과 다름. RuntimeError·OSError가 아니라서 '키워드·ID만'으로 조용히 떨어지지 않고 오류로 드러남."""


def embed_query(meta, text):
    """질의 임베딩 — 모델은 색인 meta(embed·embed_model)에서, 차원도 meta와 맞아야 함(AD41: 불일치면 거부)."""
    import numpy as np

    bad = query_model_mismatch(meta)  # api는 모델 이름이 이 프로세스 env(EMBED_MODEL) — 색인과 다르면 거부
    if bad:
        raise IndexMismatch(bad)
    v = embed_texts(meta["embed"], [text], "query")[0]
    if len(v) != meta["dim"]:  # 적재 뒤 임베딩 모델(EMBED_MODEL)을 바꾸면 차원이 달라 검색이 깨짐 — 다시 적재
        raise SystemExit(
            f"질의 임베딩 {len(v)}차원 ≠ 적재 {meta['dim']}차원(모델 {meta.get('embed_model')}) — 같은 모델로 묻거나 run-stack으로 다시 적재"
        )
    return (v / (np.linalg.norm(v) or 1)).astype("float32")


def file_name_of(file_path):
    """파일 이름 = file_path의 마지막 '/' 뒤 — v_chunk_source 뷰(`regexp_replace(file_path, '^.*/', '')`)와 같은 규칙(PG doc 행용 — mc-10)."""
    return file_path.rsplit("/", 1)[-1]


class Local:
    """로컬 검색 — 묶음 파일(numpy 정확 코사인 + 같은 BM25 + RRF). EDW 프로시저와 같은 규칙."""

    def __init__(self, bundle):
        import numpy as np

        B = Path(bundle)
        self.chunks, self.docs = jl(B / "chunks.jsonl"), jl(B / "docs.jsonl")
        for d in (
            self.docs
        ):  # mc-10 — 축소 스키마 묶음(doc_key·file_path·doc_name만)과 옛 묶음(file_sha256·file_name)을 읽는 곳마다 가르지 않게 여기서 한 번
            d.setdefault("doc_key", d.get("file_sha256") or d["file_path"])
            d.setdefault("file_name", d.get("doc_name") or file_name_of(d["file_path"]))
        self.v = np.load(B / "vectors.npy", mmap_mode="r")  # 큰 묶음도 메모리에 다 올리지 않음
        self.tf = [Counter(tokens(index_text(c))) for c in self.chunks]
        self.df = Counter(t for tf in self.tf for t in tf)
        doc_terms = {}  # BR32 — id 문턱용 문서 단위 df(아래 doc_df)의 중간 집계
        for c, tf in zip(self.chunks, self.tf):
            doc_terms.setdefault(c["doc"], set()).update(tf)
        self.doc_df = Counter(t for terms in doc_terms.values() for t in terms)
        self.n = len(self.chunks)
        self.avg = sum(c["n_terms"] for c in self.chunks) / max(self.n, 1)

    def bm25(self, terms, n, restrict=None):
        """terms: 토큰 목록(가중치 전부 1.0) 또는 {토큰: 가중치}(X3 용어 사전 확장 — common.core.terms.expand_query). 확장 없으면 전과 동일한 점수.
        restrict(AD38 SEARCH_CLIENT_HARD) = 후보로 볼 청크 번호 집합(없으면 전체, 기존 동작과 동일)."""
        w = term_weights(terms)
        sc = {}
        for i, tf in enumerate(self.tf):
            if restrict is not None and i not in restrict:
                continue
            s = 0.0
            for t, tw in w.items():
                if t in tf:
                    idf = math.log(1 + (self.n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                    s += tw * idf * tf[t] * 2.5 / (tf[t] + 1.5 * (0.25 + 0.75 * self.chunks[i]["n_terms"] / self.avg))
            if s:
                sc[i] = s
        return sorted(sc, key=lambda i: -sc[i])[:n]

    def search(
        self, qv, terms, k=10, n=50, retrieve="hybrid", vr=None, methods=None, client=None, client_strict=False, question=None, hidden=None
    ):
        """vr = 벡터 순위(청크 번호 목록)를 밖에서 줄 때(EDW 벡터 검색 결과) — 없으면 묶음 벡터로 계산.
        methods = 쓸 방법 {vector, bm25, id}(없으면 retrieve대로). 반환 (순위 목록, 근거 방법 dict{청크: v·k·i}, 점수 dict{청크: 점수}) —
        점수 = 하이브리드 RRF 합(벡터만 쓸 때는 코사인값, vr을 밖에서 받으면 모름 — {}, AD42 R3 문턱 판정용) · 같은 Local을
        여러 스레드가 쓸 때(검색 MCP) 섞이지 않게 self 속성이 아니라 반환값으로 준다(S12).
        client(AD38 SEARCH_CLIENT_HARD) = 허용할 고객 이름 집합 — 주어지면 그 고객의 문서(고객 미상 문서는 기본 포함,
        client_strict=True면 미상도 뺌)만 vector·bm25·id 후보로(저장소 질의 단계에서 제한 — 넓힌 후보 밖이라 못 잡는 문제 없음).
        None(기본)이면 제한 없음 — 전과 바이트 동일.
        hidden(OP1) = 검색에서 뺄 doc_key(file_sha256) 집합 — client와 달리 항상 완전 제외(소프트 없음, 사람이 unhide
        하기 전까지). None·빈 집합이면 전과 바이트 동일.
        question(G14) = 원문 질문 글자(weights()에 그대로 건넴 — 안 주면 전과 바이트 동일,
        BR41 tie_break에도 그대로 건넴).
        BR41 — 하이브리드(RRF) 경로에서 최종 순위(order, 멤버십 불변)를 tie_break()로 한 번 더(동점·질문 엔티티
        맞으면 앞으로) — vector만 쓰는 경로(위 m == {"vector"})는 안 거침."""
        import numpy as np

        restrict = None
        if client:
            allowed_docs = {
                i
                for i, d in enumerate(self.docs)  # 10-14 — clients(다중 라벨) 있으면 ANY-match, 없으면(옛 묶음) client로 낙하
                if CS.allows(d.get("clients") or d.get("client"), client, client_strict)
            }
            restrict = {i for i, c in enumerate(self.chunks) if c["doc"] in allowed_docs}
        if hidden:
            not_hidden_docs = {i for i, d in enumerate(self.docs) if d.get("file_sha256") not in hidden}
            not_hidden_chunks = {i for i, c in enumerate(self.chunks) if c["doc"] in not_hidden_docs}
            restrict = (restrict & not_hidden_chunks) if restrict is not None else not_hidden_chunks
        m = set(methods) if methods else ({"vector"} if retrieve == "cosine" else {"vector", "bm25", "id"})
        w = weights(question)
        lists = []
        cos = None
        if "vector" in m:
            if vr is None:
                cos = self.v @ qv
                if restrict is not None:
                    cand = np.fromiter(sorted(restrict), dtype=int)
                    order = np.argsort(-cos[cand])[: k if m == {"vector"} else n] if len(cand) else np.array([], dtype=int)
                    vr = [int(cand[j]) for j in order]
                else:
                    vr = [int(i) for i in np.argsort(-cos)[: k if m == {"vector"} else n]]
            elif restrict is not None:
                vr = [i for i in vr if i in restrict]
            lists.append((vr, w["vector"], "v"))
        if "bm25" in m:
            lists.append((self.bm25(terms, n, restrict=restrict), w["bm25"], "k"))
        if "id" in m:
            ids = [
                t for t in id_terms(terms) if 0 < self.doc_df[t] <= ID_MAX_DF
            ]  # 드문 ID만(여러 문서에 흔한 제품 코드는 문서를 특정 못 함, BR32 — 문서 단위)
            pool = [i for i, tf in enumerate(self.tf) if (restrict is None or i in restrict) and any(t in tf for t in ids)][:n]
            lists.append((pool, w["id"], "i"))  # ID 정확 일치 청크
        if m == {"vector"}:
            via = {int(i): "v" for i in list(vr)[:k]}
            score = {int(i): float(cos[i]) for i in list(vr)[:k]} if cos is not None else {}
            return [int(i) for i in list(vr)[:k]], via, score
        rrf, via = Counter(), {}
        for lst, wt, tag in lists:
            for r, i in enumerate(lst, 1):
                rrf[int(i)] += wt / (60 + r)
                via[int(i)] = via.get(int(i), "") + tag
        order = [i for i, _ in sorted(rrf.items(), key=lambda x: (-x[1], x[0]))[:k]]
        scores = {i: rrf[i] for i in order}
        docmeta = {
            i: (
                self.docs[self.chunks[i]["doc"]].get("file_name"),
                self.docs[self.chunks[i]["doc"]].get("client"),
                self.docs[self.chunks[i]["doc"]].get("contract_no"),
                self.docs[self.chunks[i]["doc"]].get("product_code"),
            )
            for i in order
        }
        order = tie_break(order, scores, docmeta, question)  # BR41 — 같은 후보 집합, 순서만(멤버십 불변)
        return order, via, scores
