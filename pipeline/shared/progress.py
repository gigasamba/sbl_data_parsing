#!/usr/bin/env python3
"""파싱 진행 현황 → output/parse/PROGRESS.md (고정 위치 · 파싱 1건이 끝날 때마다 갱신)

modules/parse/run_all.py가 문서×엔진 1건을 끝낼 때마다 자동으로 부른다. 다른 방법(별도 venv·수동 parse_one·OpenViking·Cognee 가져오기)으로
파싱했으면 끝날 때마다 직접: python modules/parse/progress.py [--src output/prepared] [--out output/parse]
내용: 전체 진행률 · 형식별 표(문서·성공 문서·전 엔진 실패·대기) · 엔진별 표(성공·실패·시간 초과·미실행(환경)·대기·평균 초·남은 시간 추정)
      · 최근 완료 10건 · 실패 목록. 원자료는 runs.jsonl(같은 문서×엔진은 마지막 기록).
"""

import argparse
import json
import re
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from common.config import settings as C  # common 칸(DOC_DIR_PREPARED, S7c)
from common.core.console import utf8_stdout
from common.core.paths import (  # RV6, tmp+os.replace 공용
    APP_ROOT,  # 폴더 재편 뒤 이 상수만 바뀌면 됨
    atomic_write_text,
    tmp_path_for,
)
from pipeline.extract.engines import registry

# 환경(미설치·미설정) 실패 단서 — 한 곳(run_all RB3② env_failed·parse_qa·실행판 공용). SI45: 예전 "not found"·"NotFoundError"는
# 손상 PDF의 'PdfReadError: EOF marker not found'까지 env로 잡아 그 엔진을 실행 전체에서 건너뛰게 했음 → 구체적인 표현만.
ENV_ERR = (
    "미설정",
    "미설치",
    "ModuleNotFoundError",
    "No module named",
    "command not found",
    "FileNotFoundError",
    "TesseractNotFoundError",
    "NotInstalledError",
    "not installed",
    "SpawnError",
    "initialization fai",
)

# 암호·DRM 오류 단서 — 한 곳(SI44③ run_all 암호 문서 phase 재시도 중단 · run_board.py SRC_RULES와 같은 패턴, 거기도 이걸로
# 바꿀 수 있음). 엔진마다 메시지가 다름 — kreuzberg 'workbook is password protected' · calamine 'password error' ·
# anydoc 'document is encrypted'. 좁게: password·encrypt·암호 포함 메시지만(원본 손상은 다른 신호라 여기 안 넣음).
ENCRYPTED_ERR = re.compile(r"password|encrypt|암호", re.I)


def is_env_error(err):
    return bool(err) and any(k in err for k in ENV_ERR)


def is_encrypted_error(err):
    return bool(err) and bool(ENCRYPTED_ERR.search(err))


def status(rec):
    err = rec.get("error")
    if not err:
        return "ok"
    if is_env_error(err):
        return "env"
    return "timeout" if "Timeout" in err else "fail"


def doc_types(docs, out):
    """문서 → 타입(.pdf는 .pdf_text / .pdf_image — 쪽당 글자 레이어 20자 기준). 판정은 <out>/_types.json에 캐시(크기·수정 시각)."""
    from pipeline.transform.represent.parse_qa import pdf_kind

    cache_f = Path(out) / "_types.json"
    try:
        cache = json.loads(cache_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    res, dirty = {}, False
    for d in docs:
        if d.suffix.lower() != ".pdf":
            res[d.name] = d.suffix.lower()
            continue
        st = d.stat()
        key = f"{d.name}|{st.st_size}|{int(st.st_mtime)}"
        if key not in cache:
            cache[key], dirty = "." + pdf_kind(d)[0], True
        res[d.name] = cache[key]
    if dirty:
        Path(out).mkdir(parents=True, exist_ok=True)
        cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return res


def _fill_chars(runs, out):
    """글자 수 없는 옛 기록(성공)은 출력 JSON에서 한 번 읽어 <out>/_chars.json에 캐시."""
    cache_f = Path(out) / "_chars.json"
    try:
        cache = json.loads(cache_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    dirty = False
    for (doc, eng), r in runs.items():
        if "chars" in r or r.get("error"):
            continue
        k = f"{eng}|{doc}"
        if k not in cache:
            try:
                cache[k] = len((json.loads((Path(out) / eng / (doc + ".json")).read_text(encoding="utf-8")).get("text") or "").strip())
            except (OSError, ValueError):
                cache[k] = 0
            dirty = True
        r["chars"] = cache[k]
    if dirty:
        cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def fmt_s(sec):
    return f"{sec / 3600:.1f}시간" if sec >= 3600 else f"{sec / 60:.0f}분" if sec >= 60 else f"{sec:.0f}초"


def write_progress(src, out, engines=None):
    src, out = Path(src), Path(out)
    docs = sorted(p for p in src.iterdir() if p.is_file() and p.name not in (".gitkeep", "rotation.csv")) if src.is_dir() else []
    runs, order = {}, []
    log = out / "runs.jsonl"
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                runs[(r["doc"], r["engine"])] = r
                order.append(r)
    _fill_chars(runs, out)
    want = registry.select(engines if isinstance(engines, str) else ",".join(engines or []))
    plan = [(d, e) for d in docs for e in registry.engines_for(d.suffix) if not want or e in want]  # 이번 대상 문서×엔진
    types = doc_types(docs, out)
    fmt = lambda d: types.get(d.name, d.suffix.lower())
    # 형식별
    by_fmt = defaultdict(lambda: {"docs": set(), "ok_docs": set(), "tried": set(), "jobs": 0, "done": 0})
    for d, e in plan:
        f = by_fmt[fmt(d)]
        f["docs"].add(d.name)
        f["jobs"] += 1
        r = runs.get((d.name, e))
        if r:
            f["done"] += 1
            f["tried"].add(d.name)
            if status(r) == "ok":
                f["ok_docs"].add(d.name)
    # 엔진별
    by_eng = defaultdict(Counter)
    secs = defaultdict(list)
    for d, e in plan:
        r = runs.get((d.name, e))
        s = status(r) if r else "pending"
        by_eng[e][s] += 1
        if r and s in ("ok", "fail", "timeout"):
            secs[e].append(r["sec"])
    total = len(plan)
    done = sum(1 for d, e in plan if (d.name, e) in runs)
    remain = sum(by_eng[e]["pending"] * (statistics.mean(secs[e]) if secs[e] else 0) for e in by_eng)
    unknown = sum(by_eng[e]["pending"] for e in by_eng if not secs[e])
    ok_docs = {n for f in by_fmt.values() for n in f["ok_docs"]}
    md = [
        f"# 파싱 진행 현황 — {time.strftime('%Y-%m-%d %H:%M:%S')} 갱신",
        "",
        f"문서 {len(docs)}개 · 성공 문서(엔진 1개 이상 성공) **{len(ok_docs)}/{len(docs)}** · 문서×엔진 **{done}/{total}** "
        f"({done / total:.0%}) · 남은 시간 추정 "
        + (f"약 {fmt_s(remain)}" if remain else "—")
        + (f" (+ 아직 한 번도 안 돈 엔진의 {unknown}건은 추정 불가)" if unknown else "")
        if total
        else "대상 없음",
        "",
        "원자료: `runs.jsonl` · 자동 갱신: `modules/parse/run_all.py`가 1건마다 · 다른 방법으로 파싱했으면 `python modules/parse/progress.py`",
        "",
        "## 형식별",
        "",
        "| 형식 | 문서 | 성공 문서 | 전 엔진 실패 | 아직 안 돈 문서 | 문서×엔진 완료 |",
        "|---|---|---|---|---|---|",
    ]
    for k in sorted(by_fmt):
        f = by_fmt[k]
        all_failed = len(f["tried"] - f["ok_docs"])
        md.append(
            f"| {k} | {len(f['docs'])} | {len(f['ok_docs'])} | {all_failed} | {len(f['docs'] - f['tried'])} | {f['done']}/{f['jobs']} |"
        )
    md += [
        "",
        "## 엔진별",
        "",
        "| 엔진 | 성공 | 실패 | 시간 초과 | 미실행(환경) | 대기 | 평균 초 | 남은 시간 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in sorted(by_eng, key=lambda x: (-by_eng[x]["pending"], x)):
        c, m = by_eng[e], (statistics.mean(secs[e]) if secs[e] else None)
        md.append(
            f"| {e} | {c['ok']} | {c['fail']} | {c['timeout']} | {c['env']} | {c['pending']} | {'' if m is None else f'{m:.1f}'} | "
            f"{'' if m is None or not c['pending'] else fmt_s(c['pending'] * m)} |"
        )
    # 타입 × 엔진 결과표 — 1단계(타입별 1개 표본)에서 "무엇이 안 되는지"를 한눈에
    tcols = sorted({fmt(d) for d in docs})
    cell, per_doc = defaultdict(list), defaultdict(list)  # 한 번만 묶음(셀마다 전체 목록을 훑지 않게)
    for d, e in plan:
        r = runs.get((d.name, e))
        cell[(e, fmt(d))].append(r)
        per_doc[d.name].append(status(r) if r else "pending")
    md += [
        "",
        "## 타입 × 엔진 결과",
        "",
        "✓ = 성공(평균 글자 수 · 평균 초) · ✗ = 실패·시간 초과(사유는 아래 실패 목록) · 환경 = 미설치·미설정(이 서버에서 못 돎) · … = 대기 · 빈칸 = 그 형식을 처리하지 않는 엔진",
        "",
        "| 엔진 | " + " | ".join(tcols) + " |",
        "|---|" + "---|" * len(tcols),
    ]
    for e in sorted({e for _, e in plan}):
        cells = []
        for t in tcols:
            recs = cell.get((e, t), [])
            if not recs:
                cells.append("")
                continue
            st = Counter(status(r) if r else "pending" for r in recs)
            oks = [r for r in recs if r and status(r) == "ok"]
            if oks and len(oks) == len(recs):
                avg = sum(r.get("chars", 0) for r in oks) // len(oks)
                cells.append("⚠ 빈 결과(0자)" if avg == 0 else f"✓ {avg:,}자 · {sum(r['sec'] for r in oks) / len(oks):.1f}s")
            elif oks:
                cells.append(
                    f"✓{len(oks)}/{len(recs)}"
                    + (f" ✗{st['fail'] + st['timeout']}" if st["fail"] + st["timeout"] else "")
                    + (f" …{st['pending']}" if st["pending"] else "")
                )
            elif st["fail"] + st["timeout"]:
                cells.append("✗" + ("" if len(recs) == 1 else f"{st['fail'] + st['timeout']}/{len(recs)}"))
            elif st["env"]:
                cells.append("환경")
            else:
                cells.append("…")
        md.append(f"| {e} | " + " | ".join(cells) + " |")
    # 안 되는 것 — 표를 사람이 훑지 않아도 되게 목록으로
    env_e, fail_et, empty_et, ok_types = {}, defaultdict(list), defaultdict(list), set()
    for d, e in plan:
        r = runs.get((d.name, e))
        if not r:
            continue
        st, t = status(r), fmt(d)
        if st == "env":
            env_e.setdefault(e, str(r["error"]).splitlines()[0][:90])
        elif st in ("fail", "timeout"):
            fail_et[e].append(t)
        elif r.get("chars", 1) == 0:
            empty_et[e].append(t)
        else:
            ok_types.add(t)
    tried_types = {fmt(d) for d, e in plan if (d.name, e) in runs}
    md += ["", "## 안 되는 것 (자동 정리)", ""]
    md += [f"- **성공한 엔진이 하나도 없는 타입**: {', '.join(sorted(tried_types - ok_types)) or '없음'}"]
    md += ["- **이 서버에서 못 도는 엔진(미설치·미설정)**: " + ("없음" if not env_e else "")]
    md += [f"  - {e} — {why}" for e, why in sorted(env_e.items())]
    md += [
        "- **실패·시간 초과(엔진: 타입)**: "
        + ("없음" if not fail_et else "; ".join(f"{e}: {', '.join(sorted(set(v)))}" for e, v in sorted(fail_et.items())))
    ]
    md += [
        "- **빈 결과 0자(엔진: 타입)** — 대개 글자 레이어 파서가 이미지 PDF를 받은 경우(정상 한계): "
        + ("없음" if not empty_et else "; ".join(f"{e}: {', '.join(sorted(set(v)))}" for e, v in sorted(empty_et.items())))
    ]
    md += ["", "## 문서별 (형식 순)", "", "| 문서 | 형식 | 성공 엔진 | 실패·시간 초과 | 미실행(환경) | 대기 |", "|---|---|---|---|---|---|"]
    for d in sorted(docs, key=lambda x: (fmt(x), x.name)):
        c = Counter(per_doc.get(d.name, []))
        md.append(f"| {d.name} | {fmt(d)} | {c['ok']} | {c['fail'] + c['timeout']} | {c['env']} | {c['pending']} |")
    md += ["", "## 최근 완료 10건", "", "| 문서 | 엔진 | 결과 | 초 |", "|---|---|---|---|"]
    md += [f"| {r['doc']} | {r['engine']} | {status(r)} | {r['sec']} |" for r in order[-10:][::-1]]
    fails = [r for r in runs.values() if status(r) in ("fail", "timeout")]
    md += ["", f"## 실패·시간 초과 {len(fails)}건 (미실행(환경)은 제외)", ""]
    md += [f"- {r['doc']} · {r['engine']} — {str(r['error'])[:160]}" for r in fails[-30:]] or ["- 없음"]
    out.mkdir(parents=True, exist_ok=True)
    text = "\n".join(md) + "\n"
    for _ in range(5):  # 반쯤 쓴 파일이 안 보이게 교체 — Windows는 다른 프로세스가 열고 있으면 잠깐 거부
        try:
            atomic_write_text(out / "PROGRESS.md", text)  # RV6 — 여러 프로세스(--procs)가 동시에 써도 임시 파일은 따로(common/atomic.py)
            break
        except PermissionError:
            time.sleep(0.2)
    else:
        tmp_path_for(out / "PROGRESS.md").unlink(missing_ok=True)
    return out / "PROGRESS.md"


if __name__ == "__main__":
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--src", default=C.cfg().paths.doc_dir_prepared or str(APP_ROOT / "output" / "prepared")
    )  # SI11 — cli/pipeline.py와 같은 env(DOC_DIR은 준비 전 원본 폴더, 다른 것)
    ap.add_argument("--out", default=str(APP_ROOT / "output" / "parse"))
    ap.add_argument("--engines", default="", help="비우면 핵심 엔진(registry.CORE) · all = 전부 · a,b = 그것만")
    a = ap.parse_args()
    p = write_progress(a.src, a.out, a.engines)
    print(p.read_text(encoding="utf-8").split("\n## 엔진별")[0])
