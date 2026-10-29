"""그림 기록의 edges(흐름도 연결) → Mermaid flowchart 글자(검토·보고서용). 순수 함수(네트워크·파일 없음).
실측(다른 세션, git 이력 docs/plans/comparison-report-structure-2026-10-03.md(c4874dd0^) §6): VLM edges → Mermaid 연결 F1 1.0(흐름도 10건 중 9건,
P&ID는 벡터 조각남으로 0.5)."""


def _qlabel(s):
    return '"' + str(s).replace('"', "'").replace("\n", " ") + '"'


def to_mermaid(edges):
    """edges[{from,to,label}] → "flowchart LR" 글자. edges 없거나 from·to 없는 것뿐이면 빈 문자열."""
    if not edges:
        return ""
    ids, lines = {}, []

    def nid(name):
        if name not in ids:
            ids[name] = f"n{len(ids)}"
        return ids[name]

    for e in edges:
        frm, to = e.get("from"), e.get("to")
        if not frm or not to:
            continue
        a, b = nid(frm), nid(to)
        label = e.get("label")
        arrow = f"-->|{_qlabel(label)}|" if label else "-->"
        lines.append(f"    {a}[{_qlabel(frm)}] {arrow} {b}[{_qlabel(to)}]")
    return "flowchart LR\n" + "\n".join(lines) if lines else ""
