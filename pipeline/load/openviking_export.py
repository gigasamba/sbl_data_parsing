#!/usr/bin/env python3
"""OpenViking 서버 → 문서 폴더 내려받기 (REST, SDK 불필요) → output/ov_export/<문서명>/{본문.md, .abstract.md, .overview.md, 이미지}

OpenViking 저장소 폴더를 직접 복사할 수 있으면 이 도구 없이 OV_DOC_ROOT를 그 폴더로 지정하면 된다.
사용: python cli/ov_export.py --url http://127.0.0.1:1933 --root viking://resources/<루트> [--only 문서명,…]
이후: OV_DOC_ROOT=output/ov_export가 구조화 단계(modules/structure/build_bundle.py ov_summaries)의 요약 출처로 쓰인다.
OV_URL·OV_ROOT를 설정해 두면 `cli/pipeline.py`의 `ov_import`가 OV_DOC_ROOT에 없는 문서를 이 함수로 받아 온다(run-stack 안에서 자동 호출).
"""

import argparse
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT
from pipeline.load.openviking_api import call, list_docs  # OV1(load/ov_ingest.py)도 같은 함수를 씀(common/ov.py로 공용화)

ROOT = APP_ROOT  # output/ 등 런타임 경로용(옛 dev/)
IMG = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def export(base, root, out, only=None, images=False, log=print):
    """only: 문서 폴더 이름 판정 함수(None이면 전부). 반환: 받은 문서 이름 목록."""
    base, out, got = base.rstrip("/"), Path(out), []
    for name, uri in list_docs(base, root).items():
        if only and not only(name):
            continue
        files = [
            x for x in call(base, "/api/v1/fs/ls", uri=uri, recursive="true", show_all_hidden="true", node_limit=5000) if not x["isDir"]
        ]
        n_md = n_img = 0
        for f in files:
            rel = f["uri"][len(uri.rstrip("/")) + 1 :]
            dst = out / name / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            ext = Path(rel).suffix.lower()
            if ext == ".md":
                dst.write_text(call(base, "/api/v1/content/read", uri=f["uri"]), encoding="utf-8")
                n_md += 1
            elif ext in IMG and images:
                dst.write_bytes(call(base, "/api/v1/content/download", uri=f["uri"]))
                n_img += 1
        log(f"{name}: md {n_md} · 이미지 {n_img} / 파일 {len(files)}")
        got.append(name)
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:1933")
    ap.add_argument("--root", required=True, help="문서 폴더들의 상위 URI, 예: viking://resources/sfdc")
    ap.add_argument("--out", default=str(ROOT / "output" / "ov_export"))
    ap.add_argument("--only", default="", help="문서 폴더 이름(쉼표) — 비우면 전부")
    ap.add_argument("--images", action="store_true", help="이미지도 내려받기(검토 화면용)")
    a = ap.parse_args()
    want = {x for x in a.only.split(",") if x}
    got = export(a.url, a.root, a.out, (lambda n: n in want) if want else None, a.images)
    print(f"문서 {len(got)}개 → {a.out}")


if __name__ == "__main__":
    utf8_stdout()
    from common.core.runlog import session

    with session("ov_export"):
        main()
