#!/usr/bin/env python3
"""파싱 에이전트 도구 층(AG11 1단계) — dev/docs/common/parse-agent-design.md 'AG11 구현 계획' 절의 도구 표를 그대로 코드로.
지금 파싱 함수(pipeline.extract.prepare·pipeline.extract.engines.registry·pipeline.transform.figures.figures·pipeline.transform.figures.vlm_page·
pipeline.transform.represent.represent·common.core.repfmt)를 **감싸기만** 한다 — 실제 작업은 전부 그 함수들이 한다, 여기는 입력을 작은
값(문서·쪽·그림 id)으로 받고 출력을 요약 dict로 줄이는 얇은 층(설계 §3 "원문 전체가 아니라 요약·신호·참조만").

build_tools(doc, doc_path, out_dir) → (tools, ctx) — 문서 1건짜리 세션.
  tools: {이름: 함수} — dev/common/adk.py.run_agent(tools=...)에 그대로 넘긴다. 키 이름 = dev/agents/parse_agent/
    agent.json의 local_tools와 정확히 같아야 하고(run_agent이 집행), 각 함수의 __name__도 같아야 한다(ADK가
    등록할 때 __name__을 보기 때문 — dev/common/adk.py run_agent()의 주석). 아래는 전부 평범한 def라 자동으로 맞다.
  ctx: 이 세션의 파싱 맥락 기록(PA0, 설계 §3) — 호출자가 세션이 끝나면 ctx['context']·ctx['decisions']를
    rep.context·rep.decisions에 붙인다. 결과(최종 _rep)는 안 바꾼다 — 기록만.

쓰기 범위(행동 변화 0 — shadow 모드가 운영 산출물을 건드리지 않게):
  - extract_images·apply_post의 PNG·index.jsonl·capped.jsonl은 **out_dir/_images**에만(공유 output/parse/_images가
    아님) — 둘 다 pipeline.transform.figures.figures.build_records·write_index·pipeline.transform.represent.represent.apply_post의
    out_images= 인자로 직접 지정(AG11 2단계 착수 조건, 10-08: 전엔 PARSE_IMAGES_ROOT 환경변수를 호출 동안만
    바꿔(프로세스 잠금으로 직렬화) 격리했던 것 — 인자로 바뀌어 환경변수 교체·잠금이 더 필요 없다).
  - VLM 응답 캐시(raw_vlm_path·det_key, PARSE_RAW_ROOT)는 **의도적으로 공유** — 내용 주소형(문서 sha·쪽·모델·prompt_id)이라
    실제 파이프라인과 같은 캐시를 재사용해도 안전하고, 그게 설계의 목적(§4·§6 "캐시·det_key 유지").
  - parse_text도 같은 이유로 **공유** — pipeline.extract.run_all의 P0 캐시(runs.jsonl·<엔진>/<문서>.json, 코드·문서
    지문 열쇠)를 그대로 읽고 쓴다(10-07 사용자 결정 — 같은 문서를 다시 돌릴 때 엔진 재실행 0, run_all.py의
    RunLog로 배치 실행과 같은 파일 잠금을 쓰므로 동시에 돌아도 섞이지 않음).

경로 — 하드코딩 대신 운영 배치와 같은 env 관례(수집 서버 실행, 10-07 사용자 결정 ①): RAG_OUT(없으면 dev/out, modules/
search/research.py와 같은 관례) 아래 parse/가 run_all·represent가 쓰는 그 출력 폴더 — parse_text의 P0 캐시 읽기·쓰기가
이 폴더를 본다. DOC_DIR(없으면 legacy DOC_SRC, 10-14부터 하드코딩 기본값 없음 — common/paths.py.doc_dir)은 원본 문서
폴더 기본값 — 이 파일 자신은 안 쓰고(문서 경로는 호출자가 doc_path로 줌), CLI(dev/cli/parse_agent.py)가 같은 관례로 푼다.

사용: python tools/parse_agent_tools.py --selftest
"""

import json
import time
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT, doc_dir  # 폴더 재편 뒤 이 상수만 바뀌면 됨

ROOT = APP_ROOT
from common.config.settings import cfg  # noqa: E402 — common 칸 설정 객체(S7c)

TOOL_NAMES = (
    "inspect_document",
    "parse_text",
    "extract_images",
    "detect_rotation",
    "ocr_region",
    "vlm_read",
    "summarize_document",
    "cross_check",
    "choose_representative",
    "apply_post",
    "finalize",
)


def rag_out():
    """RAG_OUT(없으면 dev/out) — modules/search/research.py._enrich_queue_path와 같은 관례(하드코딩 금지, 10-07 결정)."""
    base = cfg().paths.output_root  # S7c — 설정 객체(common 칸, 글자 그대로 — 없음·''은 아래 `if base`로 같음)
    return Path(base) if base else ROOT / "output"


def doc_src():
    """DOC_DIR(없으면 legacy 별칭 DOC_SRC) — common/paths.py.doc_dir, prepare.py·run_all.py와 같은 관례."""
    return doc_dir()


def _cached_or_run(engine, doc, doc_path, parse_dir):
    """엔진 결과 — pipeline.extract.run_all의 P0 캐시(runs.jsonl·<엔진>/<문서>.json, 코드·문서 지문 열쇠)를 그대로
    재사용(같으면 재실행 0) · 없거나 낡으면 pipeline.extract.engines.registry.run으로 실제 파싱하고 run_all.run_job과 같은
    파일·같은 잠금(RunLog)으로 캐시에 써 둔다(다음 호출·run_all 배치 양쪽에서 재사용) → (결과 dict, cached?)."""
    from pipeline.extract import run_all as RA
    from pipeline.extract.engines import registry

    pd = Path(parse_dir)
    dst = pd / engine / f"{doc}.json"
    sha = RA._sha(Path(doc_path))
    last = {}
    runs_f = pd / "runs.jsonl"
    if runs_f.exists():
        for ln in runs_f.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                if r.get("doc") == doc and r.get("engine") == engine:
                    last = r  # append-only 파일 — 뒤에 나온 기록이 더 최신
    same = bool(last) and last.get("sha") in (None, sha)
    status = RA.p0_status(last, engine, sha)[0] if same else "unknown"
    if dst.exists() and same and not last.get("error") and status == "ok":
        return json.loads(dst.read_text(encoding="utf-8")), True
    result = registry.run(engine, doc_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    RA._write_atomic(dst, json.dumps(result, ensure_ascii=False))
    ver = RA.P0.engine_version(engine)
    pkey = RA.p0_key(engine, sha, ver)
    RA._stamp_provenance(dst, engine, ver, pkey, "default")
    rec = {
        "doc": doc,
        "engine": engine,
        "sec": 0,
        "error": None,
        "sha": sha,
        "p0_key": pkey,
        "p0_code": RA.engine_code_fp(engine),
        "engine_version": ver,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chars": len((result.get("text") or "").strip()),
        "by": "parse_agent",
    }
    RA.RunLog(runs_f).write(json.dumps(rec, ensure_ascii=False) + "\n")
    return json.loads(dst.read_text(encoding="utf-8")), False


def build_tools(doc, doc_path, out_dir, parse_dir=None):
    """문서 1건(doc=이름, doc_path=이미 준비된 파일 경로, out_dir=이 세션의 스크래치 폴더, parse_dir=run_all·represent가
    쓰는 P0 캐시 폴더 — 비우면 rag_out()/"parse") → (tools dict, ctx dict)."""
    doc_path = str(doc_path)
    parse_dir = str(parse_dir) if parse_dir else str(rag_out() / "parse")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    ctx = {
        "doc": doc,
        "doc_path": doc_path,
        "out_dir": str(out_dir),
        "parse_dir": parse_dir,
        "engine_results": {},
        "figures": None,
        "vlm": {},
        "summary": None,
        "rep_engine": None,
        "crosscheck": None,
        "post": None,
        "final": None,
        "context": {},
        "decisions": [],
    }

    def _log(action, reason, **extra):
        ctx["decisions"].append({"action": action, "reason": reason, **extra})

    def _best_text():
        texts = [r.get("text") or "" for r in ctx["engine_results"].values()]
        return max(texts, key=len) if texts else ""

    def inspect_document():
        """형식·쪽 수·DRM 의심·이미지 PDF 여부·파일 크기 + PDF면 쪽별 신호(AD46 '문서 검사' — pipeline.transform.figures.vlm_page.
        page_signals를 그대로 써서 중복 계산 안 함, D2 글자층·D4 이미지 섞임·D6 쪽 VLM이 같은 표를 읽게) —
        pipeline.extract.prepare·pipeline.extract.run_all·pipeline.transform.figures.vlm_page의 신호 함수 그대로."""
        from pipeline.extract import prepare as P
        from pipeline.extract.run_all import n_pages as _n_pages
        from pipeline.transform.figures.vlm_page import page_signals

        p = Path(ctx["doc_path"])
        sig = {"format": p.suffix.lower(), "exists": p.exists()}
        if p.exists():
            sig["size_bytes"] = p.stat().st_size
            sig["pages"] = _n_pages(p)
            sig["drm"] = P._drm_reason(p)
            sig["is_image_pdf"] = p.suffix.lower() == ".pdf" and P.is_image_pdf(p)
            if p.suffix.lower() == ".pdf":
                sig["page_signals"] = page_signals(p)  # 캐시됨(AD12) — D2·D4·D6이 같은 쪽을 다시 안 엶
        ctx["context"]["signals"] = sig
        _log("inspect_document", "문서 신호 조회")
        return sig

    def parse_text(engines: list[str]):
        """engines(이름 목록) 각각으로 문서를 파싱 → 엔진별 글자·표·사실 수 요약(+ cached — P0 재사용 여부).
        실제 파싱은 pipeline.extract.engines.registry.run 그대로(_cached_or_run이 run_all.py와 같은 캐시를 먼저 봄) — 본문은
        ctx(이 세션 메모리)에만 보관, 모델에게는 요약만 돌려준다."""
        out = {}
        for eng in engines:
            try:
                r, cached = _cached_or_run(eng, ctx["doc"], ctx["doc_path"], ctx["parse_dir"])
                ctx["engine_results"][eng] = r
                out[eng] = {
                    "ok": True,
                    "chars": len(r.get("text") or ""),
                    "tables": len(r.get("tables") or []),
                    "facts": len(r.get("facts") or []),
                    "cached": cached,
                }
            except Exception as ex:  # 엔진 미설치·미설정 등 — 그 엔진만 실패로 기록(나머지는 계속)
                out[eng] = {"ok": False, "error": f"{type(ex).__name__}: {str(ex)[:200]}"}
        _log("parse_text", f"엔진 {len(engines)}개 실행", engines=list(engines))
        return out

    def extract_images():
        """중간 삽입 그림·쪽 통째 이미지를 자르고 1차 VLM 요약(pipeline.transform.figures.figures.build_records·write_index 그대로)
        → 그림 목록 요약(크기·캡션·언급·sha, 바이트 제외). PNG·index.jsonl·capped.jsonl(상한 기록)은 out_dir/_images에만
        (공유 저장소 아님 — build_records·write_index 둘 다 out_images= 인자로 직접 받는다, AG11 2단계 착수 조건)."""
        from pipeline.transform.figures import figures as fig_mod

        doc_text = _best_text()
        doc_sha = fig_mod.sha(Path(ctx["doc_path"]).read_bytes())
        out_images = Path(out_dir) / "_images"
        records, _plain, _enriched = fig_mod.build_records(ctx["doc"], ctx["doc_path"], doc_text, doc_sha, out_images=out_images)
        rows = fig_mod.write_index(ctx["doc"], records, out_images=out_images)
        ctx["figures"] = rows
        summary = [
            {
                "image_id": r["image_id"],
                "page": r.get("page"),
                "kind": r.get("kind"),
                "caption": r.get("caption"),
                "has_vlm": bool((r.get("vlm") or {}).get("summary")),
                "skipped": r.get("skipped"),
                "png": r.get("png"),
            }
            for r in rows
        ]
        _log("extract_images", f"그림 {len(rows)}개")
        return {"count": len(rows), "figures": summary}

    def detect_rotation(page: int = 1, probe_px: int = 1280, min_gain: float = 1.3):
        """쪽(이미지·이미지 PDF) 방향 점수 — pipeline.extract.prepare.best_angle 그대로. PDF는 그 쪽만 렌더, 그 외는 파일 전체."""
        from PIL import Image

        from pipeline.extract import prepare as P

        p = Path(ctx["doc_path"])
        if p.suffix.lower() == ".pdf":
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(p))
            page = int(page)  # 모델이 "1"처럼 문자열로 보낼 때(OpenRouter 기능 시험 10-07)
            if page < 1 or page > len(pdf):
                return {"error": f"쪽 {page} 없음(전체 {len(pdf)}쪽)"}
            im = pdf[page - 1].render(scale=200 / 72).to_pil().convert("RGB")
        else:
            im = Image.open(p)
        angle, scores = P.best_angle(im, probe_px, min_gain)
        out = {"page": page, "angle": angle, "scores": {str(k): round(v) for k, v in scores.items()}}
        _log("detect_rotation", f"{page}쪽 {angle}도", page=page, angle=angle)
        return out

    def ocr_region(page: int = 1, bbox: list[float] | None = None):
        """영역(bbox=[x0,y0,x1,y1], 0~1 비율 — 없으면 쪽 전체) OCR — pipeline.extract.prepare._ocr_lines 그대로.
        반환은 글상자 요약(글줄 수·평균 신뢰도·앞 40자 미리보기)만 — 원문을 통째로 돌려주지 않는다(설계 §3 요약만)."""
        import numpy as np
        from PIL import Image

        from pipeline.extract import prepare as P

        p = Path(ctx["doc_path"])
        if p.suffix.lower() == ".pdf":
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(p))
            page = int(page)  # 모델이 "1"처럼 문자열로 보낼 때(OpenRouter 기능 시험 10-07)
            if page < 1 or page > len(pdf):
                return {"error": f"쪽 {page} 없음(전체 {len(pdf)}쪽)"}
            im = pdf[page - 1].render(scale=200 / 72).to_pil().convert("RGB")
        else:
            im = Image.open(p).convert("RGB")
        if bbox:
            w, h = im.size
            x0, y0, x1, y1 = (float(v) for v in bbox)
            im = im.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
        lines = P._ocr_lines(np.asarray(im))
        chars = sum(len(t) for _box, t, _c in lines)
        conf = sum(float(c) for _box, _t, c in lines) / len(lines) if lines else 0.0
        preview = " ".join(t for _box, t, _c in lines)[:40]
        out = {"page": page, "bbox": bbox, "lines": len(lines), "chars": chars, "avg_conf": round(conf, 3), "preview": preview}
        _log("ocr_region", f"{page}쪽 영역 OCR {len(lines)}줄")
        return out

    def vlm_read(target: str = "page", context: str = "none"):
        """쪽 전체 옮기기(target="page") 또는 그림 1장 설명(target="figure:<image_id>", extract_images 먼저 필요) —
        adk.complete(agent=...)를 캐시·det_key 그대로 쓰는 기존 함수(pipeline.transform.figures.vlm_page.page_text ·
        pipeline.transform.figures.figures.vlm_fig)로. context="none"만 1단계에 구현 — 다른 값(summary·agent)은 맥락을 섞어
        새 prompt_id로 보내는 2단계(VLM_CTX c1·c2, 설계 §4) 일이라 여기서는 명시적으로 NotImplementedError."""
        if context != "none":
            raise NotImplementedError(f"vlm_read context={context!r} — 2단계(VLM_CTX c1/c2)에서 구현")
        if target == "page":
            from pipeline.transform.figures import vlm_page as vp_mod

            text, provs = vp_mod.page_text(ctx["doc_path"])
            ctx["vlm"]["page"] = {"text": text, "provenance": provs}
            out = {
                "target": "page",
                "chars": len(text),
                "pages": len(provs),
                "cached": sum(1 for pv in provs if pv.get("cached")),
                "errors": [pv["error"] for pv in provs if pv.get("error")],
            }
        elif target.startswith("figure:"):
            image_id = target.split(":", 1)[1]
            rec = next((r for r in (ctx.get("figures") or []) if r["image_id"] == image_id), None)
            if rec is None:
                return {"error": f"extract_images 먼저 — {image_id} 없음"}
            if not rec.get("png"):
                return {"error": f"{image_id}: 그림 바이트 없음(건너뜀 — {rec.get('skipped')})"}
            from pipeline.transform.figures import figures as fig_mod

            img_bytes = (Path(out_dir) / rec["png"]).read_bytes()
            text, prov = fig_mod.vlm_fig(img_bytes)
            parsed = fig_mod.parse_json(text) if text else {}
            ctx["vlm"][image_id] = {"text": text, "provenance": prov}
            out = {
                "target": target,
                "ok": bool(text),
                "kind": parsed.get("kind"),
                "cached": bool(prov.get("cached")),
                "error": prov.get("error"),
            }
        else:
            return {"error": f"알 수 없는 target: {target!r}"}
        _log("vlm_read", f"{target} 판독", context=context)
        return out

    def summarize_document(model: str = "llm"):
        """문서 요약 — dev/agents/doc_summary, adk.complete(agent="doc_summary")(1단계는 llm만). VLM 요약은
        문서 단위로 아직 없는 기능이라 model="vlm"은 NotImplementedError(YAGNI — 없는 것을 있는 척하지 않음)."""
        if model != "vlm":
            pass
        else:
            raise NotImplementedError("summarize_document model='vlm' — 아직 없음(문서 단위 VLM 요약 미구현)")
        from common.ai import adk as A

        text = _best_text()
        if not text.strip():
            return {"summary": "", "error": "본문 없음"}
        try:
            summary, _usage = A.complete("llm", [{"role": "user", "content": text[:8000]}], agent="doc_summary", max_tokens=300)
        except A.ModelUnavailable as ex:
            return {"summary": "", "error": str(ex)[:200]}
        ctx["summary"] = summary
        _log("summarize_document", "LLM 요약")
        return {"summary": summary, "chars": len(summary)}

    def cross_check():
        """엔진별 (라벨, 값) 교차 합의 — common.core.repfmt.pairs_of·nlabel·common.core.text.normalize_value로, 서로 다른 계열
        엔진 2개+가 같은 (라벨, 값)을 냈는지 본다(pipeline.transform.represent.crosscheck.build의 문서 1건 안쪽 계산과 같은 식 —
        거긴 qa.json·route.json이 있는 배치 폴더가 있어야 하는데, 이 세션은 parse_text가 이미 모은 결과만 보고
        같은 계산을 한다). 계열 매핑 = pipeline.shared.summarize.FAMILY(없으면 엔진 이름 그대로)."""
        from collections import defaultdict

        from common.core.repfmt import nlabel, pairs_of
        from common.core.text import normalize_value
        from pipeline.shared.summarize import FAMILY

        fam = {e: FAMILY.get(e, e) for e in ctx["engine_results"]}
        by = defaultdict(lambda: {"fams": set(), "label": None, "value": None})
        for e, r in ctx["engine_results"].items():
            for label, value in pairs_of({"text": r.get("text") or "", "facts": r.get("facts") or []}):
                k = (nlabel(label), normalize_value(value))
                if not k[0] or not k[1]:
                    continue
                c = by[k]
                c["fams"].add(fam[e])
                if c["label"] is None:
                    c["label"], c["value"] = label.strip(), value.strip()
        agree = [{"label": v["label"], "value": v["value"], "families": len(v["fams"])} for v in by.values() if len(v["fams"]) >= 2]
        label_vals = defaultdict(set)
        for lk, _vk in by:
            label_vals[lk].add(_vk)
        conflicts = [lk for lk, vs in label_vals.items() if len(vs) > 1]
        ctx["crosscheck"] = {"agree": agree, "conflicts": conflicts}
        _log("cross_check", f"엔진 {len(ctx['engine_results'])}개 교차 — 합의 {len(agree)} · 충돌 {len(conflicts)}")
        return {"agree": len(agree), "conflicts": len(conflicts), "families": sorted(set(fam.values()))}

    def choose_representative():
        """후보(parse_text로 실행한 엔진) 중 대표 선택. ponytail: 정답 없는 실문서의 완전한 순위(common.core.repfmt.
        doc_accuracy — 교차 재현율, AG11 2단계 착수 조건으로 pipeline.transform.represent.parse_qa에서 옮겨 도구 층에서도 부를 수
        있음)는 qa.json 배치 집계(score_engine의 cross_recall 등)가 있어야 나오는데 이 세션엔 없다 — 1단계는 글자
        수가 가장 많은 후보로 근사(로직 불변. 2단계에서 qa.json과 같은 배치 신호를 세션 안에서 구하면 doc_accuracy로
        승격, 설계 §9 D-PA3)."""
        engines_ok = [e for e, r in ctx["engine_results"].items() if (r.get("text") or r.get("facts"))]
        if not engines_ok:
            ctx["rep_engine"] = None
            return {"engine": None, "reason": "성공한 엔진 없음"}
        best = max(engines_ok, key=lambda e: len(ctx["engine_results"][e].get("text") or ""))
        ctx["rep_engine"] = best
        _log("choose_representative", f"대표={best}", candidates=engines_ok)
        return {"engine": best, "candidates": engines_ok}

    def apply_post():
        """후보정 적용 — pipeline.transform.represent.represent.apply_post(rep, doc, doc_path, feats) 그대로(쪽 VLM 옮기기·첨자·차트·
        그림 기록 블록을 덧붙임). choose_representative로 고른 엔진 결과를 rep 뼈대로 쓴다. 그림 PNG·index는
        out_images=out_dir/_images 인자로 직접 넘겨(AG11 2단계 착수 조건) 공유 저장소를 안 건드린다."""
        from pipeline.shared.postprocess import active_features
        from pipeline.transform.represent import represent as REP

        if not ctx.get("rep_engine"):
            return {"error": "choose_representative 먼저"}
        rep = dict(ctx["engine_results"][ctx["rep_engine"]])
        feats = active_features()
        info = REP.apply_post(rep, ctx["doc"], Path(ctx["doc_path"]), feats, out_images=Path(out_dir) / "_images")
        ctx["post"], ctx["rep_text"] = info, rep.get("text")
        _log("apply_post", f"후보정 {sorted(feats)}")
        return info

    def finalize():
        """세션 끝 — 대표 엔진·후보정·교차 대조 충돌을 모은 제안 요약. 운영 _rep는 안 건드린다(shadow — 실행은
        지금 규칙, 설계 §0) — on 모드에서 실제로 쓰는 것은 다음 단계(PA3+) 일."""
        out = {
            "doc": ctx["doc"],
            "engine": ctx.get("rep_engine"),
            "decisions": len(ctx["decisions"]),
            "post": ctx.get("post"),
            "crosscheck_conflicts": len((ctx.get("crosscheck") or {}).get("conflicts") or []),
        }
        ctx["final"] = out
        _log("finalize", "세션 종료 제안")
        return out

    tools = {
        fn.__name__: fn
        for fn in (
            inspect_document,
            parse_text,
            extract_images,
            detect_rotation,
            ocr_region,
            vlm_read,
            summarize_document,
            cross_check,
            choose_representative,
            apply_post,
            finalize,
        )
    }
    assert set(tools) == set(TOOL_NAMES), sorted(tools)
    return tools, ctx


if __name__ == "__main__":
    utf8_stdout()
    print(f"TOOL_NAMES = {TOOL_NAMES}")
