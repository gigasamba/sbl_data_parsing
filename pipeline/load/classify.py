"""분류(pl-33, 사용자 11-02) — SFDC·LAS 문서에 종류 라벨 `doc_class`를 붙인다. 판단은 운영 분류와 같게(라벨 집합·지시문 구조·근거·
경계 규칙), 흐름은 적재와 하나다: 적재(pgvector_load)가 EDW 메타를 붙인 직후, gold에 넣기 전에 한다 — 고르는 규칙을 따로 두지 않는다
(적재가 고른 문서 그대로 · 같은 내용은 묶음이 한 문서만 남김 · 파싱 안 된 문서는 gold에 오지 않음).
· 모델은 `llm.chat`(역할 llm — 예산 장부, 서버는 내부 GLM, PC는 외부 허용·가짜 LLM). effort는 설정 `common.models.llm.extra_body`.
· 본문 근거 = 게시가 올리는 대표 결과 .md(render_md — silver와 같은 글)의 앞 TEXT_CHARS자.
· 답은 JSON {"class", "confidence"} — 라벨 집합 밖이면 실패. 다시 묻지 않는다(재시도 없음). 실패한 문서는 그 문서의 적재 실패로 본다:
  gold에 넣지 않아 gold_version이 안 적히고 다음 정상 실행이 다시 고른다(사용자 11-02). 감사 한 줄.
· 이미 라벨이 있는 문서는 덮지 않는다."""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

TEXT_CHARS = 8000
LABELS = {
    "sfdc": ("RFI", "RFP", "RFI+RFP", "Proposal", "Other"),
    "las": ("MSA", "PSA", "QAG", "LOI", "Amendment", "Assignment Letter", "Other"),
}
AGENT = {"sfdc": "classify_sfdc", "las": "classify_las"}
ALIASES = {"RFP+RFI": "RFI+RFP"}
MAX_TOKENS = 4096


# ── 라벨·모델 글자 ─────────────────────────────────────────────────────────────
def _norm(s):
    return re.sub(r"\s+", "", str(s)).upper()


def label_of(raw, src):
    """모델이 고른 라벨 글자 → 집합 안 라벨(대소문자·공백·별칭 바로잡음) 또는 None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    k = _norm(raw)
    k = {_norm(x): _norm(y) for x, y in ALIASES.items()}.get(k, k)
    return {_norm(x): x for x in LABELS[src]}.get(k)


def parse_answer(text, src):
    """응답 글자 → 라벨 또는 None. 코드 울타리를 벗기고 첫 JSON 객체의 class를 읽는다(참거짓·숫자·NaN은 None)."""
    if not isinstance(text, str):
        return None
    t = re.sub(r"```(?:json)?", "", text)
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", t):
        try:
            obj, _ = dec.raw_decode(t[m.start() :])
        except ValueError:
            continue
        if isinstance(obj, dict) and "class" in obj:
            return label_of(obj.get("class"), src)
    return None


# ── LAS 키워드 근거(코드가 미리 찾아 지시문에 보여 줌 — 판단은 모델) ─────────────────────
_TYPES = {  # 계약 종류 → 본문·파일 이름에서 찾는 전체 이름
    "MSA": (r"master\s+services?\s+agreement",),
    "PSA": (r"product\s+specific\s+agreement", r"project\s+specific\s+agreement"),
    "QAG": (r"quality\s+agreement",),
    "LOI": (r"letter\s+of\s+intent",),
    "Amendment": (r"amendment",),
    "Assignment Letter": (r"assignment", r"novation"),
}
_NAME_ABBR = {"QAG": r"\bqag\b", "PSA": r"\bpsa\b", "LOI": r"\bloi\b"}  # 파일 이름 약어 — MSA는 전체 이름만
_AMEND = r"amend|amendment|변경"
_MEMO = r"\bmemo\b|\bbefore\b|\bdecision\b|request\s+for|\breport\b|검토|보고"


def las_signals(file_name, text):
    """LAS 키워드 근거 줄들 — ① 본문 앞 300자 자기 이름 ② 공백 정리한 앞 2,000자의 계약 종류 전체 이름 ③ 파일 이름 키워드
    ④ 파일 이름 변경 키워드, 그리고 경고(보고서·메모 같은 제목, 두 종류 이상)."""
    head300 = text[:300]
    m = re.search(r"\bTHIS\s+([A-Za-z &\-]{2,80}?)\s+AGREEMENT\b", head300, re.I)
    lines = [f"① 자기 이름(본문 앞 300자): {('THIS ' + m.group(1).strip() + ' AGREEMENT') if m else '뚜렷한 자기 이름 없음'}"]
    body = re.sub(r"\s+", " ", text[:2000]).lower()
    in_body = [k for k, pats in _TYPES.items() if any(re.search(p, body) for p in pats)]
    lines.append(f"② 본문 앞 2,000자의 계약 종류 이름: {', '.join(in_body) or '없음'}")
    name = re.sub(r"_+", " ", file_name or "").lower()
    in_name = [k for k, pats in _TYPES.items() if any(re.search(p, name) for p in pats)]
    in_name += [k for k, p in _NAME_ABBR.items() if re.search(p, name) and k not in in_name]
    lines.append(f"③ 파일 이름 키워드: {', '.join(in_name) or '없음'}")
    lines.append(f"④ 파일 이름 변경 키워드: {'있음' if re.search(_AMEND, name) else '없음'}")
    if re.search(_MEMO, name):
        lines.append("경고: 파일 이름이 보고서·메모처럼 보임")
    kinds = set(in_body) | set(in_name)
    if len(kinds) >= 2:
        lines.append(f"경고: 두 종류 이상이 보임({', '.join(sorted(kinds))}) — 확신도는 0.80 이하로")
    return lines


# ── 지시문 사용자 쪽 ───────────────────────────────────────────────────────────
def _fmt(file_name):
    return Path(file_name or "").suffix.lstrip(".").lower() or "알 수 없음"


def user_message(src, doc, ctx, text):
    """문서 하나의 사용자 쪽 글 — 문서 정보 묶음 + (LAS) 키워드 근거 + 본문 앞 TEXT_CHARS자."""
    name = doc.get("original_filename") or Path(doc["file_path"]).name
    info = [f"- 원본 파일 이름: {name}", f"- 파일 형식: {_fmt(name)}"]
    if src == "sfdc":
        if ctx.get("title"):
            info.insert(0, f"- 제목: {ctx['title']}")
        for k, label in (
            ("entities", "연결된 SFDC 개체"),
            ("channel", "채널(제목·방향)"),
            ("opportunity", "영업 기회"),
            ("stage", "기회 단계"),
        ):
            if ctx.get(k):
                info.append(f"- {label}: {ctx[k]}")
    else:
        for k, label in (("approval_name", "품의 제목"), ("counterparty", "상대방")):
            if ctx.get(k):
                info.append(f"- {label}: {ctx[k]}")
    parts = ["## 문서 정보", *info]
    if src == "las":
        parts += ["", "## 키워드 근거", *[f"- {x}" for x in las_signals(name, text)]]
    parts += ["", f"## 본문(앞 {TEXT_CHARS}자)", text[:TEXT_CHARS]]
    return "\n".join(parts)


# ── 분류 ─────────────────────────────────────────────────────────────────────
def _system(src):
    from common.ai.agent_prompts import load

    return load(AGENT[src], AGENT[src])


def classify_one(src, doc, ctx, text, chat=None):
    """문서 하나 → (라벨 또는 None, 오류 글 또는 None). LLM 한 번, 다시 묻지 않음."""
    if chat is None:
        from common.ai import llm

        chat = llm.chat
    try:
        out = chat(
            [{"role": "system", "content": _system(src)}, {"role": "user", "content": user_message(src, doc, ctx, text)}],
            max_tokens=MAX_TOKENS,
            json_mode=True,
            agent=AGENT[src],
        )
    except Exception as e:  # 모델 장애·예산 초과 — NULL(재시도 없음)
        return None, f"{type(e).__name__}: {str(e)[:200]}"
    lab = parse_answer(out, src)
    return lab, (None if lab else f"라벨 집합 밖·읽을 수 없는 답: {str(out)[:200]!r}")


def apply(docs, texts, contexts, existing, audit_path=None, chat=None, now=None):
    """적재 직전 — docs(묶음 문서, 원천 SFDC·LAS만 대상)에 doc_class를 채운다.
    texts {file_path: 본문}, contexts {file_path: 문서 정보}, existing {file_path: 이미 gold에 있는 라벨 — 덮지 않음}.
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
        text = texts.get(fp)
        if not text:
            lab, err = None, "대표 결과 본문 없음"
        else:
            lab, err = classify_one(src, d, contexts.get(fp) or {}, text, chat)
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


def rep_texts(docs, rep_dir):
    """대표 결과 폴더(_rep/<이름>.json) → {file_path: 게시가 올리는 .md 글(render_md — silver와 같은 글)}. 없으면 묶음의 full_text."""
    from pipeline.load.parsing_meta import render_md

    out = {}
    for d in docs:
        p = Path(rep_dir) / f"{d.get('doc_name')}.json" if rep_dir else None
        if p and p.exists():
            out[d["file_path"]] = render_md(json.loads(p.read_text(encoding="utf-8")))
        elif d.get("full_text"):
            out[d["file_path"]] = d["full_text"]
    return out
