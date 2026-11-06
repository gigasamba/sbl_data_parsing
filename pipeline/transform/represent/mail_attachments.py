"""문서 안 문서 후보정(pl-63·pl-36·pl-57) — 받기 단계가 준비 폴더 `_parts/<원본 이름>/`에 꺼내 둔 안 파일
(`parts.json` — pipeline.extract.unpack)을 형식별 구성 엔진 순서로 파싱하고, 결과는 P0 원본 층(raw_cache.raw_engine_path —
안 파일 sha256 + 엔진@버전)에 캐시해 다시 안 돈다. 대표 본문 끝에 `[파일 …]`(압축)·`[첨부 …]`(메일)·`[개체 …]`(오피스) 절로
덧붙이고, 오피스 개체는 있던 자리에 위치 표시 한 줄을 넣는다(못 찾으면 끝 절만). 메일은 인용 스레드도 단락화.
"""

import json
import re
import time
from pathlib import Path

from common.core.paths import APP_ROOT  # output/ 경계(attach_dir)
from pipeline import config as pc
from pipeline.extract.unpack import PARTS
from pipeline.shared.ext_groups import MAIL_EXTS
from pipeline.shared.raw_cache import raw_engine_path, raw_root
from pipeline.shared.vlmcall import sha
from pipeline.transform.parse.parse_engines import engine_version


def attach_dir():
    """첨부 임시 파일 폴더 — PARSE_TMP의 형제(기본 output/_tmp_parse/attach). 쓰는 쪽이 파일 하나 끝낼 때마다
    finally로 직접 지운다. 지우는 대상이라 APP_ROOT/output 아래 2단 이상만 허용."""
    tmp = Path(pc.cfg().paths.parse_tmp or (APP_ROOT / "output" / "_tmp_parse" / "stream"))
    root_out = (APP_ROOT / "output").resolve()
    rp = (tmp.parent / "attach").resolve()
    try:
        rel = rp.relative_to(root_out)
    except ValueError:
        rel = None
    if rel is None or len(rel.parts) < 2:
        raise SystemExit(f"[attach] 경로 거부 — {rp}는 {root_out} 아래 2단 이상 하위 폴더여야 함(PARSE_TMP 확인)")
    return rp


def parts_of(doc_path):
    """받기 단계가 꺼내 둔 안 파일 목록(parts.json)과 그 폴더 — 없으면 빈 목록(상자가 아님·받기 단계를 안 거침)."""
    d = Path(doc_path).parent / PARTS / Path(doc_path).name
    try:
        return d, json.loads((d / "parts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d, []


def place_marks(text, items):
    """오피스 개체가 있던 자리에 `[개체 <이름>]` 한 줄 — 파워포인트는 그 슬라이드 끝(쪽 나눔 \f 수가 슬라이드 수와 맞을 때만),
    엑셀은 그 시트 끝(다음 시트 이름표 앞), 워드는 개체 앞 문단 글이 든 줄 뒤. 자리를 못 찾으면 그대로(끝 절만)."""
    for it in items:
        w, mark = it["where"], f"[개체 {it['name']}]"
        if "slide" in w:
            segs = text.split("\f")
            if len(segs) == w["slides"]:
                segs[w["slide"] - 1] = segs[w["slide"] - 1].rstrip("\n") + "\n" + mark + "\n"
                text = "\f".join(segs)
        elif "sheet" in w:
            lines = text.split("\n")
            names = (w["sheet"], f"[숨김 시트] {w['sheet']}")
            heads = [i for i, ln in enumerate(lines) if ln.strip() in names]
            if heads:
                nexts = (w["next"], f"[숨김 시트] {w['next']}") if w["next"] else ()
                nxt = [i for i, ln in enumerate(lines) if i > heads[0] and ln.strip() in nexts]
                lines.insert(nxt[0] if nxt else len(lines), mark)
                text = "\n".join(lines)
        elif "after" in w:
            j = text.find(w["after"])
            if j >= 0:
                k = text.find("\n", j + len(w["after"]))
                k = len(text) if k < 0 else k
                text = text[:k] + "\n" + mark + text[k:]
    return text


# ── 첨부 1건 파싱(+ P0 캐시) ─────────────────────────────────────────────
def _stack_parse():
    return pc.stack().get("parse", {})  # 엔진 구성 파일(서버·PC 같음)


def parse_attachment(entry, store=None):
    """첨부 1건 → (텍스트, 캐시 적중?, 엔진) — stack.json이 그 형식에 지정한 엔진 순서로 시도해
    15자 이상 나온 첫 결과를 씀. P0 원본 층 키 = 첨부 sha256 + 엔진@버전(pipeline.shared.raw_cache.raw_engine_path) —
    같은 첨부를 같은 엔진으로 다시 안 돎."""

    store = store or raw_root()
    ext = Path(entry["name"]).suffix.lower()
    content_sha = sha(entry["bytes"])
    stack = _stack_parse()
    # stack.json은 PDF를 .pdf_text/.pdf_image로 나눠 둠(parse_engines와 같은 키) — 글자층 엔진 먼저, 15자 못 넘으면 OCR 엔진
    engines = stack.get(".pdf_text", []) + stack.get(".pdf_image", []) if ext == ".pdf" else stack.get(ext, [])
    for eng in engines:
        ver = engine_version(eng)
        dst = raw_engine_path(store, eng, ver, content_sha)
        if dst.exists():
            try:
                return json.loads(dst.read_text(encoding="utf-8")).get("text") or "", True, eng
            except (OSError, ValueError):
                pass
        adir = attach_dir()  # 강제 종료돼도 남은 파일은 다음 실행이 같은 이름으로 덮음
        adir.mkdir(parents=True, exist_ok=True)
        tmp = adir / f"attach-{content_sha[:12]}{ext}"
        out_json = tmp.with_suffix(tmp.suffix + ".json")
        try:
            tmp.write_bytes(entry["bytes"])
            # 별도 프로세스 + 시간 제한 — 멈추는 엔진이 대표 결과 만들기 전체를 세우지 않게
            from pipeline.transform.parse.parse_engines import _isolated

            _isolated(eng, tmp, out_json, "default", pc.cfg().extract.attach.timeout)
            res = json.loads(out_json.read_text(encoding="utf-8"))
        except Exception:
            continue  # 미설치·파싱 실패·시간 초과 — 스택 순서대로 다음 엔진
        finally:
            tmp.unlink(missing_ok=True)
            out_json.unlink(missing_ok=True)
        text = (res.get("text") or "").strip()
        if len(text) < 15:
            continue
        res["provenance"] = {
            "engine": eng,
            "engine_version": ver,
            "source_file": entry["name"],
            "source_sha256": content_sha,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        return res.get("text") or "", False, eng
    return "", False, None


# ── 인용 스레드 단락화 ───────────────────────────────────────────────────
_WROTE = re.compile(r"^On\s+(?P<rest>.+)\s+wrote:\s*$", re.I)  # "On <날짜>, <발신자> wrote:" — 날짜 안에도 쉼표가 있어 마지막 쉼표로 가름
_ORIG = re.compile(r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.I)
_HDR = re.compile(r"^(?P<key>From|Sent|Date|보낸\s*사람|날짜)\s*[:：]\s*(?P<val>.+)$", re.I)
_QUOTE = re.compile(r"^>+\s?")


def thread_paragraphs(text):
    """'>' 인용·Outlook 'Original Message' 구간을 날짜·발신자 단락으로(헤더 못 찾으면 '[인용]'만) — 모자라게.
    인용 구간이 없으면 빈 글자(mail_blocks가 블록으로만 덧붙이므로 base_text는 항상 그대로)."""
    plain = [(_QUOTE.sub("", ln.lstrip(), count=1) if _QUOTE.match(ln.lstrip()) else ln) for ln in (text or "").splitlines()]
    starts = [i for i, ln in enumerate(plain) if _WROTE.match(ln.strip()) or _ORIG.match(ln.strip())]
    if not starts:
        return ""
    starts.append(len(plain))
    paras = []
    for a, b in zip(starts, starts[1:]):
        head, body = plain[a].strip(), plain[a + 1 : b]
        m = _WROTE.match(head)
        if m:
            rest = m["rest"].strip()
            date, _, sender = rest.rpartition(",")
            date, sender = (date.strip(), sender.strip()) if date else (None, rest)
            sender = re.sub(r"\s*<[^>]+>\s*$", "", sender).strip() if sender else sender
        else:
            sender, date = None, None
        for ln in body[:6]:
            hm = _HDR.match(ln.strip())
            if hm:
                key = hm["key"].strip().lower()
                if key in ("from", "보낸 사람") and not sender:
                    sender = hm["val"].strip()
                elif key in ("sent", "date", "날짜") and not date:
                    date = hm["val"].strip()
        label = " · ".join(x for x in (date, sender) if x)
        content = "\n".join(ln for ln in body if ln.strip())
        if content:
            paras.append((f"[인용 {label}]" if label else "[인용]") + "\n" + content)
    return "\n\n".join(paras)


# ── doc_represent.apply_post가 부르는 진입점 ─────────────────────────────────────────
def mail_blocks(doc_path, base_text):
    """→ (위치 표시를 넣은 본문, 덧붙일 블록 목록, 통계{n, parsed, cached, sources}). 메일은 인용 스레드 단락을 먼저.
    안 파일은 받기 단계가 꺼낸 것만(크기·개수·깊이 상한도 거기서 — unpack). 꺼낸 것이 없으면 (본문 그대로, 빈 목록, 0 통계)."""
    stats = {"n": 0, "parsed": 0, "cached": 0, "sources": []}
    blocks = []
    if Path(doc_path).suffix.lower() in MAIL_EXTS:
        th = thread_paragraphs(base_text)
        if th:
            blocks.append(th)
    d, items = parts_of(doc_path)
    marks = []
    for it in items:
        stats["n"] += 1
        try:
            data = (d / it["file"]).read_bytes()
        except OSError:
            continue
        text, cached, _eng = parse_attachment({"name": it["name"], "bytes": data})
        if not text:
            continue
        stats["parsed"] += 1
        stats["cached"] += int(cached)
        stats["sources"].append(f"{Path(doc_path).name}#{it['name']}")  # 원본 위치 = 원본#안 경로
        blocks.append(f"[{it['kind']} {it['name']}]\n{text}")
        if it["depth"] == 1 and it.get("where"):  # 이 문서에 바로 든 개체만(더 깊은 것의 위치는 그 안 문서 기준)
            marks.append(it)
    return place_marks(base_text, marks), blocks, stats
