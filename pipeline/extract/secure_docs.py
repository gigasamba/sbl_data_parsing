#!/usr/bin/env python3
"""보안 문서 — 보호 종류 판별(scan) · 암호를 아는 문서 복호화 사본(decrypt) · 사본 삭제(purge)

보호 종류와 여는 방법:
  편집 잠금(시트·통합문서·문서 보호)   암호화 아님 → openpyxl·calamine·python-docx 등이 그대로 읽음(조치 불필요)
  Office 열기 암호(OOXML·97-2003)     암호화된 컨테이너 → openpyxl은 못 엶. 암호를 알면 msoffcrypto-tool로 복호화 → 일반 파싱
  PDF 소유자 암호(인쇄·복사 제한)       빈 사용자 암호로 열림 → pdfplumber·pypdf·pikepdf가 읽음(조치 불필요, decrypt로 제한 제거 사본도 가능)
  PDF 열기(사용자) 암호                암호를 알면 pikepdf로 복호화 → 일반 파싱
  PDF 비표준 보안 핸들러(DRM·인증서)  %PDF 머리지만 /Filter가 Standard가 아님(FileOpen·LiveCycle·Adobe.PubSec 등) → pdfplumber·pypdf·PyMuPDF 모두 실패.
                                     DRM 뷰어가 있는 PC에서 이미지로 떠서 OCR, 또는 DRM 반출 요청
  알 수 없는 형식(DRM 의심)            확장자와 파일 머리가 안 맞음(사내 DRM 래핑 등) → 파이썬 라이브러리로는 불가.
                                     DRM 클라이언트가 설치된 Windows에서 엔진 `office_com`(Office COM으로 열어 내용만 읽음, 저장 안 함),
                                     또는 DRM 관리자에게 복호화 반출 요청
**투명 복호화 DRM**(사내 PC의 DRM 클라이언트가 파일을 열 때 자동으로 풀어 줌): 그 PC에서는 python-docx·openpyxl·pdfplumber가
그대로 읽고 scan은 '보호 없음'으로 나온다(파이썬이 보는 바이트가 이미 평문). 같은 파일을 DRM 클라이언트 없는 서버로 옮기면 다시 'DRM 의심'.
→ 보안 문서 파싱은 DRM PC에서 하고, 파싱 결과(output/parse)는 평문 사본이므로 폐쇄망 밖으로 옮기지 않는다.
사용:
  python cli/secure_docs.py probe [--src …]                        → 실제 라이브러리로 열어 봄(openpyxl·xlrd·python-docx·python-pptx·pdfplumber) → output/secure/probe.csv
  python cli/secure_docs.py scan [--src output/prepared]               → 콘솔 표 + output/secure/scan.csv
  SECURE_DOC_PASSWORD=… python cli/secure_docs.py decrypt [--src …]  → output/secure/decrypted/(보호 없는 문서는 그대로 복사 — 이 폴더를 run_all --src로)
      여러 암호: SECURE_DOC_PASSWORDS_FILE=<한 줄에 하나> (차례로 시도). **암호는 인자·로그·결과 파일에 남기지 않는다.**
  python cli/secure_docs.py purge                                   → 복호화 사본 삭제(파싱이 끝나면)
복호화 사본은 output/(git 제외)에만 두고, 외부로 옮기지 않는다.
"""

import argparse
import csv
import re
import shutil
import zipfile
from pathlib import Path

from common.config import settings as C  # S7c — 설정 객체(공용 칸 DOC_DIR·비밀 꺼내기)
from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT
from pipeline import config as pc  # S7c — 설정 객체(pipeline 칸)
from pipeline.shared.exts import OOXML_EXTS

ROOT = APP_ROOT  # output/ 등 런타임 경로용(옛 dev/)
LEGACY = {".doc", ".xls", ".ppt"}
CFB = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
LOCK_PARTS = ("xl/workbook.xml", "word/settings.xml", "ppt/presentation.xml")
# 빈 <workbookProtection/>(openpyxl 기본 출력)은 잠금 아님 — 켜진 속성(="1"/"true")이나 암호 해시가 있을 때만
LOCK_RE = re.compile(
    rb'<(?:\w+:)?(?:workbookProtection|documentProtection|modifyVerifier|sheetProtection)\b[^>]*?(?:="(?:1|true)"|[Pp]assword|[Hh]ashValue)'
)


def classify(p):
    """→ (보호 종류, 여는 방법, 비고)"""
    ext, head = p.suffix.lower(), p.read_bytes()[:8]
    if ext in OOXML_EXTS | LEGACY:
        if head.startswith(b"PK"):
            try:
                with zipfile.ZipFile(p) as z:
                    names = set(z.namelist())
                    locked = any(LOCK_RE.search(z.read(n)) for n in names if n in LOCK_PARTS or n.startswith("xl/worksheets/"))
            except zipfile.BadZipFile:
                return "손상·알 수 없음", "원본 확인", "zip 머리지만 열리지 않음"
            return ("편집 잠금(읽기 가능)", "일반 파싱", "") if locked else ("보호 없음", "일반 파싱", "")
        if head == CFB:
            try:
                import msoffcrypto

                with p.open("rb") as f:
                    enc = msoffcrypto.OfficeFile(f).is_encrypted()
            except Exception as ex:
                if ext == ".xls":  # msoffcrypto가 못 읽는 xls(일부 생성기의 짧은 레코드) — xlrd가 암호 여부를 직접 알려 줌
                    try:
                        import xlrd

                        xlrd.open_workbook(p, on_demand=True).release_resources()
                        return "보호 없음", "일반 파싱", ""
                    except Exception as ex2:
                        if "encrypt" in str(ex2).lower():
                            return "Office 열기 암호", "decrypt(암호 필요)", "xlrd"
                return "알 수 없음(CFB)", "원본 확인", f"{type(ex).__name__}"
            if enc:
                return "Office 열기 암호", "decrypt(암호 필요)", "msoffcrypto-tool"
            return ("보호 없음", "일반 파싱", "") if ext in LEGACY else ("알 수 없음(CFB인데 OOXML 확장자)", "원본 확인", "")
        return "알 수 없는 형식(DRM 의심)", "office_com(DRM 클라이언트 PC) 또는 DRM 반출", "머리 " + head.hex()
    if ext == ".pdf":
        if not head.startswith(b"%PDF"):
            return "알 수 없는 형식(DRM 의심)", "DRM 반출 요청", "머리 " + head.hex()
        import pikepdf

        try:
            with pikepdf.open(p) as pdf:
                return (
                    ("PDF 소유자 암호(읽기 가능)", "일반 파싱(또는 decrypt로 제한 제거)", "")
                    if pdf.is_encrypted
                    else ("보호 없음", "일반 파싱", "")
                )
        except pikepdf.PasswordError:
            return "PDF 열기 암호", "decrypt(암호 필요)", "pikepdf"
        except Exception as ex:
            h = _pdf_handler(p)
            if h:
                return "PDF 비표준 보안 핸들러(DRM·인증서)", "DRM 뷰어 PC에서 이미지화 → OCR, 또는 DRM 반출", f"/Filter /{h}"
            return "손상·알 수 없음", "원본 확인", type(ex).__name__
    return "보호 없음(해당 없음)", "일반 파싱", ""


def _pdf_handler(p):
    """/Encrypt가 있는 PDF의 보안 핸들러 이름 — 스트림 필터(…Decode)·Standard가 아닌 /Filter 이름. 없으면 None."""
    raw = p.read_bytes()
    if b"/Encrypt" not in raw:
        return None
    names = {m.decode("latin-1") for m in re.findall(rb"/Filter\s*/([\w.#]+)", raw)}
    odd = sorted(n for n in names if not n.endswith("Decode") and n != "Standard")
    return odd[0] if odd else None


def _probe_one(p):
    """실제 파싱 라이브러리로 열어 글자 수를 센다 → (라이브러리, 글자 수 또는 '실패 …')."""
    ext = p.suffix.lower()
    lib = {
        ".xlsx": "openpyxl",
        ".xlsm": "openpyxl",
        ".xls": "xlrd",
        ".docx": "python-docx",
        ".docm": "python-docx",
        ".pptx": "python-pptx",
        ".pptm": "python-pptx",
        ".pdf": "pdfplumber",
    }.get(ext)
    if not lib:
        return "-", "대상 아님"
    try:
        if lib == "openpyxl":
            import openpyxl

            wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
            return lib, sum(len(str(c)) for ws in wb.worksheets for r in ws.iter_rows(values_only=True) for c in r if c is not None)
        if lib == "xlrd":
            import xlrd

            b = xlrd.open_workbook(p)
            return lib, sum(len(str(c.value)) for sh in b.sheets() for r in range(sh.nrows) for c in sh.row(r) if c.value not in ("", None))
        if lib == "python-docx":
            import docx

            d = docx.Document(p)
            return lib, sum(len(x.text) for x in d.paragraphs) + sum(len(c.text) for t in d.tables for r in t.rows for c in r.cells)
        if lib == "python-pptx":
            import pptx

            return lib, sum(len(sh.text_frame.text) for s in pptx.Presentation(p).slides for sh in s.shapes if sh.has_text_frame)
        import pdfplumber

        with pdfplumber.open(p) as pdf:
            return lib, sum(len(pg.extract_text() or "") for pg in pdf.pages)
    except Exception as ex:
        return lib, f"실패 {type(ex).__name__}"


def probe(src, out):
    """판별(classify)과 실제 열기 결과를 나란히 — 투명 복호화 DRM PC에서는 판별 '보호 없음' + 읽힘으로 나온다."""
    rows = []
    for p in _docs(src):
        lib, r = _probe_one(p)
        rows.append(
            {
                "file": p.name,
                "kind": classify(p)[0],
                "lib": lib,
                "result": (f"읽힘 {r}자" if r else "열림·글자 0(이미지 문서면 OCR)") if isinstance(r, int) else r,
            }
        )
    out.mkdir(parents=True, exist_ok=True)
    with (out / "probe.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "kind", "lib", "result"])
        w.writeheader()
        w.writerows(rows)
    print("| 문서 | 판별 | 라이브러리 | 결과 |\n|---|---|---|---|")
    for r in rows:
        print(f"| {r['file']} | {r['kind']} | {r['lib']} | {r['result']} |")
    return rows


def _docs(src):
    return sorted(p for p in Path(src).iterdir() if p.is_file() and p.name not in (".gitkeep", "rotation.csv"))


def scan(src, out):
    rows = [dict(zip(("file", "kind", "how", "note"), (p.name, *classify(p)))) for p in _docs(src)]
    out.mkdir(parents=True, exist_ok=True)
    with (out / "scan.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "kind", "how", "note"])
        w.writeheader()
        w.writerows(rows)
    from collections import Counter

    c = Counter(r["kind"] for r in rows)
    print("| 보호 종류 | 문서 | 여는 방법 |\n|---|---|---|")
    for k, n in c.most_common():
        print(f"| {k} | {n} | {next(r['how'] for r in rows if r['kind'] == k)} |")
    for r in rows:
        if r["kind"] not in ("보호 없음", "보호 없음(해당 없음)"):
            print(f"  - {r['file']}: {r['kind']} → {r['how']}" + (f" ({r['note']})" if r["note"] else ""))
    return rows, c


def _passwords():
    one = pc.given("SECURE_DOC_PASSWORD")  # S7c — 설정 객체(비밀 칸 — 준 값이 있을 때만, 옛 `if get(X)`)
    pw = [C.reveal(one)] if one is not None else []
    f = pc.cfg().connections.secure_doc.passwords_file
    if f and Path(f).exists():
        pw += [x.rstrip("\r\n") for x in Path(f).read_text(encoding="utf-8").splitlines() if x.strip()]
    return pw


def decrypt_one(p, dst, passwords, kind):
    """성공하면 사용한 암호의 순번(1부터 — 암호 자체는 반환·기록 안 함), 실패면 None."""
    for i, pw in enumerate(passwords, 1):
        try:
            if kind == "Office 열기 암호":
                import msoffcrypto

                with p.open("rb") as f, dst.open("wb") as o:
                    of = msoffcrypto.OfficeFile(f)
                    of.load_key(password=pw)
                    of.decrypt(o)
            else:
                import pikepdf

                with pikepdf.open(p, password=pw) as pdf:
                    pdf.save(dst)  # 암호화 없이 저장
            return i
        except Exception:
            dst.unlink(missing_ok=True)
    return None


def decrypt(src, out):
    rows, _ = scan(src, out)
    dd = out / "decrypted"
    dd.mkdir(parents=True, exist_ok=True)
    passwords = _passwords()
    res = []
    for r in rows:
        p, dst = Path(src) / r["file"], dd / r["file"]
        if r["kind"] in ("Office 열기 암호", "PDF 열기 암호", "PDF 소유자 암호(읽기 가능)"):
            k = decrypt_one(p, dst, passwords + ([""] if r["kind"].startswith("PDF 소유자") else []), r["kind"])
            res.append(
                (r["file"], r["kind"], f"복호화(암호 {k}번째)" if k else ("실패 — 암호 없음" if not passwords else "실패 — 맞는 암호 없음"))
            )
        elif r["kind"].startswith(("알 수 없는", "손상")):
            res.append((r["file"], r["kind"], "건너뜀 — " + r["how"]))
        else:
            shutil.copy2(p, dst)
            res.append((r["file"], r["kind"], "그대로 복사"))
    with (out / "decrypt.csv").open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows([("file", "kind", "result")] + res)
    ok = sum(x[2].startswith("복호화") for x in res)
    need = sum(x[1] in ("Office 열기 암호", "PDF 열기 암호") for x in res)
    print(f"\n복호화 {ok}건 · 열기 암호 문서 {need}건 · 결과 {out / 'decrypt.csv'} · 파싱 입력: {dd}")
    for x in res:
        if not x[2].startswith(("그대로", "복호화")):
            print(f"  - {x[0]}: {x[2]}")
    return res


def purge(out):
    dd = out / "decrypted"
    if dd.exists():
        shutil.rmtree(dd)
    print(f"복호화 사본 삭제: {dd}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "probe", "decrypt", "purge"])
    ap.add_argument("--src", default=C.cfg().paths.doc_dir or str(ROOT / "output" / "prepared"))
    ap.add_argument("--out", default=str(ROOT / "output" / "secure"))
    a = ap.parse_args()
    out = Path(a.out)
    if a.cmd == "scan":
        scan(a.src, out)
    elif a.cmd == "probe":
        probe(a.src, out)
    elif a.cmd == "decrypt":
        decrypt(a.src, out)
    else:
        purge(out)


if __name__ == "__main__":
    utf8_stdout()
    main()
