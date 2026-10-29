"""LLM 그래프 모드 — 청크마다 LLM으로 (주어, 관계, 목적어) 삼중항을 뽑아 networkx 그래프에 더한다(PC 전용 평가 실험).
S6a(10-26, D-019 ③ · T-02) — pipeline/eval/stages.py build_graph의 `elif mode == "llm":` 본문을 옮김(들여쓰기 한 단만 줄임 —
글자는 그대로). 지시서 triple_extract(같은 폴더)도 여기서만 읽는다. import하면 stages.GRAPH_MODES["llm"]에 등록되고,
stages.graph_mode_ready("llm")가 처음 쓸 때 이 모듈을 부른다(run_combo `--graph llm`·kg_external mockgraph). 서버 이미지에는 없다.
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)

# isort: split
from common.ai.agent_prompts import load as _load_prompt  # AD33: 지시문 글자는 지시서 패키지 prompt.md
from common.config.settings import cfg  # S7e2 설정 객체
from common.core.text import normalize_value
from pipeline.eval import stages as S  # 등록표(GRAPH_MODES)

_TRIPLE_SYSTEM = _load_prompt(
    "triple_extract", "triple_system"
)  # AD33 — 글자는 validation/e2e/triple_extract/prompt.md(S6a — 옛 stages.py 모듈 상수)


def build_llm_graph(G, chunks):
    """G(청크 노드가 이미 있음)에 삼중항 간선을 더하고 지표 추가분(llm_calls·llm_triples·llm_error)을 돌려준다."""
    from common.ai import llm as L

    allow_ext = bool(
        cfg().models.llm.allow_external
    )  # truth.json 쓰는 개발 PC 실험에서만 켤 것 — 회사 문서는 내부망 LLM만(DONT 13) · S7e2 설정 객체(옛 env == "1")
    calls_before = L.usage()["calls"]
    n_triples, llm_error = 0, None
    for c in chunks:
        try:
            text = L.chat(
                [{"role": "system", "content": _TRIPLE_SYSTEM}, {"role": "user", "content": f"문서: {c['doc']}\n{c['text']}"}],
                json_mode=True,
                allow_external=allow_ext,
                agent="triple_extract",
            )
            triples = L.parse_json(text).get("triples") or []
        except L.LLMUnavailable as e:
            llm_error = str(e)  # 설정 안 됨·외부 주소 가드 — 청크 순회를 멈추고 지금까지 만든 그래프로 계속(전체 실행은 안 죽는다)
            break
        except Exception as e:
            llm_error = f"{type(e).__name__}: {e}"[:200]
            continue  # 이 청크만 건너뜀(응답 파싱 실패 등)
        node_chunk = ("chunk", c["id"])
        for tri in triples:
            if not (isinstance(tri, (list, tuple)) and len(tri) == 3 and all(tri)):
                continue
            s, r, o = tri
            es, eo = ("entity", normalize_value(s)), ("entity", normalize_value(o))
            G.add_node(es, kind="entity", label=str(s))
            G.add_node(eo, kind="entity", label=str(o))
            for nd in (es, eo):
                G.nodes[nd].setdefault("src", set()).add(c["id"])
            G.add_edge(es, eo, type=str(r)[:60])
            G.add_edge(node_chunk, es, type="mentions")
            G.add_edge(node_chunk, eo, type="mentions")
            n_triples += 1
    llm_extra = {"llm_calls": L.usage()["calls"] - calls_before, "llm_triples": n_triples}
    if llm_error:
        llm_extra["llm_error"] = llm_error
    return llm_extra


S.GRAPH_MODES["llm"] = build_llm_graph
