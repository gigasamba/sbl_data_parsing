"""W3(E16 이식) — 서식 첨자(윗·아래첨자)를 ^·_로. 원본: eval_hard_parse.supsub_text.
docx w:vertAlign · xlsx rPr/vertAlign · pptx a:rPr@baseline · PDF는 글자 크기·기준선(작은 글자+위로 들림 = 위첨자).
AD37: supsub_text()는 문서 전체를 다시 옮긴 "표기본" 원천일 뿐 — 대표 본문에는 merge_supsub()이 첨자 있는 줄만 바꿔 넣는다
(문서 전체를 본문에 덧붙여 두 번 들어가던 버그 수정 — 청크·BM25·임베딩 중복 방지)."""

import html
import re
import zipfile
from pathlib import Path


def supsub_text(p):
    """문서 전체를 첨자 표기(^·_) 포함해 다시 옮긴 글자 — merge_supsub()의 원천(본문에 직접 쓰지 않음, AD37)."""
    p = Path(p)
    ext = p.suffix.lower()
    out = []
    if ext == ".pdf":
        import fitz

        for pg in fitz.open(p):
            for b in pg.get_text("dict")["blocks"]:
                for ln in b.get("lines", []):
                    sizes = [s["size"] for s in ln["spans"]]
                    base = max(sizes) if sizes else 0
                    line = ""
                    for s in ln["spans"]:
                        small = s["size"] < base * 0.8
                        sup = (s["flags"] & 1) or (small and s["origin"][1] < ln["spans"][0]["origin"][1] - 0.5)
                        line += ("^" if sup else "_" if small else "") + s["text"]
                    out.append(line)
        return "\n".join(out)
    if ext not in (".docx", ".xlsx", ".pptx"):
        return ""
    z = zipfile.ZipFile(p)
    names = {
        ".docx": ["word/document.xml"],
        ".xlsx": [n for n in z.namelist() if re.match(r"xl/(sharedStrings|worksheets/sheet\d+)\.xml$", n)],
        ".pptx": [n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)],
    }[ext]
    run_re = {".docx": r"<w:r[ >].*?</w:r>", ".xlsx": r"<r>.*?</r>", ".pptx": r"<a:r>.*?</a:r>"}[ext]
    para_re = {".docx": r"<w:p[ >].*?</w:p>", ".xlsx": r"<(?:si|is)>.*?</(?:si|is)>", ".pptx": r"<a:p>.*?</a:p>"}[ext]
    for n in names:
        x = z.read(n).decode("utf-8", "ignore")
        for para in re.findall(para_re, x, re.S):
            line = ""
            for r in re.findall(run_re, para, re.S):
                # 정규식 추출은 XML을 파싱하지 않으므로 글자 참조(&#45453;·&amp; 등)가 그대로 남음 — 여기서 한 번만 해제(AD24①)
                t = html.unescape("".join(re.findall(r"<(?:w:t|t|a:t)(?: [^>]*)?>([^<]*)</(?:w:t|t|a:t)>", r)))
                if re.search(r'vertAlign w:val="superscript"|vertAlign val="superscript"|baseline="[1-9]', r):
                    t = "^" + t
                elif re.search(r'vertAlign w:val="subscript"|vertAlign val="subscript"|baseline="-', r):
                    t = "_" + t
                line += t
            out.append(line)
    return "\n".join(out)


def merge_supsub(base, doc_path):
    """AD37 — 첨자 있는 **줄만** 대표 본문(base) 안에서 첨자 표기본 줄로 바꿔 넣는다(문서 전체를 덧붙이지 않음).
    후보 찾기는 parse_qa의 정규화(norm)·퍼지 매칭(_best) 재사용(order_diff 채점이 쓰는 것과 같은 기준·임계값 90) —
    단 실제 치환은 그 후보와 "첨자 표기만 다르다"(표기본 줄에서 ^·_를 뗀 것과 base 줄이 공백 무시로 같다)는 것을
    확정한 뒤에만 한다(독립 검토 MAJOR 1 — 퍼지 점수만 보고 바꾸면 숫자처럼 비슷한 다른 값까지 덮어씀, 예: '수량 1' → '수량 7').
    못 맞거나(후보 자체가 없음) 첨자 말고 다른 글자까지 다르면 base를 그대로 두고 못 맞춘 줄로만 센다(끝에 덧붙이지
    않음 — 덧붙이면 그 내용이 다시 중복으로 들어감, MAJOR 1).
    반환: (바꿔 넣은 본문, 첨자 표기본 전체 — rep["post"]에 따로 보관, 못 맞춘 줄 수)."""
    full = supsub_text(doc_path)
    if not full.strip():
        return base, full, 0
    from pipeline.transform.represent.parse_qa import _best, norm, norm_nows  # 지연 import — 무거운 모듈(채점과 기준 공유, AD37)

    # A9(10-13) — split("\n"): str.splitlines()는 쪽 나눔 문자(\f)도 줄 경계로 보고 지워, 첨자 후처리를 거친 모든 대표
    # 본문에서 쪽 경계가 사라졌다(청크 meta.page 빈칸 — 합본 PDF 31/114). \f는 제 줄에 남고 norm()이 비워 매칭에 안 걸림.
    base_lines = base.split("\n")
    cand = [norm(ln) for ln in base_lines]
    n_unmatched = 0
    for ml in full.splitlines():
        if not re.search(r"[\^_]", ml):  # 첨자 없는 줄은 base와 같은 내용 — 손대지 않음(최소 변경)
            continue
        plain = re.sub(r"[\^_]", "", ml)  # 첨자 마커만 뗀 글자(비교 기준 — 이게 base 줄과 같아야 치환)
        if not norm(plain):
            continue
        _, score, idx = _best(norm(plain), cand)  # 퍼지는 후보 찾기에만(줄 위치가 어긋나 있을 수 있어서)
        if idx is not None and score >= 90 and norm_nows(plain) == norm_nows(base_lines[idx]):
            ff = "\f" if base_lines[idx].startswith("\f") else ""  # 같은 줄 앞에 붙은 쪽 나눔은 살림
            base_lines[idx] = ff + ml  # 첨자 표기만 다름이 확인된 경우에만 치환
            cand[idx] = ""  # 이미 바꾼 자리는 다른 첨자 줄이 다시 매칭 안 되게
        else:
            n_unmatched += 1
    merged = "\n".join(base_lines)
    return merged, full, n_unmatched
