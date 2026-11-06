"""분류 — SFDC·LAS 문서에 종류 라벨 `doc_class`를 붙인다. 운영 분류와 같게: 지시문은 운영 글자 그대로
(resources/prompts/pipeline/classify_sfdc·classify_las), 사용자 쪽 글(문서 정보·LAS 키워드 근거·본문 8,000자)도 운영 코드와 같은 모양.
흐름은 적재와 하나다 — 적재(pgvector_load)가 EDW 메타(edw_meta — 분류 힌트 칸 포함)를 붙인 직후, gold에 넣기 전. 힌트는 그 문서 행의
gold 칸에서 읽는다. 고르는 규칙을 따로 두지 않는다(같은 내용은 묶음이 한 문서만 · 파싱 안 된 문서는 gold에 안 옴).
· 모델은 `llm.chat`(역할 llm — 예산 장부, 서버는 내부 GLM, PC는 LLM_ALLOW_EXTERNAL=1이면 외부 모델·또는 가짜 LLM). effort는 설정 `common.models.llm.extra_body`.
· 답은 JSON의 class만 읽는다(확신도는 쓰지 않음). 라벨 집합 밖이면 실패. 다시 묻지 않는다. 실패한 문서는 그 문서의
  적재 실패 — gold에 넣지 않아 gold_version이 안 적히고 다음 정상 실행이 다시 고른다. 감사 한 줄.
· 이미 라벨이 있는 문서는 덮지 않는다."""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

TEXT_CHARS = 8000
FRONT = 2000  # LAS 키워드 근거 ② — 본문 앞 글자 수(운영 그대로)
LABELS = {
    "sfdc": ("RFI", "RFP", "RFI+RFP", "Proposal", "Other"),
    "las": ("MSA", "PSA", "QAG", "LOI", "Amendment", "Assignment Letter", "Other"),
}
AGENT = {"sfdc": "classify_sfdc", "las": "classify_las"}
SFDC_ALIASES = {
    "rfi": "RFI",
    "rfp": "RFP",
    "rfi+rfp": "RFI+RFP",
    "rfp+rfi": "RFI+RFP",
    "proposal": "Proposal",
    "other": "Other",
}  # 운영 그대로
MAX_TOKENS = 4096


# ── 답 읽기 ─────────────────────────────────────────────────────────────────────
def parse_answer(text, src):
    """응답 → 라벨 또는 None. 운영 parse_answer와 같은 찾기(코드 울타리를 벗기고 class(SFDC는 doc_class도)가 있는 첫 JSON 객체).
    SFDC는 운영 별칭표(소문자·공백 뺌), LAS는 집합 안 글자(앞뒤 공백 정리 — 운영은 집합 확인이 없었지만 집합 밖은 실패)."""
    s = text.strip() if isinstance(text, str) else ""
    if s.startswith("```"):
        s = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```[A-Za-z0-9_-]*\s*$", "", s).strip()
    keys = ("class", "doc_class") if src == "sfdc" else ("class",)
    dec = json.JSONDecoder()
    i = 0
    while (j := s.find("{", i)) != -1:
        i = j + 1
        try:
            obj, _ = dec.raw_decode(s, j)
        except ValueError:
            continue
        if isinstance(obj, dict) and any(k in obj for k in keys):
            raw = next((obj[k] for k in keys if obj.get(k)), None)
            if not isinstance(raw, str):
                return None
            if src == "sfdc":
                return SFDC_ALIASES.get(raw.strip().lower().replace(" ", ""))
            return raw.strip() if raw.strip() in LABELS["las"] else None
    return None


# ── SFDC 제목 키워드 묶음(운영 analyze_clues 그대로 — 분류 때 계산) ─────────────────────
FAMILIES = {
    "rfi": re.compile(r"\brfi\b|request for information", re.I),
    "rfp": re.compile(r"\brfp\b|request for( a)? proposal", re.I),
    "rfq": re.compile(r"\brfq\b|\bbid(s)?\b|tender", re.I),
    "proposal": re.compile(r"proposal|제안", re.I),
    "pricing": re.compile(r"pricing|quotation|견적|\bprice\b|시세", re.I),
    "legal": re.compile(r"\bloi\b|\bpsa\b|\bmsa\b|\bcda\b|\bnda\b|agreement|contract|품의|계약|\bsow\b", re.I),
    "meeting": re.compile(
        r"meeting|call report|minutes|회의|conference|dcat|jpm|bio ?asia|peg ?s|cphi|site visit|tc with|partnering", re.I
    ),
    "tech": re.compile(
        r"tech(nology)? transfer|process description|purification|upstream|downstream|cell bank|batch record|\bbds\b|fermentation|chromatography",
        re.I,
    ),
    "system": re.compile(r"^(log-|login|reportexport|lightningpageview|dashboard|report-)", re.I),
}


def fams(title):
    """제목 → 맞는 묶음 이름들(FAMILIES 순서). system이 있으면 system만."""
    hits = [k for k in FAMILIES if FAMILIES[k].search(title or "")]
    return ["system"] if "system" in hits else hits


# ── LAS 키워드 근거(운영 extract_evidence 그대로 — 정규식 글자 포함) ─────────────────────
MAIN_KW = [
    ("QAG", re.compile(r"quality\s+agreements?|품질계약|품질협정", re.I), re.compile(r"(?<![A-Za-z])QA[GA](?![A-Za-z])", re.I)),
    ("PSA", re.compile(r"product\s+specific\s+agreements?", re.I), re.compile(r"(?<![A-Za-z])PSA(?![A-Za-z])", re.I)),
    ("MSA", re.compile(r"master\s+(?:services?|purchase)\s+agreements?|주계약|기본계약", re.I), None),
    ("LOI", re.compile(r"letter\s+of\s+intent|의향서|양해각서", re.I), re.compile(r"(?<![A-Za-z])LOI(?![A-Za-z])", re.I)),
]
NOV_PAT = re.compile(r"(?<![A-Za-z])novation(?![A-Za-z])|assignment\s+and\s+assumption|계약양도", re.I)
OTHER_PAT = re.compile(
    r"(?<![A-Za-z])(NDA|CDA|MTA|TTA|TMA|MOU|SOWSoW|PSR|LOU)(?![A-Za-z])|"  # 'SOWSoW'는 운영 글자 그대로(같은 결과를 내려고 고치지 않음)
    r"statement\s+of\s+work|scope\s+of\s+work|work\s+order|service\s+order|order\s+form|"
    r"termination\s+agre|sequence\s+transfer|side\s*letter|letter\s+agreement|"
    r"letter\s+of\s+understanding|memorandum\s+of\s+understanding|"
    r"material\s+transfer\s+agre|non[-\s]?disclosure\s+agre|"
    r"confidential(ity)?\s+disclosure\s+agre|partnering\s+agre|"
    r"비밀유지|시설대|리스|보험|용역|품의|결과보고",
    re.I,
)
DR_PAT = re.compile(r"decision\s+report|(?<![A-Za-z])DR(?=[ _\-.(\d\]])|품의|결과보고", re.I)
REFUSE_PAT = re.compile(
    r"memo|before|month\s+of|dec\s+\d|decision(?!\s+report\s+for\s+(MSA|PSA|QAG|LOI))|"
    r"scope\s+of\s+work(?!\s*agreement)|request\s+for|draft\s+for|"
    r"prior\s+to|in\s+preparation|비용|예산",
    re.I,
)
AMEND_PAT = re.compile(r"amendment|addendum|(?<![A-Za-z])AM(?=\s*No)|변경합의|개정", re.I)
SELF_ID = [
    ("MSA", r"this\s+master\s+(?:development\s+)?services?\s+agreement|master\s+(?:development\s+)?services?\s+agreement\s+between"),
    ("PSA", r"this\s+product\s+specific\s+agreement|this\s+supply\s+agreement|product\s+specific\s+agreement\s+between"),
    ("QAG", r"this\s+quality\s+agreement|quality\s+agreement\s+between|this\s+technical\s*[-\s]*quality"),
    ("LOI", r"this\s+letter\s+of\s+intent|letter\s+of\s+intent\s+between"),
    ("Amendment", r"this\s+amendment|amendment\s+(no|number)\s*\d"),
    ("Other", r"this\s+memorandum|this\s+decision\s+report|품의|re\s*:|memo"),
]
CORE_TYPES = {"MSA", "PSA", "QAG", "LOI", "Amendment", "Novation", "Other-type", "DR"}


def las_evidence(fn, body):
    """운영 extract_evidence(fn, body)와 같은 글 — Signal ①~④·충돌 경고."""
    title = fn.replace("_", " ")
    front = (body or " ").replace("_", " ")[:FRONT]
    body_start = (body or " ").strip()[:300].replace("_", " ")
    lab0 = next((lab for lab, pat in SELF_ID if re.search(pat, body_start, re.I)), None)
    opening = (
        f"  Signal①(BODY OPENING): Document starts with '{lab0}' self-identification"
        if lab0
        else f"  Signal①(BODY OPENING): '{body_start[:80]}' (no clear self-ID in first line)"
    )
    b2 = []
    for name, fp, _ap in MAIN_KW:
        m = fp.search(front)
        if m:
            b2.append(f"{name}('{m.group(0)[:16]}')")
    if NOV_PAT.search(front):
        b2.append("Novation/Assignment")
    if OTHER_PAT.search(front):
        b2.append("Other-type")
    t3 = []
    for name, fp, ap in MAIN_KW:
        m1 = fp.search(title)
        m2 = ap.search(title) if ap else None
        if m1:
            t3.append(f"{name}(full:'{m1.group(0)[:14]}')")
        elif m2:
            t3.append(f"{name}(abbr:'{m2.group(0)[:8]}')")
    if NOV_PAT.search(title):
        t3.append("Novation")
    if OTHER_PAT.search(title):
        t3.append("Other-type")
    if DR_PAT.search(title):
        t3.append("DR/DecisionReport")
    amend = bool(AMEND_PAT.search(title))
    sig = ({lab0} if lab0 else set()) | {e.split("(")[0] for e in b2 + t3}
    found = {x for x in sig if x in CORE_TYPES or x.startswith("Other")}
    conflicts = []
    if len(found) >= 2:
        conflicts.append(f"⚠ MULTIPLE TYPE SIGNALS: {', '.join(sorted(found))}")
    if amend:
        conflicts.append("⚠ Amendment keyword present — check parent")
    r = REFUSE_PAT.search(title)
    if r:
        conflicts.append(f"⚠ Title reference keyword '{r.group(0)}' — may be REPORT/MEMO context")
    ev = [
        "## Keyword Evidence (evaluate by Signal Priority ①→②→③→④)",
        opening,
        f"  Signal②(BODY first-2000): {'; '.join(b2) if b2 else '(none)'}",
        f"  Signal③(TITLE keywords): {'; '.join(t3) if t3 else '(none)'}",
    ]
    if amend:
        ev.append("  Signal④(AMENDMENT): YES — title contains amendment keyword")
    if conflicts:
        ev += ["", *conflicts, "  → SIGNALS CONFLICT — you MUST lower confidence to ≤0.80"]
    return "\n".join(ev)


# ── 사용자 쪽 글(운영 코드와 같은 모양) ──────────────────────────────────────────────
def _s(v):
    return "" if v is None else str(v)


def sfdc_user(doc, rep):
    """운영 build_user_prompt와 같은 글 — 힌트는 문서 attrs(EDW 사슬 키). 제목이 비면 원본 파일 이름. rep = {text, format, engine}."""
    fn = Path(doc["file_path"]).name
    h = doc.get("attrs") or {}  # 힌트 키(title·entity_*·sent_received__c·subject·stagename·real_rfp__c·rfp_*)
    title = h.get("title") or fn
    lines = [
        "## Document metadata",
        f"- Title: {title}",
        f"- Original filename: {fn}",
        f"- File format: {_s(rep.get('format'))} (representative parse engine: {_s(rep.get('engine'))})",
    ]
    if h.get("entity_class"):  # 운영 `if f:` — EDW 사슬이 이 파일을 찾았으면 늘 있음(연결 없음도 unlinked)
        lines.append(f"- SFDC entity: type={_s(h.get('entity_type'))} class={h['entity_class']} id={_s(h.get('entity_id'))}")
        direction = _s(h.get("sent_received__c")).strip()
        if direction:
            lines.append(f"- Communication channel: direction={direction}, subject={_s(h.get('subject'))[:300]}")
        if _s(h.get("stagename")).strip():
            lines.append(
                f"- Opportunity: stage={h['stagename']}, Real_RFP__c={_s(h.get('real_rfp__c'))}, "
                f"rfp_window={_s(h.get('rfp_received_start_date__c'))}~{_s(h.get('rfp_received_end_date__c'))}"
            )
        kw = "|".join(fams(title))
        if kw:
            lines.append(f"- Title keyword families: {kw}")
    lines += ["", f"## Document text (first {TEXT_CHARS} chars of parsed Markdown)", rep["text"][:TEXT_CHARS]]
    return "\n".join(lines)


def las_user(doc, rep):
    """운영 LAS 사용자 쪽 글과 같은 모양 — 상대방은 gold client_edw(LAS.Contract.PartnerCorpName)."""
    fn = doc["file_path"].split("/")[-1]
    up = ["## Document metadata", f"- Original filename: {fn}", f"- File format: {_s(rep.get('format'))}"]
    appr = (doc.get("attrs") or {}).get("approvalname")  # 힌트는 attrs
    if appr:
        up.append(f"- Approval title: {appr}")
    if doc.get("client_edw"):
        up.append(f"- Counterparty: {doc['client_edw']}")
    body = rep["text"]
    up += ["", las_evidence(fn, body), f"## Document text (first {TEXT_CHARS} chars)", body[:TEXT_CHARS]]
    return "\n".join(up)


USER = {"sfdc": sfdc_user, "las": las_user}


# ── 분류 ─────────────────────────────────────────────────────────────────────
def _system(src):
    from common.ai.agent_prompts import load

    return load(AGENT[src], AGENT[src])


def classify_one(src, doc, rep, chat=None):
    """문서 하나 → (라벨 또는 None, 오류 글 또는 None). LLM 한 번, 다시 묻지 않음."""
    if chat is None:
        from common.ai import llm

        chat = llm.chat
    try:
        out = chat(
            [{"role": "system", "content": _system(src)}, {"role": "user", "content": USER[src](doc, rep)}],
            max_tokens=MAX_TOKENS,
            json_mode=True,
            agent=AGENT[src],
        )
    except Exception as e:  # 모델 장애·예산 초과 — 실패(재시도 없음)
        return None, f"{type(e).__name__}: {str(e)[:200]}"
    lab = parse_answer(out, src)
    return lab, (None if lab else f"라벨 집합 밖·읽을 수 없는 답: {str(out)[:200]!r}")


def apply(docs, reps, existing, audit_path=None, chat=None, now=None):
    """적재 직전 — docs(묶음 문서 — EDW 메타·힌트 칸이 붙은 행, 원천 SFDC·LAS만 대상)에 doc_class를 채운다.
    reps {file_path: {text, format, engine}}, existing {file_path: 이미 gold에 있는 라벨 — 덮지 않음}.
    반환: 분류에 실패한 file_path 집합 — 적재가 그 문서를 넣지 않는다(다음 정상 실행이 다시 고름)."""
    from common.store.db.models import search_tables as ST

    at = (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M:%S")
    failed, audit = set(), []
    for d in docs:
        src = ST.source_of(d.get("source_system"))
        if src not in LABELS:
            continue
        fp = d["file_path"]
        if existing.get(fp) or d.get("doc_class"):  # 이미 라벨 있음(gold 또는 묶음) — 덮지 않음(운영과 같음)
            d["doc_class"] = existing.get(fp) or d["doc_class"]
            continue
        rep = reps.get(fp) or {}
        if not (rep.get("text") or "").strip():
            lab, err = None, "대표 결과 본문 없음"
        else:
            lab, err = classify_one(src, d, rep, chat)
        d["doc_class"] = lab
        if lab is None:
            failed.add(fp)
        audit.append({"at": at, "file_path": fp, "source": src, "doc_class": lab, "error": err})
    if audit_path and audit:
        p = Path(audit_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            for r in audit:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if audit:
        print(f"[classify] {len(audit)}건 분류 · 실패 {len(failed)}건(적재하지 않음 — 다음 실행에 다시)", file=sys.stderr, flush=True)
    return failed


def rep_inputs(docs, rep_dir):
    """대표 결과 폴더(_rep/<이름>.json) → {file_path: {text: 게시가 올리는 .md(render_md — silver와 같은 글), format, engine}}
    (format·engine = 대표 결과 index의 형식·대표 엔진). 대표 결과가 없으면 묶음의 full_text(형식·엔진 비움)."""
    from pipeline.load.publish_parse_result import render_md

    out = {}
    for d in docs:
        p = Path(rep_dir) / f"{d.get('doc_name')}.json" if rep_dir else None
        if p and p.exists():
            rep = json.loads(p.read_text(encoding="utf-8"))
            out[d["file_path"]] = {"text": render_md(rep), "format": rep.get("format"), "engine": rep.get("engine")}
        elif d.get("full_text"):
            out[d["file_path"]] = {"text": d["full_text"], "format": None, "engine": None}
    return out
