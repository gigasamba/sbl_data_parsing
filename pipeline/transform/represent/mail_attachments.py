"""W17 — 메일(.eml·.msg) 첨부 재귀 파싱 + 인용 스레드 단락화(post feature). docs/backlog.md W17 참고.
원본 파서 층(P0)은 그대로 두고(W10 설계), represent.py가 --src 원본(doc_path)에서 첨부를 꺼내 형식별 엔진
(stack.json "parse" 순서, 예: .xlsx → kreuzberg/office)으로 파싱한다. 결과는 P0 원본 층(pipeline.shared.parse_run.
raw_engine_path, 첨부 sha256 + 엔진@버전 키)에 캐시해 다시 안 돎. 대표 본문에는 `[첨부 <파일명>]` 절로 덧붙인다
(블록으로만 덧붙임 — base_text 자체는 안 건드려 PARSE_POST=none·이 기능 OFF 시 바이트 동일 보장).
인라인 그림(cid)은 그림 기능(figure_extract.py)이 담당 — 여기서는 image/* 첨부를 건너뛴다.
zip 첨부는 ATTACH_MAX_DEPTH(기본 1)만큼만 풀고, 크기(ATTACH_MAX_MB 기본 20)·개수(ATTACH_MAX_N 기본 10) 상한을 넘으면 건너뜀.
"""

import email
import hashlib
import io
import json
import re
import time
import zipfile
from email import policy
from pathlib import Path

from common.core.paths import APP_ROOT  # output/ 경계(attach_dir)
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.shared import parse_run as P0
from pipeline.shared.post_config import raw_root  # PARSE_RAW_ROOT(이중 raw/ 방지, post/__init__.py)


def attach_dir():
    """첨부 임시 파일 폴더 — PARSE_TMP의 형제(기본 output/_tmp_parse/attach). 쓰는 쪽이 파일 하나 끝낼 때마다
    finally로 직접 지운다. APP_ROOT/output 아래 2단 이상만 허용(독립 보안 검토 BLOCKER 1 — 지우는 대상이라 범위를 좁힘,
    op-08에 지운 pipeline/stream.py에서 옮김)."""
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


def _max_depth():
    return pc.cfg().extract.attach.max_depth  # S7c — 설정 객체


def _max_mb():
    return pc.cfg().extract.attach.max_mb  # S7c — 설정 객체


def _max_n():
    return pc.cfg().extract.attach.max_n  # S7c — 설정 객체


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ── 첨부 꺼내기(형식별) ───────────────────────────────────────────────────
def _eml_attachments(path):
    """.eml — 이름이 있는 비-이미지 부분만(이미지는 인라인 그림, figures.py가 담당이라 제외)."""
    msg = email.message_from_bytes(Path(path).read_bytes(), policy=policy.default)
    out = []
    for part in msg.walk():
        if part.is_multipart() or part.get_content_maintype() == "image":
            continue
        name = part.get_filename()
        if not name:
            continue  # 본문(text/plain·text/html) — 첨부 아님
        out.append({"name": str(name), "bytes": part.get_payload(decode=True) or b"", "depth": 0})
    return out


def _msg_attachments(path):
    """.msg — extract_msg(서버에만 설치, 개발 PC에 없으면 빈 목록으로 조용히 건너뜀)."""
    try:
        import extract_msg
    except ImportError:
        return []
    m = extract_msg.openMsg(str(path))
    try:
        out = []
        for a in m.attachments:
            name = a.longFilename or a.shortFilename
            data = getattr(a, "data", None)
            if name and isinstance(data, bytes):
                out.append({"name": str(name), "bytes": data, "depth": 0})
        return out
    finally:
        m.close()


def _expand_zip(entry, cap):
    """zip 첨부를 cap단(기본 1)까지만 풀기 — 그 밑은 손 안 댐(opaque로 둠, 맞는 엔진 없으면 parse_attachment가 자연히 건너뜀)."""
    if Path(entry["name"]).suffix.lower() != ".zip" or entry["depth"] >= cap:
        return [entry]
    try:
        zf = zipfile.ZipFile(io.BytesIO(entry["bytes"]))
        infos = [zi for zi in zf.infolist() if not zi.is_dir()][: _max_n()]  # 읽기 전에 개수·풀린 크기 확인(독립 검토 10-04 — zip 폭탄)
        cap_b, total = _max_mb() * 1024 * 1024, 0
        inner = []
        for zi in infos:
            total += zi.file_size
            if zi.file_size > cap_b or total > cap_b:
                break  # 상한 넘으면 그 뒤는 안 풂(읽은 것까지만)
            inner.append({"name": f"{entry['name']}#{zi.filename}", "bytes": zf.read(zi), "depth": entry["depth"] + 1})
    except (zipfile.BadZipFile, OSError):
        return [entry]
    if not inner:
        return [entry]
    return [e for ie in inner for e in _expand_zip(ie, cap)]


def extract(doc_path):
    """doc_path(.eml·.msg) → 꺼낸 첨부 목록(개수 상한 적용 후 zip 전개) — 다른 형식·오류는 빈 목록."""
    ext = Path(doc_path).suffix.lower()
    try:
        atts = _eml_attachments(doc_path) if ext == ".eml" else _msg_attachments(doc_path) if ext == ".msg" else []
    except Exception:
        return []
    cap = _max_depth()
    out = []
    for e in atts[: _max_n()]:
        out += _expand_zip(e, cap)
    return out


# ── 첨부 1건 파싱(+ P0 캐시) ─────────────────────────────────────────────
def _stack_parse():
    return pc.stack().get("parse", {})  # 엔진 구성 파일(서버·PC 같음 — 사용자 11-01)


def parse_attachment(entry, store=None):
    """첨부 1건 → (텍스트, 캐시 적중?, 엔진) — stack.json이 그 형식에 지정한 엔진 순서로 시도해
    15자 이상 나온 첫 결과를 씀. P0 원본 층 키 = 첨부 sha256 + 엔진@버전(pipeline.shared.parse_run.raw_engine_path) —
    같은 첨부를 같은 엔진으로 다시 안 돎."""

    store = store or raw_root()
    ext = Path(entry["name"]).suffix.lower()
    content_sha = sha(entry["bytes"])
    stack = _stack_parse()
    # stack.json은 PDF를 .pdf_text/.pdf_image로 나눠 둠(run_all과 같은 키) — 글자층 엔진 먼저, 15자 못 넘으면 OCR 엔진
    engines = stack.get(".pdf_text", []) + stack.get(".pdf_image", []) if ext == ".pdf" else stack.get(ext, [])
    for eng in engines:
        ver = P0.engine_version(eng)
        dst = P0.raw_engine_path(store, eng, ver, content_sha)
        if dst.exists():
            try:
                return json.loads(dst.read_text(encoding="utf-8")).get("text") or "", True, eng
            except (OSError, ValueError):
                pass
        adir = attach_dir()  # 강제 종료돼도 남은 파일은 다음 실행이 같은 이름으로 덮음
        adir.mkdir(parents=True, exist_ok=True)  # 검토 MINOR 5) · 스트리밍 시작 청소가 안 건드림(재검토 6번)
        tmp = adir / f"attach-{content_sha[:12]}{ext}"
        out_json = tmp.with_suffix(tmp.suffix + ".json")
        try:
            tmp.write_bytes(entry["bytes"])
            # 별도 프로세스 + 시간 제한(독립 검토 10-04 — 같은 프로세스에서 멈추는 엔진이 represent 전체를 세우던 위험)
            from pipeline.extract.run_engines import _isolated

            _isolated(eng, tmp, out_json, "default", pc.cfg().extract.attach.timeout)  # S7c — 설정 객체
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


# ── represent.py가 부르는 진입점 ─────────────────────────────────────────
def mail_blocks(doc_path, base_text):
    """.eml·.msg만: 인용 스레드 단락 + 첨부별 `[첨부 <파일명>]` 절 → (덧붙일 블록 목록, 통계{n, parsed, cached, sources}).
    다른 형식·오류는 (빈 목록, 0 통계)."""
    stats = {"n": 0, "parsed": 0, "cached": 0, "sources": []}
    blocks = []
    ext = Path(doc_path).suffix.lower()
    if ext not in (".eml", ".msg"):
        return blocks, stats
    th = thread_paragraphs(base_text)
    if th:
        blocks.append(th)
    for entry in extract(doc_path):
        if len(entry["bytes"]) > _max_mb() * 1024 * 1024:
            continue  # 크기 상한 초과 — 건너뜀(통계 n에도 안 넣음, 시도 자체를 안 함)
        stats["n"] += 1
        text, cached, eng = parse_attachment(entry)
        if not text:
            continue
        stats["parsed"] += 1
        stats["cached"] += int(cached)
        stats["sources"].append(f"{Path(doc_path).name}#{entry['name']}")  # 원본 위치 = 메일#첨부명
        blocks.append(f"[첨부 {entry['name']}]\n{text}")
    return blocks, stats
