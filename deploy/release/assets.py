#!/usr/bin/env python3
"""폐쇄망 반입 자산(모델·언어 팩·글꼴·휠)을 git에 담아 옮기고 서버에서 제자리에 설치한다 — 인터넷 없이.

담는 것(서버에서 받을 수 없는 것):
  wheels/en_core_web_sm-3.8.0-…whl      spaCy 영어 모델 — unstructured 토큰화(unstructured/nlp/tokenize.py)
  tessdata/{kor,eng,osd}.traineddata    Tesseract 한국어·영어(tessdata_best)·방향 — tesseract(지금 이 자산을 쓰는 엔진 없음) (TESSDATA_PREFIX)
  fonts/GoNotoCurrent-Regular.ttf       marker 렌더링 글꼴(marker settings.FONT_PATH — 없으면 첫 실행 때 인터넷에서 받으려다 실패)
  rapidocr/*.onnx                       RapidOCR 한국어 PP-OCRv5 인식 + 검출·방향 — rapidocr_ko(최종 추천 엔진, 패키지 폴더 안)
  (PostgreSQL 16 + pgvector Docker 이미지는 여기 없음 — 별도 브랜치 dev_server_pgvector를 ZIP으로 받아 docker load)
  wheels/psycopg*·typing_extensions·tzdata  PostgreSQL 드라이버(psycopg 3, Linux x86_64 · Python 3.12)
용량 때문에 뺀 것: docling 모델(약 530 MB) · EasyOCR 모델(99 MB) · RapidOCR 중국어 인식(21 MB, 기본 rapidocr 엔진용) — 모두 최종 추천 10개 밖 — docling·docling_ocr 모델은 이 도구에 없음. GitHub 파일 한도(100 MB) 때문에 90 MB 넘는 파일은 .partNN으로 나눠 담고 설치할 때 합친다(sha256 확인). 목록·해시 = assets/MANIFEST.json.

사용:
  (개발 PC) PYTHONPATH=. python deploy/release/assets.py pack           → assets/ 채움(아래 SOURCES 경로에서) + MANIFEST.json
  (서버)    python /app/docker/assets.py install [--python <venv python>]  → 합치기·해시 확인·제자리 복사·휠 설치, .env에 넣을 줄 출력
            PYTHONPATH=. python deploy/release/assets.py check → 설치 상태만 표로
paddle·mineru·임베딩(bge-m3 등)은 크기·venv가 달라 여기 없음. 준비 가이드: docs/operations/release-and-patch.md §5-6.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT  # assets/는 패키지 밖 저장소 루트

ROOT = APP_ROOT
A = ROOT / "assets"
PART = 90 * 1024 * 1024
HOME = Path.home()
HF = Path(os.environ.get("HF_HOME") or HOME / ".cache" / "huggingface") / "hub"  # env 남김 — 라이브러리


def _py_path(python, code):
    r = subprocess.run([python, "-c", code], capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


# 개발 PC 원본 위치(pack) — 서버에선 안 씀
def sources():
    scratch = Path(os.environ.get("ASSET_SRC") or ROOT)  # env 남김 — 호스트 도구
    rapid = _py_path(sys.executable, "import rapidocr,os;print(os.path.join(os.path.dirname(rapidocr.__file__),'models'))")
    out = {
        "wheels/en_core_web_sm-3.8.0-py3-none-any.whl": scratch / "dl" / "en_core_web_sm-3.8.0-py3-none-any.whl",
        "fonts/GoNotoCurrent-Regular.ttf": scratch / "dl" / "GoNotoCurrent-Regular.ttf",
    }
    for n in ("kor", "eng", "osd"):
        out[f"tessdata/{n}.traineddata"] = (
            scratch / "tessdata_best" / f"{n}.traineddata"
        )  # tessdata_best(LSTM 정확도 우선) — fast판은 한국어 11/56(실측)
    if rapid:  # rapidocr_ko에 필요한 것만(한국어 인식·검출·방향) — 중국어 인식은 뺌
        for f in rapid.glob("*.onnx"):
            if f.name != "PP-OCRv6_rec_small.onnx":
                out[f"rapidocr/{f.name}"] = f
    for f in sorted((scratch / "dl" / "wheels_pg").glob("*.whl")):  # psycopg 드라이버
        out[f"wheels/{f.name}"] = f
    # docling 모델(HF 캐시, 약 530 MB)은 용량 때문에 제외
    return out


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def pack():
    man = {}
    for rel, src in sorted(sources().items()):
        src = Path(os.path.realpath(src))
        if not src.exists():
            print(f"  없음(건너뜀): {rel} ← {src}")
            continue
        dst = A / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        size = src.stat().st_size
        parts = []
        if size > PART:
            with open(src, "rb") as f:
                i = 0
                while chunk := f.read(PART):
                    pp = dst.with_name(f"{dst.name}.part{i:02d}")
                    pp.write_bytes(chunk)
                    parts.append(pp.name)
                    i += 1
        else:
            shutil.copy2(src, dst)
        man[rel] = {"sha256": sha(src), "size": size, "parts": parts}
        print(f"  {rel}  {size / 1e6:.1f} MB" + (f"  ({len(parts)}조각)" if parts else ""))
    (A / "MANIFEST.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"합계 {sum(v['size'] for v in man.values()) / 1e6:.0f} MB · {len(man)}개 → {A}")


def assemble(rel, meta, dst):
    """assets 안의 파일(또는 조각)을 dst로 — 해시 확인."""
    src = A / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if meta["parts"]:
        with open(dst, "wb") as o:
            for n in meta["parts"]:
                o.write((src.parent / n).read_bytes())
    else:
        shutil.copy2(src, dst)
    if sha(dst) != meta["sha256"]:
        dst.unlink()
        raise SystemExit(f"해시 불일치: {rel} — 조각이 빠졌거나 손상(git pull 다시)")


def targets(python):
    """자산 종류 → 설치 위치. 패키지 폴더는 그 venv의 python으로 찾는다(없으면 None = 그 엔진 미설치)."""
    rapid = _py_path(python, "import rapidocr,os;print(os.path.join(os.path.dirname(rapidocr.__file__),'models'))")
    font = _py_path(python, "from marker.settings import settings;print(settings.FONT_PATH)")
    return {
        "tessdata": A / "tessdata",  # 제자리(TESSDATA_PREFIX로 가리킴)
        "rapidocr": rapid,
        "hf": HF,
        "font": font,
    }  # easyocr 타깃 없음(EasyOCR 모델은 스택 밖 — sources()도 안 담음)


def install(python):
    man = json.loads((A / "MANIFEST.json").read_text(encoding="utf-8"))
    t = targets(python)
    done, skip = [], []
    for rel, meta in man.items():
        kind, _, rest = rel.partition("/")
        if kind == "wheels":
            r = subprocess.run([python, "-m", "pip", "install", "--no-index", "--no-deps", str(A / rel)], capture_output=True, text=True)
            (done if r.returncode == 0 else skip).append(f"{rel} (pip {'ok' if r.returncode == 0 else r.stderr.strip()[-120:]})")
            continue
        if kind == "hf":  # tar → HF 캐시에 풀기(이미 풀려 있으면 건너뜀)
            import tarfile

            tmp = A / "hf" / "_restore.tar"
            assemble(rel, meta, tmp)
            with tarfile.open(tmp) as tf:
                names = [m for m in tf.getmembers() if m.isfile()]
                if all((HF / m.name).exists() and (HF / m.name).stat().st_size == m.size for m in names):
                    done.append(f"{rel} (이미 있음)")
                else:
                    tf.extractall(HF, members=names, filter="data")  # 경로 탈출·링크 차단
                    done.append(f"{rel} → {HF} ({len(names)}개)")
            tmp.unlink()
            continue
        if kind == "docker":  # 이미지 tar.gz 복원만 — 띄우는 건 사람(docker load → compose up)
            dst = A / rel
            if not (dst.exists() and dst.stat().st_size == meta["size"]):
                assemble(rel, meta, dst)
            done.append(f"{rel} → {dst}  (다음: docker load -i {dst})")
            continue
        if kind == "fonts":
            dst = t["font"]
        elif kind == "tessdata":
            continue  # 그대로 씀
        else:
            base = t.get(kind)
            dst = (base / rest) if base else None
        if dst is None:
            skip.append(f"{rel} (이 venv에 패키지 없음 — --python으로 그 엔진의 venv 지정)")
            continue
        if dst.exists() and dst.stat().st_size == meta["size"]:
            done.append(f"{rel} (이미 있음)")
            continue
        assemble(rel, meta, dst)
        done.append(f"{rel} → {dst}")
    print("설치:\n  " + "\n  ".join(done))
    if skip:
        print("건너뜀:\n  " + "\n  ".join(skip))
    print(f"\n.env에 추가: TESSDATA_PREFIX={A / 'tessdata'}\n            HF_HUB_OFFLINE=1  (docling이 인터넷 대신 캐시를 읽게)")


def check(python):
    man = json.loads((A / "MANIFEST.json").read_text(encoding="utf-8"))
    t = targets(python)
    print("| 자산 | 위치 | 상태 |\n|---|---|---|")
    for rel, meta in man.items():
        kind, _, rest = rel.partition("/")
        if kind == "wheels":
            ok = _py_path(python, "import en_core_web_sm;print(en_core_web_sm.__file__)") is not None
            print(f"| {rel} | {python} | {'✓' if ok else '✗ install 필요'} |")
            continue
        if kind == "docker":
            ok = (A / rel).exists() and (A / rel).stat().st_size == meta["size"]
            print(f"| {rel} | {A / rel} | {'✓ 복원됨' if ok else '✗ install 필요'} |")
            continue
        if kind == "hf":
            ok = all(
                (HF / r).exists()
                for r in ("models--docling-project--docling-models/refs/v2.3.0", "models--docling-project--docling-layout-heron/refs/main")
            )
            print(f"| {rel} | {HF} | {'✓' if ok else '✗ install 필요'} |")
            continue
        dst = {"fonts": t["font"], "tessdata": A / rel}.get(kind) or ((t.get(kind) / rest) if t.get(kind) else None)
        ok = bool(dst) and dst.exists() and dst.stat().st_size == meta["size"]
        print(f"| {rel} | {dst or '패키지 없음'} | {'✓' if ok else '✗'} |")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pack", "install", "check"])
    ap.add_argument("--python", default=sys.executable, help="휠·패키지 폴더(rapidocr·marker)를 찾을 venv의 python")
    a = ap.parse_args()
    utf8_stdout()
    {"pack": pack, "install": lambda: install(a.python), "check": lambda: check(a.python)}[a.cmd]()
