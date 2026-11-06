#!/usr/bin/env python3
"""파싱 전 준비 → output/prepared/ (모든 엔진이 같은 입력을 쓰게)

1. --only 목록(candidate_ready stage_batch의 only.txt — 중복 제외를 지난 이름)에 있는 파일만. DRM·암호·지원 안 함은 건너뜀
   기록(_records/skipped.jsonl·skipped.csv + 문서마다 extract.skip span 1행)만 남기고 처리하지 않는다.
2. 방향 보정(설정 `extract.prepare.rotate_pages` — 기본 꺼짐): 켜면 이미지·이미지 PDF의 쪽마다 0·90·180·270도로 돌려
   RapidOCR 점수(가로 글상자의 신뢰도 × 글자 수)를 **동시에**(스레드 4개, 스레드마다 RapidOCR 하나) 재고 가장 높은 방향으로 돌린다
   (같으면 0도, 모두 0이면 그대로). 끄면 회전을 위한 OCR을 전혀 하지 않고 그대로 놓는다.
   - 점수는 긴 변 --probe-px(기본 1280)로 줄인 이미지로 계산(속도). 저장은 원래 해상도(PDF는 --dpi, 기본 extract.page_render_dpi = 150).
   - 회전이 있었던 파일만 새로 쓰고, 나머지는 그대로 복사. 텍스트 레이어가 있는 PDF·오피스·txt는 복사만.
   - 이미지 PDF를 돌리면 쪽 이미지로 다시 만든 PDF가 된다(원래 텍스트 레이어 없음 전제).
3. 기록: output/prepared/rotation.csv (파일·쪽·선택 각도·네 방향 점수·`orig_sha256` = 회전 전 원본 파일 sha256 —
   `pipeline.shared.vlmcall`이 쪽 VLM P0 열쇠에 씀: 렌더 바이트 대신 이걸 써야 재준비해도 캐시가 안 깨짐)

작은 기울기(1~5도) 보정은 하지 않는다 — 필요하면 튜닝 항목.

사용: python -m pipeline.extract.filter_and_rotate [--only <이름 목록>] → python -m pipeline.transform.parse.parse_engines --src output/prepared
"""

import argparse
import csv
import io
import json
import os
import shutil
import struct
import threading
import time
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import (  # 폴더 재편 뒤 이 상수만 바뀌면 됨
    APP_ROOT,
    doc_dir,
    tmp_path_for,  # tmp+os.replace · place()가 하드링크한 dst를 그 자리에서 save()하면 원본 inode까지 덮어씀
)
from pipeline import config as pc
from pipeline.extract import archive, unpack
from pipeline.shared.ext_groups import IMG_EXTS, OOXML_EXTS
from pipeline.shared.srcsha import sha_of
from pipeline.transform.parse.engines import registry  # '처리 엔진 없는 확장자' 판정(engines_for)

_OCR: list = []

# DRM·암호 래핑 머리 바이트 판별. 내용은 열지 않음(이름·종류·머리만), 네트워크 없음, 제조사 서명은 공개 포맷 기준만.
ZIP_SIG = b"PK\x03\x04"  # 정상 OOXML(ZIP 컨테이너)
CFB_SIG = bytes.fromhex("d0cf11e0a1b11ae1")  # OLE 복합 파일 — 구형 .doc·암호 걸린 OOXML이 이 컨테이너에 담김
PDF_SIG = b"%PDF"
_ENCRYPTED_PACKAGE = "EncryptedPackage".encode("utf-16-le")  # MS-OFFCRYPTO — 비밀번호 보호 OOXML을 OLE 안에 담을 때 스트림 이름
DRM_MARKERS = (  # 머리 바이트에 섞여 있으면 그 제품 래핑으로 본다(일반 서명만 — 내용 추측 없음)
    (b"<## FASOO", "drm_fasoo"),  # Fasoo Enterprise DRM
    (b"MarkAny", "drm_markany"),  # MarkAny DRM
    (b"SCDSA", "drm_softcamp"),  # SoftCamp SCDSA 컨테이너
    (b"DocumentSecurity", "drm_unknown"),  # 제품 특정 안 되는 일반 DocumentSecurity/IRM 헤더
)

# 구형 OLE(복합 파일) 암호: OOXML(zip 컨테이너)과 다른 신호라 _drm_reason이 못 봄(.doc·.xls·.ppt는 OOXML_EXTS 밖).
OLE_EXT = {".doc", ".xls", ".ppt"}
# 풀지 않는 압축은 DRM·손상이 아니라 "파싱 대상이 아님"(사람이 다시 올리거나 풀어야 함). .zip·.tar·.tgz·.tar.gz는 푼다(pl-57 — pipeline.extract.archive).
ARCHIVE_EXT = {".7z", ".rar", ".bz2", ".xz"}


def _cfb_sectors(data):
    """CFB(복합 파일 바이너리) 최소 머리글 읽기 — FAT·디렉터리만 stdlib로(olefile 없을 때 대체).
    ponytail: 109개 직접 FAT 섹터(DIFAT 없이 다루는 범위 — 사양상 보통 문서 7MB까지)만, 미니스트림(작은 스트림)도 다루지
    않음 — 그 밖은 신호 없음(None)으로 포기(엔진이 각자 판정). olefile이 설치되면 이 함수 대신 그걸 쓴다."""
    if len(data) < 512 or data[:8] != CFB_SIG:
        return None
    try:
        sector_shift = struct.unpack_from("<H", data, 30)[0]
        mini_cutoff = struct.unpack_from("<I", data, 56)[0]
        first_dir_sec = struct.unpack_from("<I", data, 48)[0]
        num_fat = struct.unpack_from("<I", data, 44)[0]
        fat_ids = struct.unpack_from("<109I", data, 76)
    except struct.error:
        return None
    if not (0 <= num_fat <= 109):  # DIFAT 필요(섹터 많음) — 다루지 않음
        return None
    sector_size = 1 << sector_shift

    def off(secid):
        return 512 + secid * sector_size

    fat = []
    for secid in fat_ids[:num_fat]:
        o = off(secid)
        if o < 0 or o + sector_size > len(data):
            return None
        n = sector_size // 4
        fat.extend(struct.unpack_from(f"<{n}I", data, o))

    def chain(start, limit_bytes=None):
        secid, seen, buf = start, set(), b""
        while 0 <= secid < len(fat) and secid not in seen:
            seen.add(secid)
            o = off(secid)
            if o + sector_size > len(data):
                break
            buf += data[o : o + sector_size]
            if limit_bytes and len(buf) >= limit_bytes:
                break
            secid = fat[secid]
        return buf

    dir_bytes = chain(first_dir_sec)
    entries = []
    for i in range(0, len(dir_bytes) - 127, 128):
        ent = dir_bytes[i : i + 128]
        namelen = struct.unpack_from("<H", ent, 64)[0]
        if not (2 <= namelen <= 64):
            continue
        try:
            name = ent[: namelen - 2].decode("utf-16-le")
        except UnicodeDecodeError:
            continue
        entries.append({"name": name, "type": ent[66], "start": struct.unpack_from("<I", ent, 116)[0]})
    return {"entries": entries, "mini_cutoff": mini_cutoff, "chain": chain}


def _ole_stream_head(cfb, name, n=2048):
    """CFB 스트림 하나의 앞 n바이트(미니스트림 제외 — 위 _cfb_sectors ponytail)."""
    for e in cfb["entries"]:
        if e["type"] == 2 and e["name"] == name:
            return cfb["chain"](e["start"], n)[:n]
    return None


def _ole_head_reason(ext, head):
    """FIB fEncrypted(.doc)·BIFF FILEPASS(.xls) 신호 — 스트림 앞부분(head)만 봄."""
    if head is None:
        return None
    if ext == ".doc":
        return "encrypted_doc" if len(head) >= 12 and struct.unpack_from("<H", head, 10)[0] & 0x0100 else None
    if ext == ".xls":  # BIFF 레코드: recType(2) + recLen(2) + data — FILEPASS=0x2F
        pos = 0
        while pos + 4 <= len(head):
            rec_type, rec_len = struct.unpack_from("<HH", head, pos)
            if rec_type == 0x2F:
                return "encrypted_xls"
            if rec_len < 0:
                break
            pos += 4 + rec_len
        return None
    return None


def _ole_encrypted_reason(p):
    """.doc·.xls·.ppt 암호 — OOXML과 다른 신호: FIB fEncrypted 플래그(.doc)·BIFF FILEPASS 레코드(.xls)·
    EncryptedSummary 스토리지(.ppt — CryptoAPI RC4 암호화 때 추가되는 저장소, CryptSession10Container를 담음).
    olefile이 설치돼 있으면 그걸로(정확), 없으면 _cfb_sectors 최소 리더로. None = 의심 없음(엔진이 각자 판정)."""
    ext = p.suffix.lower()
    if ext not in OLE_EXT:
        return None
    try:
        data = p.read_bytes()
    except OSError:
        return None
    if not data.startswith(CFB_SIG):
        return None  # OLE 컨테이너가 아니면(다른 손상 등) 엔진이 각자 판정
    try:
        import olefile
    except ImportError:
        olefile = None
    if olefile is not None:
        try:
            ole = olefile.OleFileIO(io.BytesIO(data))
            names = {s[-1] for s in ole.listdir()}
            if ext == ".ppt" and "EncryptedSummary" in names:
                return "encrypted_ppt"
            if ext != ".ppt":  # .ppt는 위 저장소 이름만 보고, 없으면 아래 내장 판독기로 다시
                stream = "WordDocument" if ext == ".doc" else next((n for n in ("Workbook", "Book") if n in names), None)
                head = ole.openstream(stream).read(2048) if stream else None
                reason = _ole_head_reason(ext, head)
                if reason:
                    return reason
            # olefile이 '없음'이라도 아래 내장 판독기로 한 번 더(규격을 덜 지킨 CFB는 olefile이 짧은 스트림을 미니 스트림에서
            # 읽어 엉뚱한 바이트를 줌 — 이미지(olefile 있음)에서만 .xls 암호를 놓치던 것, OLE 파일만 추가 비용)
        except Exception:
            pass  # olefile이 못 읽는 CFB(작은·비표준 구성)는 아래 내장 판독기로 다시 — 그냥 None이면 이미지에서만 암호 .doc을 놓침
    cfb = _cfb_sectors(data)
    if not cfb:
        return None
    if ext == ".ppt":
        return "encrypted_ppt" if any(e["name"] == "EncryptedSummary" for e in cfb["entries"]) else None
    name = "WordDocument" if ext == ".doc" else next((n for n in ("Workbook", "Book") if any(e["name"] == n for e in cfb["entries"])), None)
    return _ole_head_reason(ext, _ole_stream_head(cfb, name) if name else None)


def _unsupported_reason(p):
    """압축(zip 등)·처리 엔진 없는 확장자 — 원본 손상·DRM이 아니라 파싱 대상이 아님(사람이 변환·재전달).
    엔진 유무는 registry.engines_for(ext)로(stack.json·엔진 FORMATS와 같은 기준, DRM 판별과 같은 자리에서 한 번만 판정)."""
    ext = p.suffix.lower()
    if ext in ARCHIVE_EXT:
        return "unsupported_archive"
    return None if registry.engines_for(ext) else "unsupported_format"


def _drm_reason(p):
    """OOXML·PDF 머리 바이트만으로 DRM·암호 래핑 의심 판정 — 내용은 안 읽음(머리만), None = 의심 없음(엔진이 각자 판정).
    OOXML인데 ZIP도 OLE도 아니거나, OLE인데 EncryptedPackage 스트림이 있으면(비밀번호 보호 OOXML) 걸러 낸다."""
    ext = p.suffix.lower()
    if ext not in OOXML_EXTS and ext != ".pdf":
        return None
    try:
        head = p.open("rb").read(4096)
    except OSError:
        return None
    for sig, reason in DRM_MARKERS:
        if sig in head:
            return reason
    if ext == ".pdf":
        return None if head.startswith(PDF_SIG) else "drm_unknown"
    if head.startswith(ZIP_SIG):
        return None
    if head.startswith(CFB_SIG):
        try:
            data = p.read_bytes()
        except OSError:
            return "drm_unknown"
        return "encrypted_ooxml" if _ENCRYPTED_PACKAGE in data else "drm_unknown"
    return "drm_unknown"  # ZIP도 OLE도 아님 — 래핑 의심(제품 특정 안 함)


_TLS = threading.local()  # 스레드마다 RapidOCR 하나(회전 판정 4방향 동시 계산 — 한 객체를 여러 스레드가 같이 쓰지 않게)
_POOL: list = []
ANGLES = (0, 90, 180, 270)


def _ocr_lines(arr):
    """글상자 [(box, text, conf)] — rapidocr 3.x 한국어 모델(rapidocr_ko 엔진과 같은 패키지·모델). 스레드마다 엔진 하나."""
    eng = getattr(_TLS, "ocr", None)
    if eng is None:
        from rapidocr import RapidOCR

        from pipeline.transform.parse.engines.rapidocr.parser import (
            ko_params,  # OC1 — 엔진과 같은 설정·스레드 상한(병렬 prepare도 코어 다툼 없게)
        )

        params = ko_params()
        n = params.get("EngineConfig.onnxruntime.intra_op_num_threads")
        if n:  # 4방향 동시 — 엔진 4개가 CPU 몫(n)을 나눠 씀(나누지 않으면 4 × n 스레드가 서로 다퉈 차례 계산보다 느림)
            params["EngineConfig.onnxruntime.intra_op_num_threads"] = max(1, n // len(ANGLES))
        eng = _TLS.ocr = RapidOCR(params=params)
    r = eng(arr, use_cls=False)
    return list(zip(r.boxes.tolist(), r.txts, r.scores)) if r.boxes is not None else []


def _pool():
    """4방향 동시 계산 스레드 풀(한 번 만들어 쪽마다 다시 씀 — 스레드의 RapidOCR도 그대로 남아 다시 씀)."""
    if not _POOL:
        from concurrent.futures import ThreadPoolExecutor

        _POOL.append(ThreadPoolExecutor(max_workers=len(ANGLES), thread_name_prefix="rotate"))
    return _POOL[0]


def score(im, probe):
    import numpy as np

    im = im.copy()
    im.thumbnail((probe, probe))
    # 방향 분류기 끔 + 가로로 긴 글상자만: 바른 방향이면 글줄이 가로. 끄지 않으면 뒤집힌 글도 읽어 점수 차가 사라짐(실측 327 vs 312)
    res = _ocr_lines(np.asarray(im.convert("RGB")))
    total = 0.0
    for box, text, conf in res or []:
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        if max(xs) - min(xs) > 1.5 * (max(ys) - min(ys)):
            total += float(conf) * len(text)
    return total


def best_angle(im, probe):
    """쪽 하나의 방향 — 0·90·180·270도로 돌린 이미지의 score()를 스레드 4개로 동시에 재고 가장 높은 각도(같으면 0도, 모두 0이면 0도).
    문턱·비율·기대 각도 같은 판단 규칙은 두지 않는다. 반환: (각도, {각도: 점수})."""
    ims = [im.rotate(a, expand=True) if a else im for a in ANGLES]  # 돌린 이미지는 이 스레드에서 만들어 넘김
    s = dict(zip(ANGLES, _pool().map(lambda x: score(x, probe), ims)))
    a = max(ANGLES, key=lambda k: (s[k], k == 0))
    return (a if s[a] > 0 else 0), s


_sha256 = sha_of  # 받기가 manifest에 남긴 값(같은 파일일 때) — 없으면 다시 구함


def _record_skip(p, reason, skipped, skipped_log):
    """건너뛴 문서 기록 — skipped.csv(이번 실행 전체, 호환)용 리스트에 더하고, skipped.jsonl(누적, 이어쓰기)에
    파일 sha256·시각과 함께 바로 씀 + extract.skip span 1행(runtrace.skip_event)."""
    from pipeline.shared.runtrace import skip_event

    skipped.append({"file": p.name, "reason": reason})
    skip_event(p.name, reason)
    print(f"{p.name}: {reason} — 기록하고 건너뜀", flush=True)
    try:
        sha = _sha256(p)
    except OSError:
        sha = None
    rec = {"file": p.name, "reason": reason, "sha256": sha, "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    skipped_log.parent.mkdir(parents=True, exist_ok=True)
    with skipped_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _locked(p, skipped, skipped_log):
    """열기 암호가 걸린 PDF면 skipped에 기록하고 True(권한 암호만 있는 PDF는 열리므로 False — 그대로 파싱)."""
    import pypdfium2 as pdfium

    try:
        pdfium.PdfDocument(str(p)).close()
        return False
    except pdfium.PdfiumError as e:
        if "password" not in str(e).lower():
            return False  # 다른 손상은 엔진들이 각자 판정(여기서 막지 않음)
        _record_skip(p, "encrypted_pdf", skipped, skipped_log)
        return True


def is_image_pdf(p):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(p))
    chars = sum(len(doc[i].get_textpage().get_text_range().strip()) for i in range(min(len(doc), 5)))
    return chars < 50 * min(len(doc), 5)


def place(p, dst):
    """회전이 필요 없는 파일을 out으로 — 하드링크(디스크를 두 배로 쓰지 않음), 안 되면(다른 파일 시스템) 복사."""
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(p, dst)
    except OSError:
        shutil.copy2(p, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--src", default=None, help="원본 문서 폴더(기본 DOC_DIR env — --help·import 때는 안 풀어야 하므로 여기서는 default=None)"
    )
    ap.add_argument("--out", default=str(APP_ROOT / "output" / "prepared"))
    ap.add_argument("--only", default="", help="이 목록(파일명 한 줄씩)에 있는 파일만 — 보통 stage_batch의 only.txt")
    ap.add_argument(
        "--dpi", type=int, default=pc.cfg().extract.ocr.dpi, help="PDF 쪽 렌더 해상도 — 기본 extract.page_render_dpi(쪽·그림 VLM과 같은 값)"
    )
    ap.add_argument("--probe-px", type=int, default=1280)
    ap.add_argument("--no-scan-rotate", action="store_true", help="이미지 PDF(스캔)는 방향 보정 안 함 — run_pipeline 스캔 문서 정책")
    a = ap.parse_args()
    from PIL import Image

    src, out = Path(a.src) if a.src else doc_dir(), Path(a.out)
    if out.resolve() == src.resolve():  # out은 만들어 내는 폴더(지우고 다시 씀) — 원본 폴더면 원본이 지워짐
        raise SystemExit("--out이 원본 폴더와 같음 — 다른 폴더를 지정")
    out.mkdir(parents=True, exist_ok=True)
    # 기록 파일은 하위 폴더 _records/에(parse_engines는 이 폴더의 맨 위 파일만 문서로 훑는다 — 기록이 "건너뜀 .csv"로 세지지 않게)
    records = out / "_records"
    records.mkdir(exist_ok=True)
    parts = out / "_parts"  # 꺼낸 안 문서(pl-63) — 하위 폴더라 파싱 대상(맨 위 파일)이 아님
    if (out / "skipped.jsonl").exists() and not (records / "skipped.jsonl").exists():  # 예전 자리의 누적 기록은 옮겨 이어 씀
        (out / "skipped.jsonl").replace(records / "skipped.jsonl")
    skipped_log = Path(pc.cfg().extract.skipped_log or (records / "skipped.jsonl"))  # S7c — 설정 객체
    only = {x.strip() for x in Path(a.only).read_text(encoding="utf-8").splitlines() if x.strip()} if a.only else None
    files = sorted(p for p in src.iterdir() if p.is_file() and p.name != ".gitkeep" and (only is None or p.name in only))
    old = {}
    if (out / "rotation.csv").exists():  # 이미 만든 파일은 건너뛰고 예전 회전 기록을 이어 씀
        with (out / "rotation.csv").open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                old.setdefault(r["file"], []).append(r)
    log, n_rot, n_skip, skipped = [], 0, 0, []
    rotate_on = bool(pc.cfg().extract.prepare.rotate)  # 사용자 11-02 — 회전 켬/끔 하나(기본 꺼짐)
    for p in files:
        ext = p.suffix.lower()
        dst = out / p.name
        if dst.exists() and dst.stat().st_mtime >= p.stat().st_mtime and p.name in old:  # 원본이 안 바뀜 → 다시 안 함(수집 서버 재실행)
            log += old[p.name]
            n_skip += 1
            continue
        drm = _drm_reason(p)  # DRM·암호 래핑 의심(머리 바이트만) — 엔진에 보내기 전에 먼저 거름
        if drm:
            _record_skip(p, drm, skipped, skipped_log)
            continue
        ole_enc = _ole_encrypted_reason(p)  # 구형 OLE(.doc·.xls·.ppt) 암호(FIB·BIFF FILEPASS·EncryptedSummary)
        if ole_enc:
            _record_skip(p, ole_enc, skipped, skipped_log)
            continue
        unsup = _unsupported_reason(p)  # 압축(zip 등)·처리 엔진 없는 확장자는 파싱 대상이 아님
        if unsup:
            _record_skip(p, unsup, skipped, skipped_log)
            continue
        bad = archive.check(p)  # 압축 원본 — 암호·깨짐·안전 상한(pl-57)
        if bad:
            _record_skip(p, bad, skipped, skipped_log)
            continue
        if ext in IMG_EXTS and rotate_on:
            osha = _sha256(p)  # 원본(회전 전) sha256 — post.vlm_page P0 열쇠가 렌더 바이트 대신 이걸 씀
            im = Image.open(p)
            ang, s = best_angle(im, a.probe_px)
            log.append({"file": p.name, "page": 1, "angle": ang, "orig_sha256": osha, **{f"s{k}": round(v) for k, v in s.items()}})
            if ang:
                tmp = tmp_path_for(
                    dst
                )  # dst가 이전 실행에서 원본과 하드링크됐을 수 있어 그 자리에 바로 save()하면 원본까지 덮어씀 → 임시 파일 + os.replace
                im.rotate(ang, expand=True).save(tmp, format=im.format)
                os.replace(tmp, dst)
                n_rot += 1
            else:
                place(p, dst)
        elif ext == ".pdf" and _locked(p, skipped, skipped_log):  # 열기 암호 PDF — 기록하고 건너뜀(한 파일 때문에 묶음 전체가 멈추지 않게)
            continue
        elif (
            ext == ".pdf" and rotate_on and not a.no_scan_rotate and is_image_pdf(p)
        ):  # 회전은 extract.prepare.rotate_pages(기본 꺼짐)일 때만 · 꺼지면 회전용 OCR 없이 그대로 놓음
            import pypdfium2 as pdfium

            osha = _sha256(p)
            pages, changed = [], False
            for i, pg in enumerate(pdfium.PdfDocument(str(p))):
                im = pg.render(scale=a.dpi / 72).to_pil().convert("RGB")
                ang, s = best_angle(im, a.probe_px)
                log.append({"file": p.name, "page": i + 1, "angle": ang, "orig_sha256": osha, **{f"s{k}": round(v) for k, v in s.items()}})
                pages.append(im.rotate(ang, expand=True) if ang else im)
                changed |= bool(ang)
            if changed:
                tmp = tmp_path_for(dst)  # 위와 같은 이유(이미지 PDF도 place()로 하드링크됐을 수 있음)
                pages[0].save(tmp, "PDF", resolution=a.dpi, save_all=True, append_images=pages[1:])
                os.replace(tmp, dst)
                n_rot += 1
            else:
                place(p, dst)
        else:
            place(p, dst)
        if not unpack.is_fresh(dst, parts):  # 문서 안 문서(압축·메일 첨부·오피스 개체)를 _parts/<이름>/에(pl-63)
            unpack.unpack(dst, parts)
        angles = ", ".join(f"{r['page']}쪽 {r['angle']}°" for r in log if r["file"] == p.name)
        print(f"{p.name}: {angles or '복사'}", flush=True)
    with (out / "rotation.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "page", "angle", "orig_sha256", "s0", "s90", "s180", "s270"])
        w.writeheader()
        w.writerows(log)
    with (records / "skipped.csv").open("w", encoding="utf-8-sig", newline="") as f:  # 건너뛴 문서와 이유(암호 등) — 사람 확인 목록
        w = csv.DictWriter(f, fieldnames=["file", "reason"])
        w.writeheader()
        w.writerows(skipped)
    gone = 0
    names = {p.name for p in files} - {s["file"] for s in skipped} | {
        "rotation.csv",
        ".gitkeep",
    }  # 원본에서 지워졌거나 중복으로 빠진 파일 → out에서도 뺌(기록은 _records/ 폴더라 대상 아님)
    for q in out.iterdir():  #   (뒤 단계 묶음이 따라감 — PostgreSQL은 안 지움)
        if (q.is_file() or q.is_symlink()) and q.name not in names:
            q.unlink()
            gone += 1
    for q in parts.iterdir() if parts.exists() else ():  # 준비 원본이 빠지면 꺼낸 안 문서도 함께
        if q.name not in names:
            shutil.rmtree(q)
    print(
        f"파일 {len(files)}개 → {out} · 회전 보정 {n_rot}개 · 그대로 둠(안 바뀜) {n_skip}개 · 선택에 없어 뺌 {gone}개 · 쪽별 기록 rotation.csv"
        + (f" · 암호 등으로 건너뜀 {len(skipped)}개(_records/skipped.csv)" if skipped else "")
    )
    if skipped:  # 사유별 건수(PHASE_REPORT엔 이 단계 정보가 없어 여기 요약)
        from collections import Counter

        reasons = Counter(s["reason"] for s in skipped)
        print("  건너뜀 사유별: " + " · ".join(f"{k} {v}" for k, v in reasons.most_common()), flush=True)


if __name__ == "__main__":
    utf8_stdout()
    main()
