#!/usr/bin/env python3
"""외부 지식 그래프 스택 어댑터 — LightRAG·Cognee·Graphiti·OpenViking를 같은 인터페이스(build→search)로 감싸
output/eval/external/<스택>.jsonl({"anchor_id","units":[{"doc","text"}]})을 만든다. tools/run_combo.py가 이를
combo {"parse":"external","retrieve":<스택>}로 같은 R 지표(eval-design.md §5 마지막 문단)로 채점한다.

이 PC에는 lightrag·cognee·graphiti-core·openviking-sdk가 **설치돼 있지 않다**(이번 작업에서 설치 금지 — 어댑터
코드만). 그래서 각 어댑터는 지연 import(lazy import)이며, 실행하면 "미설치 — SETUP.md …" 에러로 바로 멈춘다.
API 사용법은 dev_tools/perform_test/abtest/kg/*_arm.py(과거 실험, 이 저장소 read-only)를 그대로 옮겼으나 이 PC에서 실행해 본
적은 없다 — **미검증(UNVERIFIED)**. 검증된 것은 mockgraph뿐이다(로컬 mock LLM으로 build→search→jsonl→
run_combo 채점까지 전체 경로 실행 확인 — --selftest 및 이 파일을 만든 세션의 수동 실행).

공통 인터페이스: Adapter.build(corpus, workdir) → 색인 적재. Adapter.search(query, k) → [{"doc","text"}, ...].
코퍼스는 output/parse에서 pipeline.eval.stages.load_corpus(parse 설정, 기본 route)로 읽고, 질의는 output/eval/anchors.jsonl.

사용:
  python cli/kg_external.py --stack mockgraph --out output/eval
  python cli/kg_external.py --stack lightrag_hybrid --out output/eval   # 미설치 → 명확한 에러
  python cli/kg_external.py --selftest
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)

# isort: split
import argparse
import asyncio
import json
import os
import re
import time
from datetime import UTC
from pathlib import Path

from common.config import settings as C  # common 칸(S7c — 설정 객체: LLM_*·EMBED_BASE_URL·OV_URL · COMMON.env())
from pipeline import config as pc  # pipeline 칸(S7c — 설정 객체: GRAPHITI_NEO4J_*)

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # env 남김 — 라이브러리(5-3 H)
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")  # env 남김 — 라이브러리(5-3 H)

from common.core.console import utf8_stdout
from pipeline.eval import anchors as A  # 위 라이브러리 env(오프라인) 다음에 import
from pipeline.eval import stages as S

HERE = Path(__file__).resolve().parent

SETUP_HINT = "SETUP.md 4절(별도 venv) 참고 — 이 PC에는 설치돼 있지 않다(이번 작업은 어댑터 코드만, 설치 금지)"


def _missing(pkg, extra=""):
    return RuntimeError(f"'{pkg}' 미설치 — {SETUP_HINT}{(' ' + extra) if extra else ''}")


def _llm_key():
    """LLM_API_KEY(없으면 "dummy" — 옛 os.environ.get("LLM_API_KEY", "dummy"), 빈 값은 빈 글자 그대로) — S7c 설정 객체."""
    k = C.reveal(C.cfg().models.llm.api_key)
    return k if k is not None else "dummy"


def _need_llm():
    llm = C.cfg().models.llm  # S7c — 설정 객체
    base, model = llm.base_url, llm.model
    if not (base and model):
        raise RuntimeError("LLM_BASE_URL·LLM_MODEL 미설정(.env) — 이 스택은 자체 LLM 추출이 필요합니다")
    return base, model


def _guess_doc(piece, corpus):
    """근거 조각이 어느 문서에서 왔는지 최선 추정 — 소스 메타데이터가 없을 때 폴백(토큰 겹침이 가장 큰 문서)."""
    piece_words = set(S.words(piece))
    if not piece_words:
        return None
    best, best_score = None, 0
    for doc, text in corpus.items():
        score = len(piece_words & set(S.words(text)))
        if score > best_score:
            best, best_score = doc, score
    return best


def _split_units(text, k):
    """컨텍스트 문자열(프레임워크가 이어 붙여 돌려준 것) → 근거 조각 목록(빈 줄 기준 문단 분리, 최대 k개)."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    return parts[:k] or ([text.strip()] if text and text.strip() else [])


def _units_from_context(text, corpus, k):
    return [{"doc": _guess_doc(p, corpus) or "", "text": p} for p in _split_units(text, k)]


# ── 공통 인터페이스 ──────────────────────────────────────────


class Adapter:
    def build(self, corpus, workdir):
        raise NotImplementedError

    def search(self, query, k=10):
        raise NotImplementedError


# ── mockgraph — 검증용: pipeline.eval.stages "llm" 그래프 모드 + 그래프 검색을 그대로 mock LLM으로(S6a — "llm" 모드는 PC 전용 validation/e2e/graph_llm.py) ──


class MockGraphAdapter(Adapter):
    """실제 프레임워크 없이 build→search→jsonl→run_combo 채점 전체 경로를 점검하기 위한 인프로세스 어댑터."""

    def __init__(self):
        self.chunks = self.G = self.corpus = None

    def build(self, corpus, workdir):
        self.corpus = corpus
        self.chunks = S.chunk_all(corpus, "structure")
        self.G, self.metrics = S.build_graph("llm", self.chunks)

    def search(self, query, k=10):
        units = S.retrieve("graph", query, self.chunks, self.corpus, G=self.G, topk=k)
        return [{"doc": u["doc"], "text": u["text"]} for u in units]


# ── LightRAG (MIT) — dev_tools/perform_test/abtest/kg/lightrag_arm.py API 그대로. 미검증 ──


class LightRAGAdapter(Adapter):
    """mode: naive·local·global·hybrid·mix. LLM=LLM_BASE_URL/LLM_MODEL(OpenAI 호환).
    임베딩=EMBED_BASE_URL(있으면 API) 또는 로컬 e5-small(sentence-transformers)."""

    def __init__(self, qmode="hybrid"):
        self.qmode = qmode
        self.rag = self.QueryParam = None

    def build(self, corpus, workdir):
        try:
            from lightrag import LightRAG, QueryParam
            from lightrag.kg.shared_storage import initialize_pipeline_status
            from lightrag.llm.openai import openai_complete_if_cache
            from lightrag.utils import EmbeddingFunc
        except ImportError as err:
            raise _missing("lightrag-hku", "(`uv pip install lightrag-hku` — 별도 venv 권장)") from err
        base, model = _need_llm()

        async def llm(prompt, system_prompt=None, history_messages=None, **kw):
            kw.pop("keyword_extraction", None)
            return await openai_complete_if_cache(
                model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages or [],
                base_url=base,
                api_key=_llm_key(),
                temperature=0,
                **kw,
            )

        async def embed(texts):
            mode = "api" if C.cfg().models.embed.base_url else "e5-small"  # S7c — 설정 객체
            return S.embed_texts(mode, list(texts), "passage")

        self.QueryParam = QueryParam
        self.rag = LightRAG(
            working_dir=str(workdir),
            llm_model_func=llm,
            llm_model_max_async=1,
            enable_llm_cache=True,
            embedding_func=EmbeddingFunc(embedding_dim=384, max_token_size=512, func=embed),
            addon_params={"language": "Korean"},
        )

        async def _ingest():
            await self.rag.initialize_storages()
            await initialize_pipeline_status()
            await self.rag.ainsert(list(corpus.values()), ids=list(corpus), file_paths=list(corpus))

        asyncio.run(_ingest())
        self._corpus = corpus

    def search(self, query, k=10):
        async def _q():
            return await self.rag.aquery(query, param=self.QueryParam(mode=self.qmode, only_need_context=True, enable_rerank=False))

        ctx = asyncio.run(_q())
        text = ctx if isinstance(ctx, str) else json.dumps(ctx, ensure_ascii=False)
        return _units_from_context(text, self._corpus, k)


# ── Cognee (Apache-2.0) — dev_tools/perform_test/abtest/kg/cognee_arm.py의 add→cognify→search(only_context) 그대로. 미검증 ──


class CogneeAdapter(Adapter):
    """search_type: CHUNKS · GRAPH_COMPLETION(그래프 컨텍스트만, 생성 답변 아님) · INSIGHTS."""

    def __init__(self, search_type="GRAPH_COMPLETION"):
        self.search_type = search_type
        self.cognee = None
        self._corpus = {}

    def build(self, corpus, workdir):
        base, model = _need_llm()
        os.environ.update(
            {
                "LLM_PROVIDER": "custom",
                "LLM_ENDPOINT": base,
                "LLM_MODEL": model,  # env 남김 — 라이브러리(cognee)가 읽는 env(5-3 H)
                "LLM_API_KEY": _llm_key(),
                "SYSTEM_ROOT_DIRECTORY": str(Path(workdir) / "system"),
                "DATA_ROOT_DIRECTORY": str(Path(workdir) / "data"),
            }
        )
        try:
            import cognee
        except ImportError as err:
            raise _missing("cognee", "(`uv pip install 'cognee[docling,docs]'` — 별도 venv, SETUP.md 4절)") from err
        self.cognee, self._corpus = cognee, corpus

        async def _ingest():
            await cognee.prune.prune_data()
            await cognee.prune.prune_system(metadata=True)
            await cognee.add([f"[{n}]\n{t}" for n, t in corpus.items()], dataset_name="ext", skip_connection_test=True)
            await cognee.cognify(datasets=["ext"])

        asyncio.run(_ingest())

    def search(self, query, k=10):
        from cognee import SearchType

        async def _q():
            return await self.cognee.search(query, query_type=SearchType[self.search_type], datasets=["ext"], only_context=True, top_k=k)

        res = asyncio.run(_q())
        text = "\n".join(str(getattr(r, "search_result", r)) for r in res)
        return _units_from_context(text, self._corpus, k)


# ── Graphiti (Apache-2.0, Neo4j 백엔드) — dev_tools/perform_test/abtest/kg/graphiti_arm.py의 add_episode→search. 미검증 ──


class GraphitiAdapter(Adapter):
    """variant: None(기본 g.search)·rrf·mmr·cross_encoder(graphiti_core.search.search_config_recipes 프리셋,
    설치된 버전에 있을 때만 — 없으면 기본 검색으로 폴백)."""

    def __init__(self, variant=None):
        self.variant = variant
        self.g = None
        self._corpus = {}

    def build(self, corpus, workdir):
        try:
            from graphiti_core import Graphiti
            from graphiti_core.cross_encoder.bge_reranker_client import BGERerankerClient
            from graphiti_core.embedder.client import EmbedderClient
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.llm_client.openai_client import OpenAIClient
            from graphiti_core.nodes import EpisodeType
        except ImportError as err:
            raise _missing("graphiti-core", "(`uv pip install graphiti-core` + Neo4j docker — SETUP.md 4절)") from err
        base, model = _need_llm()
        gr = pc.cfg().connections.graphiti  # S7c — 설정 객체(uri·user는 빈 값 그대로 — blank=keep, 비밀번호는 없으면 "")
        uri, user = gr.neo4j_uri, gr.neo4j_user
        pw = C.reveal(gr.neo4j_password)
        pw = pw if pw is not None else ""

        class E5(EmbedderClient):
            async def create(self, input_data):
                t = input_data if isinstance(input_data, str) else str(input_data)
                return S.embed_texts("e5-small", [t], "passage")[0].tolist()

            async def create_batch(self, input_data_list):
                return [v.tolist() for v in S.embed_texts("e5-small", list(input_data_list), "passage")]

        llm = OpenAIClient(config=LLMConfig(api_key=_llm_key(), model=model, small_model=model, base_url=base, temperature=0))
        self.g = Graphiti(uri, user, pw, llm_client=llm, embedder=E5(), cross_encoder=BGERerankerClient(), max_coroutines=1)
        self._corpus = corpus

        async def _ingest():
            await self.g.build_indices_and_constraints()
            from datetime import datetime

            for name, text in corpus.items():
                await self.g.add_episode(
                    name=name,
                    episode_body=text[:12000],
                    source_description=name,
                    reference_time=datetime(2026, 1, 1, tzinfo=UTC),
                    source=EpisodeType.text,
                    group_id="ext",
                )

        asyncio.run(_ingest())

    def search(self, query, k=10):
        async def _q():
            if self.variant:
                try:
                    from graphiti_core.search import search_config_recipes as R

                    cfg = {
                        "rrf": R.COMBINED_HYBRID_SEARCH_RRF,
                        "mmr": R.COMBINED_HYBRID_SEARCH_MMR,
                        "cross_encoder": R.COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
                    }.get(self.variant)
                    if cfg:
                        res = await self.g._search(query, cfg, group_ids=["ext"])
                        return res.edges
                except ImportError:
                    pass
            return await self.g.search(query, group_ids=["ext"], num_results=k)

        edges = asyncio.run(_q())
        return [{"doc": _guess_doc(e.fact, self._corpus) or "", "text": e.fact} for e in edges[:k]]


# ── OpenViking(AGPLv3) — 로컬 서버(SDK SyncHTTPClient, REST /api/v1/search 경유). 미검증 ──


class OpenVikingAdapter(Adapter):
    """mode: None(기본) · THINKING(설치된 SDK가 search(mode=...)를 받으면). 서버가 떠 있어야 한다(SETUP.md 3절).
    XS8: OV_FEATURES에 parse가 없으면 --stack openviking*을 명시해도 거부(.env에 OV_FEATURES=parse 추가 안내)."""

    def __init__(self, mode=None):
        self.mode = mode
        url = C.cfg().connections.openviking.url  # S7c — 설정 객체(없으면 기본 주소, 빈 값은 빈 글자 그대로)
        self.base = url if url is not None else "http://127.0.0.1:1933"
        self.client = None
        self._corpus = {}

    def build(self, corpus, workdir):
        from common.store import services

        if not services.ov_enabled("parse"):
            raise RuntimeError(
                "OV_FEATURES에 parse가 없음 — .env에 OV_FEATURES=parse(또는 summary,search,parse)를 추가해야 이 스택을 씀(XS8)"
            )
        self._corpus = corpus
        try:
            from openviking_sdk import SyncHTTPClient
        except ImportError as err:
            raise _missing("openviking-sdk", "(`uv pip install openviking-sdk` — SETUP.md 4절, 서버는 별도 docker)") from err
        self.client = SyncHTTPClient(url=self.base)
        try:
            self.client.initialize()
        except Exception as e:
            raise RuntimeError(f"OpenViking 서버({self.base}) 연결 실패 — 떠 있는지 확인(SETUP.md 3절): {e}") from e
        for name, text in corpus.items():
            fp = Path(workdir) / name
            fp.write_text(text, encoding="utf-8")
            self.client.add_resource(str(fp), wait=True, timeout=600)

    def search(self, query, k=10):
        kw = {"limit": k, **({"mode": self.mode} if self.mode else {})}
        try:
            res = self.client.search(query, **kw)
        except TypeError:
            kw.pop("mode", None)
            res = self.client.search(query, **kw)
        items = [it for key in ("resources", "memories", "skills") for it in (res or {}).get(key, []) or []]
        out = []
        for it in items[:k]:
            text = str(it.get("content") or it.get("overview") or it.get("abstract") or "")[:1500]
            out.append({"doc": _guess_doc(text, self._corpus) or (it.get("uri") or ""), "text": text})
        return out


STACKS = {
    "mockgraph": lambda: MockGraphAdapter(),
    "lightrag": lambda: LightRAGAdapter("hybrid"),
    "lightrag_naive": lambda: LightRAGAdapter("naive"),
    "lightrag_local": lambda: LightRAGAdapter("local"),
    "lightrag_global": lambda: LightRAGAdapter("global"),
    "lightrag_hybrid": lambda: LightRAGAdapter("hybrid"),
    "lightrag_mix": lambda: LightRAGAdapter("mix"),
    "cognee": lambda: CogneeAdapter("GRAPH_COMPLETION"),
    "cognee_chunks": lambda: CogneeAdapter("CHUNKS"),
    "cognee_insights": lambda: CogneeAdapter("INSIGHTS"),
    "cognee_graph_completion": lambda: CogneeAdapter("GRAPH_COMPLETION"),
    "graphiti": lambda: GraphitiAdapter(None),
    "graphiti_rrf": lambda: GraphitiAdapter("rrf"),
    "graphiti_mmr": lambda: GraphitiAdapter("mmr"),
    "graphiti_cross_encoder": lambda: GraphitiAdapter("cross_encoder"),
    "openviking": lambda: OpenVikingAdapter(None),
    "openviking_thinking": lambda: OpenVikingAdapter("THINKING"),
}


# ── 실행 ──────────────────────────────────────────────────────


def _write_jsonl(stack, out_dir, adapter, anchors, k):
    ext_dir = Path(out_dir) / "external"
    ext_dir.mkdir(parents=True, exist_ok=True)
    out_path = ext_dir / f"{stack}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for a in anchors:
            units = adapter.search(a["query"], k)
            f.write(json.dumps({"anchor_id": a["id"], "units": units}, ensure_ascii=False) + "\n")
    return out_path


def run_stack(stack, corpus, anchors, out_dir, workdir, k=10):
    """어댑터 build→모든 앵커 search→output/eval/external/<stack>.jsonl. run_combo.run_external가 그대로 채점한다."""
    adapter = STACKS[stack]()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    adapter.build(corpus, workdir)
    build_sec = time.perf_counter() - t0
    out_path = _write_jsonl(stack, out_dir, adapter, anchors, k)
    print(f"[{stack}] 적재 {build_sec:.1f}s · 질의 {len(anchors)}건 → {out_path}", flush=True)
    return out_path


def run_from_cli(a):
    docs = sorted(p.name for p in Path(a.src).iterdir() if p.is_file())
    route = S.load_route(a.parse_dir)
    corpus, _ = S.load_corpus(a.parse_dir, docs, a.parse, route)
    anchors = A.load_anchors(Path(a.out) / "anchors.jsonl")
    if not anchors:
        raise SystemExit(f"{a.out}/anchors.jsonl 없음 — 먼저 python -m pipeline.eval.run_combo로 앵커를 만든다")
    workdir = a.workdir or (Path(a.out) / "external_work" / a.stack)
    run_stack(a.stack, corpus, anchors, a.out, workdir, k=a.k)


def build_cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stack", choices=sorted(STACKS), help="어댑터 이름(mockgraph만 이 PC에서 검증됨)")
    ap.add_argument("--parse-dir", default="output/parse")
    ap.add_argument("--src", default="output/corpus/docs")
    ap.add_argument("--parse", default="route", help="pipeline.eval.stages.load_corpus의 parse 설정(route·route2·엔진명)")
    ap.add_argument("--out", default="output/eval")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--workdir")
    return ap


def main(argv=None):
    a = build_cli().parse_args(argv)
    if not a.stack:
        raise SystemExit("--stack 필요")
    run_from_cli(a)


if __name__ == "__main__":
    utf8_stdout()
    from common.core.runlog import session

    with session("kg_external"):
        main()
