"""표준 라이브러리 MHT/MHTML 읽기 (.mht · .mhtml — 웹페이지·메일을 HTML+이미지째 한 파일로 저장한 MIME 묶음)

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
text/html 부분 → 본문 텍스트 + 표(행·열), text/plain 부분 → 본문. 이미지 부분은 개수만 기록(`trace.images`) —
이미지 속 글자가 필요하면 `images_dir`로 풀어 OCR·VLM 엔진에 넣는다(tools/run_all.py 대상 아님).
메일을 MHT로 저장한 경우 머리글(From·To·Date·Subject)도 본문 앞에 넣어 메일 필드 추출(tools/extract_email.py)이 쓰게 한다.
"""
import email
import re
from email import policy
from html.parser import HTMLParser

from pipeline.extract.engines._common.contract import _html_rows, _with_tables


class _Text(HTMLParser):
    """HTML → 줄 단위 텍스트(블록 태그에서 줄바꿈, script·style 제외)."""
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article", "header", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append("\t")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_text(h):
    p = _Text()
    p.feed(h)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in "".join(p.out).splitlines()]
    return "\n".join(ln for ln in lines if ln)


_CHARSET_WIDEN = {"ks_c_5601-1987": "cp949", "euc-kr": "cp949", "euckr": "cp949", "euc_kr": "cp949"}


def decode_mail_text(data, charset=None):
    """메일 본문 바이트 → 문자열(SI42 — EML/MSG 한글 깨짐). `part.get_content()`(선언 charset 그대로, 못 읽으면 '�')
    대신 바이트(`get_payload(decode=True)`)에서 직접: [선언 charset(ks_c_5601-1987·euc-kr는 cp949로 넓힘) → cp949 → utf-8]
    순 엄격 디코드 — ks_c_5601-1987 선언이지만 실제론 CP949 확장 글자(똠·쀍 등)가 섞인 메일이 Python의 ks_c_5601-1987→euc_kr
    별칭 때문에 그 글자만 깨지는 것(cp949는 euc-kr의 상위집합)·charset 선언이 없거나(utf-8 선언인데 실제 EUC-KR 등) 틀린 경우를 cp949
    순서로 구제. 전부 strict 디코드가 실패하면 치환 문자('�') 수가 가장 적고 한글 비율이 가장 높은 후보를 고른다(점수).
    parse_mhtml·parse_msg·modules/parse/post/figures.py(.eml 본문) 공용 — 이 세 곳 외 메일 본문을 바이트에서 디코드하는 곳이
    새로 생기면 여기로. TODO(SI42② — 사용자 제안): 그래도 애매하면(치환 문자·한글 자모 조각 비율 높음) 후보 2~3개를 내부
    LLM이 고르는 안(문서당 1회) — NO_PAID_CALLS·모델 미설정이면 조용히 건너뛰어야 해 이번 라운드는 규칙만(rules-only)."""
    if not isinstance(data, bytes):
        return data or ""
    declared = (charset or "").strip().lower()
    order, tried, candidates = [_CHARSET_WIDEN.get(declared, declared) or None, "cp949", "utf-8"], set(), []
    for enc in order:
        if not enc or enc in tried:
            continue
        tried.add(enc)
        try:
            return data.decode(enc)                       # 엄격 디코드 성공 — 선언(넓힌 것) → cp949 → utf-8 순 첫 성공
        except (LookupError, UnicodeDecodeError):
            candidates.append(enc)
    best = None
    for enc in candidates or ["utf-8"]:
        txt = data.decode(enc, errors="replace")
        bad = txt.count("�")
        hangul = sum(1 for c in txt if "가" <= c <= "힣" or "㄰" <= c <= "ㆎ")
        score = (bad, -hangul)
        if best is None or score < best[0]:
            best = (score, txt)
    return best[1] if best else data.decode("utf-8", errors="replace")


def _part_text(part):
    """메일 한 파트(text/html·text/plain) → 문자열 — 원본 바이트 + 선언 charset으로 decode_mail_text, 바이트를 못 얻으면
    (드묾) get_content() 폴백."""
    raw = part.get_payload(decode=True)
    return decode_mail_text(raw, part.get_content_charset()) if raw is not None else part.get_content()


def parse_mhtml(path, images_dir=None):
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    head = [f"{k}: {msg[k]}" for k in ("From", "To", "Cc", "Date", "Subject") if msg[k]]
    texts, tables, images = [], [], 0
    for part in msg.walk():
        ctype = part.get_content_type()
        if part.is_multipart():
            continue
        if ctype == "text/html":
            h = _part_text(part)
            texts.append(html_text(h))
            tables += [t for t in _html_rows(h) if t]   # TB2 — _html_rows가 표 전체를 보고 직접 뽑음(바깥 regex 제거, 중첩 표도 보존)
        elif ctype == "text/plain":
            texts.append(_part_text(part))
        elif ctype.startswith("image/"):
            images += 1
            if images_dir:
                from pathlib import Path
                name = part.get_filename() or f"image_{images}.{ctype.split('/')[1]}"
                (Path(images_dir) / re.sub(r"[^\w.\-]", "_", name)).write_bytes(part.get_payload(decode=True))
    out = _with_tables("\n".join(head + texts), tables, "mhtml[stdlib]")
    out["trace"].update({"images": images, "parts": sum(1 for _ in msg.walk())})
    return out


def parse_html(path):
    """.html·.htm — meta charset(없으면 UTF-8 → CP949 순) 판별 후 본문·표. 표준 라이브러리만."""
    raw = open(path, "rb").read()
    m = re.search(rb"charset=[\"']?([\w-]+)", raw[:4096], re.I)
    for enc in ([m.group(1).decode()] if m else []) + ["utf-8", "cp949"]:
        try:
            h = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        h = raw.decode("utf-8", "replace")
    tables = [t for t in _html_rows(h) if t]   # TB2 — _html_rows가 표 전체를 보고 직접 뽑음(바깥 regex 제거, 중첩 표도 보존)
    return _with_tables(html_text(h), tables, "html[stdlib]")


def parse_msg(path):
    """Outlook .msg — extract_msg(GPL-3.0)로 머리글·본문(HTML 본문이 있으면 표까지). SI42 — htmlBody는 메일이 선언한
    charset을 extract_msg가 따로 안 주므로 본문 안 <meta charset=...>을 찾고(없으면 None), decode_mail_text가
    parse_mhtml과 같은 규칙(선언 → cp949 → utf-8)으로 디코드 — 예전 `.decode('utf-8','replace')` 한 줄은 EUC-KR 메일 전체가 깨짐."""
    import extract_msg
    m = extract_msg.openMsg(str(path))
    try:
        head = [f"{k}: {v}" for k, v in (("From", m.sender), ("To", m.to), ("Cc", m.cc), ("Date", m.date), ("Subject", m.subject)) if v]
        hb = m.htmlBody
        if isinstance(hb, bytes):
            cs = re.search(rb"charset=[\"']?([\w-]+)", hb[:4096], re.I)
            h = decode_mail_text(hb, cs.group(1).decode() if cs else None)
        else:
            h = hb or ""
        tables = [t for t in _html_rows(h) if t]   # TB2 — _html_rows가 표 전체를 보고 직접 뽑음(바깥 regex 제거, 중첩 표도 보존)
        body = html_text(h) if h else (m.body or "")
        att = [a.longFilename or a.shortFilename for a in m.attachments]
    finally:
        m.close()
    return _with_tables("\n".join(head + [body] + ([f"첨부: {', '.join(att)}"] if att else [])), tables, "msg[extract_msg]")


ENGINES = {"mhtml": parse_mhtml, "html_stdlib": parse_html, "msg_extract": parse_msg}
FORMATS = {"mhtml": ('.mht', '.mhtml', '.eml'), "html_stdlib": ('.html', '.htm'), "msg_extract": ('.msg',)}   # .eml = 같은 MIME
REQUIRES = {"modules": [], "tools": []}
PROFILED = set()
UNVERIFIED = set()
