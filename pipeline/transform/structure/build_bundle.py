#!/usr/bin/env python3
"""저장소 묶음 만들기(로컬 output/edw/bundle → PostgreSQL 적재 원본, EDW에는 적재 안 함) — 파싱 선정 엔진 결과 → 청크(원본 위치) · 요약 · 메타 · 임베딩 → output/edw/bundle/

기술 비교 없이 **파싱에서 선정된 엔진만** 쓴다(output/parse/selection.json `final` 형식별 주 엔진 → 실패면 예비 → route 순).
  청크   : structure 청커(pipeline.transform.structure.chunking, AD32③ — evaluation.stages는 조합 실험용으로 같은 것을 가져다 씀) — 본문은 정제 텍스트(쪽 번호 줄 제외), 위치 = 파일 경로·쪽·줄·문자 범위·제목,
           쪽 안 위치(bbox, pt) = OCR 엔진은 글자 상자 합집합, 텍스트 PDF는 원본 PDF에서 청크 첫·끝 줄을 찾아 합집합
  요약   : 앞부분 발췌(LLM 요약은 op-08에 지움 — --summary auto·lead 둘 다 발췌)
  메타   : 고객사·계약 번호 — 파싱 모듈 교차 확인 값(_rep rep.meta)(서로 다른 계열 파서 2개+)만
  임베딩 : --embed api(EMBED_BASE_URL·EMBED_MODEL — 서버 임베딩 전용 모델) · bge-m3 · e5-small … (L2 정규화 저장, 차원은 첫 응답에서)
  (지식 그래프 kg_nodes·kg_edges · 개념→청크 concept_chunk · 그림 행 images.jsonl · 집계 사실 facts.jsonl은 11-01에 지움 — PRD pl-06:
   아무도 적재·조회하지 않음(facts.jsonl을 읽던 검색 쪽 집계는 mc-04에서 지움). kg_nodes.jsonl·kg_edges.jsonl은 빈 파일로만 씀 — 묶음 계약 common/core/contract.py가 파일을 요구, 그 목록은 핸드오프 지문 파일이라 0.2.0 배치에서 고침)
산출: docs.jsonl · chunks.jsonl · vectors.npy(float32, chunks 순서) · meta.json · kg_nodes.jsonl·kg_edges.jsonl(빈 파일)
사용: python -m pipeline.transform.structure.build_bundle [--parse-dir output/parse] [--src output/prepared] [--embed api|bge-m3] [--summary auto|lead] [--out output/edw/bundle]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from common.ai.embed import embed_texts
from common.config import layout as L  # 안내 메시지의 settings.yaml 자리
from common.config import settings as C  # S7c: 설정 객체(common 칸 EMBED_MODEL·EMBED_BASE_URL·LLM_ALLOW_EXTERNAL·GLOSSARY_DIR·OV_URL)
from common.core import docmeta as DM  # 날짜·개정·구판·문서군(L3-1, structure·search 공용 규칙)
from common.core import repfmt as AQ  # 대표 결과 형식 읽기(라벨 어휘·키-값 쌍·표 행)
from common.core import terms as T  # 고객 명부·이름 정규화·ID 모양(검색과 같은 규칙)
from common.core.console import utf8_stdout
from common.core.contract import (  # 문서 ID(doc_key) 규칙(GH1-04: orig_sha256으로 parse와 같은 값)
    file_hash,
    original_file_hash,
)
from common.core.meaning import strip_page_numbers
from common.core.paths import APP_ROOT  # 폴더 재편 뒤 이 상수만 바뀌면 됨
from common.core.text import (  # 색인 본문·토큰 규칙(모듈 계약)
    index_text,
    normalize_value,
    tokens,
)
from pipeline import config as pc  # S7c: 설정 객체(pipeline 칸)
from pipeline.transform.structure import chunking as S  # 청킹·개체 정규식(구조화 모듈)
from pipeline.transform.structure import facts as AG  # 제품 코드(PRODUCT_CODE_RE — 용어 draft)
from pipeline.transform.structure import terms as ST  # name_hits·seed_roster(구조화 전용, 10-16 분리)


def pick_engine(doc, dd, sel, route):
    """선정 엔진(주 → 예비) 중 이 문서에서 성공한 것, 없으면 형식별 순위(route)에서 성공한 첫 엔진."""
    ok = {e for e, m in dd["engines"].items() if m.get("ok")}
    for e in (sel.get("final") or {}).get(dd["format"], []) + route.get(dd["format"], []):
        if e in ok:
            return e
    return sorted(ok)[0] if ok else None


def ocr_bbox(boxes, text, span):
    """OCR 글자 상자 → 청크 문자 범위와 겹치는 상자들의 합집합(쪽마다 첫 쪽만)."""
    pos, hits = 0, []
    for b in boxes:
        i = text.find(b["text"], pos)
        if i < 0:
            continue
        pos = i + len(b["text"])
        if i < span[1] and pos > span[0]:
            hits.append(b)
    if not hits:
        return None
    pg = hits[0].get("page")
    bb = [b["bbox"] for b in hits if b.get("page") == pg and b.get("bbox")]
    return (
        ",".join(f"{v:.0f}" for v in (min(x[0] for x in bb), min(x[1] for x in bb), max(x[2] for x in bb), max(x[3] for x in bb)))
        if bb
        else None
    )


def pdf_bbox(path, page, chunk_text, _cache={}):  # noqa: B006 — 일부러 함수 기본값 사전을 프로세스 캐시로 씀(쪽 단어 목록)
    """텍스트 PDF: 원본 PDF 그 쪽에서 청크 첫 줄·끝 줄을 찾아 합집합(pt, 왼쪽 위 원점). 못 찾으면 None."""
    try:
        import fitz
    except ImportError:
        return None
    if path not in _cache:
        try:
            _cache[path] = fitz.open(path)
        except Exception:
            _cache[path] = None
    pdf = _cache[path]
    if pdf is None or not page or page > len(pdf):
        return None
    lines = [ln.strip() for ln in chunk_text.splitlines() if len(ln.strip()) >= 4]
    if not lines:
        return None
    pg = pdf[page - 1]
    rects = [r for ln in (lines[0][:60], lines[-1][:60]) for r in pg.search_for(ln)[:1]]
    if not rects:
        return None
    return ",".join(
        f"{v:.0f}" for v in (min(r.x0 for r in rects), min(r.y0 for r in rects), max(r.x1 for r in rects), max(r.y1 for r in rects))
    )


def lead_summary(text, n=300):
    """앞부분 발췌(유의미 줄만, n자) — 요약이 없을 때 표시용(사실 왜곡 없음)."""
    out = []
    for ln in strip_page_numbers(text).splitlines():
        if re.search(r"[가-힣A-Za-z0-9]{2,}", ln):
            out.append(ln.strip())
        if sum(map(len, out)) >= n:
            break
    return " ".join(out)[:n]


def _embed(model, texts, kind):
    return embed_texts(model, texts, kind)  # 자기 점검이 가짜로 바꿔 끼우는 자리


def embed_all(model, texts, batch=None, cache=None, out=None):
    """청크 본문 → 벡터(L2 정규화). 같은 모델·같은 본문은 **임베딩 캐시**(EMBED_CACHE, 기본 output/edw/embed_cache.sqlite)에서 재사용 —
    수집 서버 새벽 배치가 매번 전체 청크를 API로 다시 보내지 않고 새·바뀐 청크만. EMBED_CACHE=0이면 끔.
    out(.npy 경로)을 주면 벡터를 파일에 바로 씀(memmap) — 청크 100만 × 4096차원 ≈ 16 GB를 메모리에 올리지 않게.
    EMBED_BATCH(기본 32)개씩 · 실패하면 EMBED_RETRY(기본 2)번 다시(대기 2·4초) — 임베딩 서버 일시 과부하에 배치 전체가 죽지 않게."""
    import hashlib as _h
    import sqlite3
    import time as _t

    import numpy as np

    if model == "none":  # 임베딩 없이(키워드·ID 검색만) — 임베딩 서버가 없는 곳에서 구조화·검색 시험
        arr = np.zeros((len(texts), 0), dtype=np.float32)
        if out:
            np.save(out, arr)
        return arr
    st = (
        pc.cfg().transform.structure
    )  # S7c — 설정 객체(EMBED_MAX_CHARS 8000·EMBED_BATCH 32·EMBED_RETRY 2·EMBED_CONCURRENCY 4 — 빈 글자도 기본값)
    cap = int(st.embed_max_chars)  # 안전망: 쪼개지 않은 청커가 너무 긴 본문을 내도 전체 빌드가 400으로 죽지 않게 자름(L3-3)
    over = sum(1 for t in texts if len(t) > cap)
    if over:
        texts = [t[:cap] if len(t) > cap else t for t in texts]
        print(f"임베딩 입력 길이 상한 초과 {over}건 → {cap}자로 자름(EMBED_MAX_CHARS)", flush=True)
    batch = batch or int(st.embed_batch)
    retry = int(st.embed_retry)
    if cache is None:  # 옛 `get("EMBED_CACHE", 기본)` — 비운 값('')은 그대로 두어 캐시 끔(기본값 None 글자 칸은 ''를 ''로 남김)
        cache = st.embed_cache if st.embed_cache is not None else str(APP_ROOT / "output" / "edw" / "embed_cache.sqlite")
    mid = f"{model}:{C.cfg().models.embed.model if model == 'api' else ''}"  # 모델이 바뀌면 다른 키 · S7c — 설정 객체
    keys = [_h.sha256((mid + "\n" + t).encode("utf-8")).hexdigest() for t in texts]
    arr, done, db = None, np.zeros(len(texts), dtype=bool), None

    def put(j, row):
        nonlocal arr
        if arr is None:  # 첫 벡터에서 차원을 알고 나서 자리 마련
            shape = (len(texts), len(row))
            arr = np.lib.format.open_memmap(out, mode="w+", dtype=np.float32, shape=shape) if out else np.empty(shape, np.float32)
        nr = float(np.linalg.norm(row))
        arr[j] = row / (nr or 1)
        done[j] = True

    if cache and cache != "0":
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(cache, timeout=120)  # 병렬 빌드가 같은 캐시를 함께 씀 — 잠김이면 기다림(기본 5초는 짧음)
        db.execute("CREATE TABLE IF NOT EXISTS e (k TEXT PRIMARY KEY, v BLOB)")
        for i in range(0, len(keys), 900):  # 900개씩 꺼내 바로 씀(캐시 전체를 메모리에 모으지 않음)
            part = keys[i : i + 900]
            got = dict(db.execute(f"SELECT k, v FROM e WHERE k IN ({','.join('?' * len(part))})", part).fetchall())
            for j in range(i, i + len(part)):
                if keys[j] in got:
                    put(j, np.frombuffer(got[keys[j]], dtype=np.float32))
    todo = [i for i in range(len(texts)) if not done[i]]
    conc = max(1, int(st.embed_concurrency))  # 2026-10-22 — 임베딩 호출 병렬(EMBED_BATCH 묶음씩 동시 전송, 기본 4)
    t_embed0 = _t.time()
    slices = [todo[i : i + batch] for i in range(0, len(todo), batch)]

    def _one(idx):
        for k in range(retry + 1):
            try:
                return np.asarray(_embed(model, [texts[j] for j in idx], "passage"), dtype=np.float32)
            except (OSError, TimeoutError):
                if k == retry:
                    raise
                _t.sleep(2 * (k + 1))

    def _store(idx, v):  # 메인 스레드에서만 — put()의 arr 첫 할당·sqlite 쓰기가 스레드 경합 없게
        for j, row in zip(idx, v):
            put(j, row)
        if db is not None:
            db.executemany("INSERT OR REPLACE INTO e(k, v) VALUES (?, ?)", [(keys[j], row.tobytes()) for j, row in zip(idx, v)])
            db.commit()

    if conc > 1 and len(slices) > 1:  # 병렬 — 워커는 HTTP 호출만, 저장(캐시·배열)은 메인 스레드가 완료 순서대로
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=conc) as ex:
            futs = {ex.submit(_one, idx): idx for idx in slices}
            for fut in as_completed(futs):
                _store(futs[fut], fut.result())
    else:
        for idx in slices:
            _store(idx, _one(idx))
    if db is not None:
        db.close()
    print(
        f"임베딩 캐시: 재사용 {len(texts) - len(todo)} · 새로 {len(todo)}"
        + (f" ({cache})" if db is not None else "")
        + f" · 호출 {len(slices)}회(병렬 {min(conc, len(slices))}) · {_t.time() - t_embed0:.1f}s",
        flush=True,
    )
    if arr is None:
        arr = np.zeros((0, 1), dtype=np.float32)
        if out:
            np.save(out, arr)
    elif out:
        arr.flush()
    return arr


def infer_clients(docs, head=400, roster=None):
    """문서 고객 라벨(다중 가능, 10-14) — d['clients'](증거 강도 내림차순 목록) + 기존 호환용 d['client'](= clients[0],
    단일 필드를 쓰는 옛 호출자·검색 경로용 1순위)를 채운다.

    (1) 전체 본문(머리 400자만이 아니라 — 이전 버그: 400자 뒤에만 나오는 고객 이름을 영영 못 봤다)에서 알려진
    고객 이름·별칭이 — ⓐ 2회 이상 나오거나 ⓑ 제목/첫 head자 안에 한 번이라도 나오면(잡음 가드 — 본문 뒤쪽 1회
    등장만으로는 "같이 언급된 제3자"와 구분 안 됨, review ①) '증거 있음'으로 본다. 등장 횟수는 단어 경계·한글
    조사 인식 매칭(ST.name_hits·_name_pat, match_clients·expand_query와 같은 규칙)으로 센다 — 독립 검토
    10-14: raw substring count("in")는 경계가 없어 짧은 별칭(예 "MSD")이 "MSDS" 안에서도 걸리는 잡음이 났다.
    증거 있는 고객이 여럿이면
    (이전 버그: 정확히 하나일 때만 채웠다 — 둘 이상이면 그대로 비워 둠) 전부 clients에, 증거 강한 순(제목/머리
    등장 먼저 · 그다음 등장 횟수 · 동점은 이름순, 결정적)으로 담는다. meta_confirmed 문서는 자기 확정 고객이
    항상 clients[0](1순위) — 본문에 다른 알려진 고객이 같이 나오면 뒤에 더한다(그 문서의 2번째 이하 라벨).
    (2) 그래도 clients가 비면 제품 코드 접두어(MRH-MAB-01 → MRH)를 다른 문서에서 그 고객과 함께 나온 것으로
    배워 채움(client_src='product') — 그대로, clients에도 반영.
    알려진 고객 = 교차 확인된 고객 + 고객 명부(roster, 기본 T._aliases() — stack.json client_aliases·CLIENT_ROSTER·
    GLOSSARY_DIR org_client) + 주요 바이오·제약사 공개 이름 seed(pipeline.transform.structure.terms.seed_roster())
    합집합 — roster를 명시하면(옛 호출자·시험) seed는 안 더함(바이트 동일).
    ponytail: 알려진 고객 수 × 문서 전체 길이 스캔(O(roster×len(text))) — 명부가 아주 커지면 아호코라식 등으로."""
    if roster is None:
        roster = dict(T._aliases())
        for c, al in ST.seed_roster().items():
            roster[c] = sorted(set(roster.get(c, [])) | set(al))
    known = {d["client"]: [] for d in docs if d.get("meta_confirmed") and d.get("client")}
    known.update({c: list(a) for c, a in roster.items()})
    for d in docs:
        text = d.get("full_text") or ""
        head_text = text[:head]
        scored = []
        for c, al in known.items():
            names = [n for n in [c] + al if n]
            if not names:
                continue
            cnt = sum(
                ST.name_hits(n, text) for n in names
            )  # 독립 검토 10-14 — 경계 인식 카운트(raw substring 아님, 원문 그대로 — 공백은 name_hits가 처리)
            if cnt == 0:
                continue
            in_head = any(ST.name_hits(n, head_text) for n in names)
            if cnt >= 2 or in_head:  # 잡음 가드 — 뒤쪽 1회 등장만으로는 안 채움
                scored.append(((1 if in_head else 0, cnt), c))
        scored.sort(key=lambda x: (-x[0][0], -x[0][1], x[1]))  # 제목/머리 먼저 · 횟수 내림 · 이름 오름(결정적)
        hits = [c for _, c in scored]
        primary = d.get("client")
        if not primary and hits:
            primary = hits[0]
            d["client"], d["client_src"] = primary, "text"
        if primary or hits:
            d["clients"] = ([primary] if primary else []) + [c for c in hits if c != primary]
    pre = {}
    for d in docs:
        for code in set(AG.PRODUCT_CODE_RE.findall_codes(d.get("full_text") or "")) if d.get("client") else ():
            pre.setdefault(code.split("-")[0], set()).add(d["client"])
    for d in docs:
        code = (d.get("contract") or {}).get("product_code")
        if not d.get("client") and code and len(pre.get(code.split("-")[0], ())) == 1:
            cl = next(iter(pre[code.split("-")[0]]))
            d["client"], d["client_src"] = cl, "product"
            d["clients"] = [cl] + [c for c in d.get("clients", []) if c != cl]


def warn_if_no_client_roster(docs):
    """BR57 — 명부(GLOSSARY_DIR org_client + stack.json client_aliases)가 비어 있어 canon_clients·infer_clients가
    아무것도 못 채운 채(묶음에 문서가 있는데도 client가 전부 빈 채) 끝났으면 경고 한 줄만(동작은 안 바꿈 — 이
    묶음을 쓰는 검색 쪽 clientscope·BR23 엔티티 분해가 조용히 무동작이 되는 원인을 빌드 시점에 알린다. 실측:
    V11 풀 묶음이 GLOSSARY_DIR 없이 지어져 505건 전부 client 없음 → BR57에서 드러남)."""
    if not docs or any(d.get("client") for d in docs):
        return
    if T._aliases():
        return  # 명부는 있는데 이 묶음 문서들이 그냥 다 안 걸렸을 뿐 — 경고 대상 아님
    print(
        "WARNING: 고객 명부 없음 — client 메타가 비어 고객 필터·비교 분할이 동작 안 함"
        f" (settings.yaml {L.to_yaml('common.paths.glossary_dir')}·{L.to_yaml('common.paths.client_roster')} 확인)",
        file=sys.stderr,
        flush=True,
    )


def collect_draft_terms(docs, glossary_dir=None):
    """SI43④ — 문서에서 새 회사 이름 후보(structure/draft_terms.py 휴리스틱)를 찾아 이미 아는 이름(명부·용어집
    전 카테고리 — client든 CDMO든, approved만 — draft 자신은 빼지 않음: 여러 구조화 실행에 걸쳐 되풀이로 나온
    이름일수록 write_draft_terms의 카운트가 올라가야 "가장 빈번한 것"이 의미가 있다)을 뺀 나머지를
    **output/ 자동 draft CSV**(`terms.write_draft_terms` → `terms.draft_terms_path()`, GLOSSARY_DIR이 아님 — 독립
    검토 BLOCK 1, 10-13: GLOSSARY_DIR은 서버에서 이미지 밖 실 운영 사전 폴더라 거기 쓰면 PermissionError로
    구조화 전체가 깨진다)에 쌓는다 — 사람 승인 없이, BM25 weak 가중만(하드 필터·고객 판별엔 안 들어감).
    glossary_dir 인자는 **읽기**(이미 아는 approved 이름 판별)에만 쓰고, 쓰기 경로는 항상 output/(또는
    DRAFT_TERMS_OUT) — 둘을 혼동하지 않는다. 이 함수 전체(명부·
    용어집 읽기 포함)를 try/except로 감싸 — 어떤 이유로든(디스크 가득·권한·잠긴 파일) 실패해도 WARNING만 찍고
    빈 목록을 돌려준다(warn_if_no_client_roster와 같은 관례) — 구조화(build_bundle.py main())가 이 보조 기능 때문에
    멈추지 않게. 반환: 새로 추가한 이름 목록(로그용, 실패하면 빈 목록)."""
    d = glossary_dir or C.cfg().paths.glossary_dir  # S7c — 설정 객체(인계 칸 — terms.py는 아직 env로 읽음)
    try:
        from pipeline.transform.structure import draft_terms as DT

        known = set(T._aliases()) | {a for al in T._aliases().values() for a in al}
        if d:
            for r in T.load_glossary(d).values():  # 모든 카테고리(org_client든 org_cdmo든) — approved만, draft는 안 뺌
                known.add(r.get("canonical") or "")
                known.update(T.split_terms(r.get("synonyms")))
                known.update(T.split_terms(r.get("abbreviations")))
        known_norm = {T.norm(n) for n in known if n}
        cands = DT.collect_candidate_org_names(docs, known_norm, T.norm)
        return T.write_draft_terms(cands, category="org_client")
    except Exception as ex:  # 독립 검토 BLOCK 1: 보조 기능 실패가 구조화를 깨면 안 됨
        print(f"WARNING: SI43④ 새 회사 이름 후보 draft 쓰기 실패(구조화는 계속) — {type(ex).__name__}: {ex}", file=sys.stderr, flush=True)
        return []


def canon_clients(docs, cut=0.9):
    """OCR 오탈자 고객사 이름(Northfeld) → 교차 확인된 고객사 이름(Northfield)으로. 확인 안 된 값만, 유사도 cut 이상일 때만
    바꾸고 원래 값은 client_raw에 남김. 개발 PC 실측: rapidocr_ko·paddleocr(같은 PP-OCR 계열)가 같은 글자를 같이 틀림."""
    import difflib

    known = {d["client"] for d in docs if d.get("meta_confirmed") and d.get("client")}
    for d in docs:
        c = d.get("client")
        if c and not d.get("meta_confirmed") and c not in known:
            m = difflib.get_close_matches(c, known, n=1, cutoff=cut)
            if m:
                d["client_raw"], d["client"] = c, m[0]


def load_figures(images_dir):
    """output/parse/_images/index.jsonl(파싱 모듈 W1·W9·W11 그림 기록) → {문서 파일명: [기록, …]}. 없으면 빈 묶음(그림 0건 — 오류 아님)."""
    f = Path(images_dir) / "index.jsonl"
    by_doc = {}
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                by_doc.setdefault(r["doc"], []).append(r)
    return by_doc


def figure_chunk_text(rec):
    """그림 기록(설계 §3 계약 — vlm{model,summary,text,content}) → 청크 본문(L1, 자르지 않는 청크 1개): 캡션 + 요약 + 그림 글자 + 값/연결/표."""
    vlm = rec.get("vlm") or {}
    content = vlm.get("content") or {}
    vals = ", ".join(f"{v.get('label')}={v.get('value')}{v.get('unit') or ''}" for v in content.get("values") or [] if v.get("label"))
    edges = ", ".join(
        f"{e.get('from')} → {e.get('to')}" + (f"({e['label']})" if e.get("label") else "")
        for e in content.get("edges") or []
        if e.get("from")
    )
    parts = [f"[그림 {rec['image_id']}] ({rec.get('kind') or ''})"]
    if rec.get("caption"):
        parts.append(f"캡션: {rec['caption']}")
    parts += [f"요약: {vlm.get('summary') or ''}", f"그림 글자: {vlm.get('text') or ''}"]
    if vals:
        parts.append(f"값: {vals}")
    if edges:
        parts.append(f"연결: {edges}")
    if content.get("table_md"):
        parts.append(content["table_md"])
    trend = rec.get(
        "trend"
    )  # F14(c) — parse 쪽(pipeline.transform.figures.chart_values)이 이미 계산해 기록에 넣어 둔 값을 그대로 읽기만(rag-core↔rag-parse import 경계 유지)
    if trend and trend.get("direction"):
        parts.append(f"추세: {trend['direction']}({trend.get('period') or ''}, {trend.get('basis') or ''})")
    return "\n".join(parts)


def _vc_status(check):
    """값 확인 상태(요약 한 단어) — conflict(사람 확인) > agree(본문과 일치) > none."""
    check = check or {}
    if check.get("conflict"):
        return "conflict"
    if check.get("agree"):
        return "agree"
    return "none"


def figure_chunk(di, seq, rec, source_system=None):
    """그림 기록(_images/index.jsonl, 설계 §3 계약) → 청크 1개(L1, nofig — 쪼개지 않음) — BM25·벡터 둘 다에 들어감(일반 청크와 같은 목록)."""
    text = figure_chunk_text(rec)
    # page는 PDF 쪽·pptx 슬라이드 번호 겸용(그림 기록 계약에 별도 slide 필드 없음 — image_id #p<n>과 같은 값)
    return {
        "doc": di,
        "seq": seq,
        "page": rec.get("page"),
        "sheet": rec.get("sheet"),
        "line_start": None,
        "line_end": None,
        "char_start": None,
        "char_end": None,
        "bbox": rec.get("bbox"),
        "section": None,
        "chunk_text": text,
        "n_chars": len(text),
        "n_terms": len(tokens(text)),
        "image_id": rec.get("image_id"),
        "provenance_model": (rec.get("provenance") or {}).get("model"),
        "value_check_status": _vc_status(rec.get("value_check")),
        "source_system": source_system,
    }


def fig_empty(rec):
    """AD21③ — 검색 청크로 만들 가치 없는 그림 기록: 상한·작은·반복으로 VLM이 안 돈 것(skipped) 또는 VLM이
    돌았지만 요약·글자·값·연결·표가 모두 빈 플레이스홀더. 캡션은 안 봄(본문에 이미 있어 캡션만으로는 그림 청크를 안 만들 근거가 안 됨)."""
    vlm = rec.get("vlm") or {}
    content = vlm.get("content") or {}
    return not any(
        [
            (vlm.get("summary") or "").strip(),
            (vlm.get("text") or "").strip(),
            content.get("values"),
            content.get("edges"),
            (content.get("table_md") or "").strip(),
        ]
    )


def fig_page_child(rec, page_vlm_ids):
    """F11 — 쪽 VLM이 이미 쪽 전체를 옮겨 적은(부모 skipped=page_vlm) 하위 그림: 내용이 본문 청크와 겹쳐 합본 잡음·1위 하락
    → 검색 청크는 안 만들고 image_id만 본문 청크에 연결(get_image·images.jsonl엔 남음)."""
    return rec.get("parent_image_id") in page_vlm_ids


def fig_host(doc_chunks, page):
    """독립 검토 MINOR② — 빈 그림의 image_id를 붙일 텍스트 청크: 같은 쪽 우선(여러 개면 마지막, 즉 그 쪽 마지막 조각) ·
    없으면 쪽 번호가 가장 가까운 청크(동점은 앞선 것, 안정) · 쪽 번호 있는 청크가 전혀 없으면 문서 첫 청크."""
    if not doc_chunks:
        return None
    same = [c for c in doc_chunks if c.get("page") == page]
    if same:
        return same[-1]
    paged = [(abs(c["page"] - page), i, c) for i, c in enumerate(doc_chunks) if c.get("page") is not None and page is not None]
    if paged:
        return min(paged, key=lambda t: (t[0], t[1]))[2]
    return doc_chunks[0]


def _rel_to_source(path):
    """PC 폴더 원천의 원본 경로 → 원천 폴더(PARSE_SOURCE) 기준 상대 경로(posix). 그 폴더 밖이거나 폴더 원천이 아니면 None."""
    root = pc.cfg().extract.input_source
    if not root or root.startswith("rdb:"):
        return None
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--parse-dir", default="output/parse")
    ap.add_argument("--src", default="output/prepared", help="원본 문서 폴더(파일 경로·sha·PDF 위치 찾기)")
    ap.add_argument(
        "--path-prefix",
        default=pc.cfg().load.edw_path_prefix,
        help="저장소(doc.file_path)에 기록할 원본 경로 접두(서버의 실제 보관 위치) — 없으면 --src 절대 경로",
    )
    ap.add_argument(
        "--embed", default=pc.cfg().transform.structure.embed or ("api" if C.cfg().models.embed.base_url else "bge-m3")
    )  # S7c — 설정 객체
    ap.add_argument("--summary", default="auto", choices=["auto", "lead"], help="둘 다 앞부분 발췌(옛 호출·색인 설정 호환)")
    ap.add_argument("--chunk", default=None, help="기본 = stack.json chunk(없으면 structure)")
    ap.add_argument("--stack", default=None, help="엔진 구성 파일(PC 실험·시험용 — 비우면 설정 common.paths.stack_file)")
    ap.add_argument("--no-rep", action="store_true", help="대표 파싱(output/parse/_rep) 대신 선정 엔진을 문서마다 고름(단계 1 실험용)")
    ap.add_argument("--images-dir", default=None, help="그림 기록 index.jsonl 폴더(L1, 기본 = --parse-dir/_images) — 없으면 그림 청크 0건")
    ap.add_argument("--out", default="output/edw/bundle")
    a = ap.parse_args(argv)
    stack = json.loads(Path(a.stack).read_text(encoding="utf-8")) if a.stack else pc.stack()
    a.chunk = a.chunk or stack.get("chunk") or "structure"
    t0 = time.time()
    pd = Path(a.parse_dir)
    fig_by_doc = load_figures(a.images_dir or (pd / "_images"))  # L1: 그림 기록(W1·W9·W11) → 문서별 그림 청크
    use_rep = not a.no_rep and (pd / "_rep" / "index.json").exists()  # 단계 2: 고정 스택의 대표 파싱 결과만
    reps = {}
    if use_rep:  # 파싱 모듈 인계 = _rep 폴더 하나(형식·쪽 수·교차 확인·원본 정보 포함, docs/architecture.md)
        for r in json.loads((pd / "_rep" / "index.json").read_text(encoding="utf-8"))["docs"]:
            f = pd / "_rep" / f"{r['doc']}.json"
            if r.get("engine") and f.exists():
                reps[r["doc"]] = json.loads(f.read_text(encoding="utf-8"))
    if use_rep and all("meta" in (x.get("rep") or {}) for x in reps.values()):
        items = [(doc, {"format": x["rep"]["format"], "pages": x["rep"].get("pages")}) for doc, x in sorted(reps.items())]
        meta_docs = {doc: x["rep"]["meta"] for doc, x in reps.items()}
        route = sel = {}
    else:  # 예전 대표 결과·단계 1 실험: qa.json·엔진별 결과에서
        qa = json.loads((pd / "qa.json").read_text(encoding="utf-8"))
        items = sorted(qa["docs"].items())
        route = json.loads((pd / "route.json").read_text(encoding="utf-8")) if (pd / "route.json").exists() else {}
        sel = json.loads((pd / "selection.json").read_text(encoding="utf-8")) if (pd / "selection.json").exists() else {}
        from pipeline.transform.represent.crosscheck import build  # 실험 경로(--no-rep·예전 대표 결과)만 — 기본 경로는 _rep의 rep.meta

        meta_docs = build(a.parse_dir, a.src)  # 교차 확인 (라벨, 값)
    src = Path(a.src)
    n_fig_dropped = 0  # AD21③ — 빈 VLM 그림은 청크를 만들지 않음

    # EDW 파일 메타(고객·원천 칸·등록 시각)는 적재가 EDW 조인으로 채운다(pl-29, 11-02 — 외부 file_meta 파일 지움)
    # rdb:csv 배치 — prepared 파일명 → 원본 s3_key 매핑 (source.py가 남긴 manifest.jsonl)
    _manifest_keys = {}
    _mf = Path(a.parse_dir) / "_source" / "manifest.jsonl"
    if _mf.exists():
        for line in _mf.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("file_name") and r.get("key"):
                    _manifest_keys[r["file_name"]] = r["key"]
    docs, chunks, n_sum, seen_sha = [], [], {"llm": 0, "lead": 0}, {}
    alias = {}  # 견적·주문 번호 → 같은 문서의 (교차 확인된) 계약 번호
    for md in meta_docs.values():
        con = AQ.pick(md["pairs"], AQ.CONTRACT_FIRST)
        if con:
            for p in md["pairs"]:
                if AQ.CONTRACT_RE.search(p["label"]) and " / " not in p["label"]:
                    alias[normalize_value(p["value"])] = con["value"]
    for doc, dd in items:
        if use_rep:
            raw = reps.get(doc)
            if raw is None:
                continue
            if not (src / doc).exists() and not (raw.get("rep") or {}).get("source"):
                continue  # 원본도 원본 정보(rep.source)도 없음
            eng, folder = raw["rep"]["engine"], "_rep"
        else:
            eng = pick_engine(doc, dd, sel, route)
            if not eng or not (src / doc).exists():
                continue
            raw, folder = json.loads((pd / eng / f"{doc}.json").read_text(encoding="utf-8")), eng
        text, _ = S.load_parse_doc(pd, folder, doc)
        if not text.strip():
            continue
        ab = lead_summary(text)
        n_sum["lead"] += 1
        md = meta_docs.get(doc, {})
        cl = AQ.pick(md.get("pairs", []), AQ.CLIENT_RE, AQ.SUPPLIER_RE)
        co = AQ.pick(md.get("pairs", []), AQ.CONTRACT_RE)
        cl = cl or AQ.pick(md.get("all", []), AQ.CLIENT_RE, AQ.SUPPLIER_RE)  # 교차 확인 못 하면 단일 엔진 값(meta_confirmed=False)
        co = co or AQ.pick(md.get("all", []), AQ.CONTRACT_RE)
        if not co:  # 라벨이 깨진 문서('··ID | C-MRH-2023-02') — 'ID·번호'로 끝나는 라벨의 값이 제목에도 있으면 계약 번호
            head = T.norm(text[:200])
            co = next(
                (
                    {**p, "src": "head"}
                    for p in md.get("all", [])
                    if re.search(r"(id|번호|no\.?)\s*$", p["label"].strip(), re.I)
                    and len(T.norm(p["value"])) >= 6
                    and T.norm(p["value"]) in head
                ),
                None,
            )
        if co and not T.ID_LIKE.fullmatch(co["value"].strip()):
            co = None  # ID 모양이 아닌 값('3'·'Question')은 계약 번호로 쓰지 않음
        if co and normalize_value(co["value"]) in alias:
            co = {**co, "value": alias[normalize_value(co["value"])]}
        # 원본이 이 서버에 있으면 원본에서, 없으면 파싱 모듈이 남긴 원본 정보(rep.source)에서 — 구조화 모듈 분리(docs/architecture.md)
        orig = (src / doc) if (src / doc).exists() else None
        so = (raw.get("rep") or {}).get("source") or {}
        path = (a.path_prefix.rstrip("/\\") + "/" + doc) if a.path_prefix else (str(orig.resolve()) if orig else so["path"])
        h = (
            (original_file_hash(orig) or file_hash(orig)) if orig else so["sha256"]
        )  # GH1-04 — 원본이 로컬에 있어도 회전된 바이트 대신 원본 식별(rotation.csv) 먼저
        if h in seen_sha:  # 같은 내용 다른 이름(사본) — 한 번만, 다른 경로는 aliases에
            docs[seen_sha[h]].setdefault("aliases", []).append(path)
            continue
        seen_sha[h] = len(docs)
        di = len(docs)
        uri = so.get("uri") or (path if "://" in path else Path(path).resolve().as_uri())  # 원본 위치(나중에 s3://) — 검색 결과로 돌려줌
        _s3_key = uri.split("/", 3)[-1] if uri.startswith("s3://") and uri.count("/") >= 3 else None
        if not _s3_key:  # rdb:csv 배치 — rep.source.uri가 file://이면 manifest에서 파일명으로 s3_key를 찾는다
            _s3_key = _manifest_keys.get(doc) or _manifest_keys.get(Path(path).name)
        if not _s3_key:  # PC 폴더 원천(사용자 11-02 Q4) — 원천 폴더 기준 상대 경로(`SFDC/<uuid>/<이름>` — s3_key와 같은 모양)
            _s3_key = _rel_to_source(path)
        _src_sys = None
        _seg = _s3_key.split("/", 1)[0].upper() if _s3_key else ""
        if _seg in ("SFDC", "CRMS", "LAS", "FAQ"):  # 원본 키 첫 마디 = 원천(pl-28 스키마 고르기)
            _src_sys = _seg
        elif _s3_key:
            if _s3_key.startswith(("SFDC-", "SFDC_")):
                _src_sys = "SFDC"
            elif _s3_key.startswith(("CRMS-", "CRMS_")):
                _src_sys = "CRMS"
            elif _s3_key.startswith(("las_", "LAS_")):
                _src_sys = "LAS"
        # 2026-10-20 축소 스키마 — pgvector doc에는 검색에 필요한 최소만(EDW 식별 + clients + summary).
        # clients는 main의 infer_clients(docs)가 이후에 채움(기존 흐름 그대로). file_name은 file_path에서 유도.
        docs.append(
            {
                "file_path": _s3_key
                or path,  # 11-02(pl-28) Object Storage 원본 경로 = EDW s3_key(ParsingMeta와 잇는 키) — 개발 서버 로컬 경로는 안 씀
                "doc_name": doc,  # doc_name은 번들 JSONL 로컬용(파일명) — db 적재 안 함
                "summary": ab,
                "full_text": text,  # full_text는 본문 매칭(client) 내부용 — db 적재 안 함
                "source_system": _src_sys,
                "doc_key": _s3_key or path,  # doc_key = file_path(검색 근거의 문서 키와 같은 값)
                **DM.doc_meta(doc, text),
            }
        )
        first = len(chunks)
        seq = 0
        for c in S.chunk_all({doc: text}, a.chunk, {doc: eng}):
            m = c["meta"]
            bbox = None
            if raw.get("boxes"):
                bbox = ocr_bbox(raw["boxes"], text, m["span"])
            elif dd["format"] == ".pdf_text" and orig:  # 글자 PDF 위치는 원본에서 찾음 — 원본이 없으면 비워 둠
                bbox = pdf_bbox(str(orig), m["page"] or 1, c["text"])
            toks = tokens(c["text"])
            chunks.append(
                {
                    "doc": di,
                    "seq": seq,
                    "page": m["page"] or (1 if dd.get("pages") == 1 else None),  # 한 쪽짜리 문서는 1
                    "line_start": m["line"],
                    "line_end": m["line_end"],
                    "char_start": m["span"][0],
                    "char_end": m["span"][1],
                    "bbox": bbox,
                    "section": m["section"],
                    "chunk_text": c["text"],
                    "n_chars": len(c["text"]),
                    "n_terms": len(toks),
                    "source_system": _src_sys,
                }
            )
            seq += 1
        doc_text_chunks = chunks[first : len(chunks)]  # 이 문서의 텍스트 청크(그림 청크 추가 전) — 빈 그림의 image_id를 붙일 자리
        page_vlm_ids = {r["image_id"] for r in fig_by_doc.get(doc, []) if r.get("skipped") == "page_vlm"}
        for rec in fig_by_doc.get(doc, []):  # L1: 그림 1개 = 청크 1개(자르지 않음) — 텍스트 청크 뒤 이어서
            if fig_page_child(rec, page_vlm_ids) or fig_empty(rec):  # AD21③ 빈 VLM · F11 쪽 VLM과 중복
                n_fig_dropped += 1
                host = fig_host(doc_text_chunks, rec.get("page"))
                if host is not None:  # 원본 이미지 조회(get_image)용 image_id 연결은 문서/쪽 청크에 남김
                    host.setdefault("image_ids", []).append(rec["image_id"])
                seq += 1  # 독립 검토 MAJOR① — 빠진 그림도 seq를 소비(건너뛴 번호) → 남은 청크의
                continue  #   chunk_key(doc_sha:seq)가 어느 그림이 비었는지와 무관하게 항상 같음(결정성)
            chunks.append(figure_chunk(di, seq, rec, source_system=_src_sys))
            seq += 1
    canon_clients(docs)
    infer_clients(docs)
    warn_if_no_client_roster(docs)
    added = collect_draft_terms(docs)  # SI43④ — 새 회사 이름 후보를 glossary draft로(약한 BM25만)
    if added:
        print(f"[bundle] 새 회사 이름 후보 {len(added)}건을 용어집 draft로 추가(사람 승인 전): {', '.join(added)}", flush=True)
    for c in chunks:  # G9: 청크 머리말 [문서명 · 고객 · 절 제목] — 같은 양식 다른 고객·문서를 가름
        d = docs[c["doc"]]
        c["head"] = "[" + " · ".join(x for x in (Path(d["doc_name"]).stem, d.get("client"), c.get("section")) if x) + "]"
        c["n_terms"] = len(tokens(index_text(c)))
    final = Path(a.out)
    out = final.with_name(
        final.name + ".tmp"
    )  # 임시 폴더에 전부 쓰고 끝나면 폴더째 바꿔 끼움 — 중간에 죽어도 벡터·청크 순서가 어긋난 묶음이 남지 않음
    import shutil

    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    vecs = embed_all(a.embed, [index_text(c) for c in chunks], out=str(out / "vectors.npy"))  # 머리말 포함(G9)
    dim = int(vecs.shape[1]) if len(vecs) else 0
    del vecs  # memmap 닫기(Windows는 열린 파일을 옮길 수 없음)
    # ponytail: kg_nodes·kg_edges는 빈 파일 — 묶음 계약(contract.check_bundle 파일 목록, 핸드오프 지문 파일)이 요구해서만 씀. 0.2.0 배치에서 목록과 함께 지움(pl-06)
    for name, rows in (("docs", docs), ("chunks", chunks), ("kg_nodes", []), ("kg_edges", [])):
        with open(out / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # S7c — meta의 embed_model은 설정 객체(common 칸 EMBED_MODEL)에서(옛 env 읽기와 같은 값: 없음 → None)
    meta = {
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stack": stack.get("name"),
        "stack_conf": stack,
        "source": "rep" if use_rep else "selected",
        "embed": a.embed,
        "embed_model": C.cfg().models.embed.model if a.embed == "api" else a.embed,
        "dim": dim,
        "chunk": a.chunk,
        "summary": n_sum,
        "docs": len(docs),
        "chunks": len(chunks),
        "engines": sorted({d.get("parse_engine") or "rep" for d in docs}),
        "bbox": sum(1 for c in chunks if c["bbox"]),
        "fig_chunks": sum(1 for c in chunks if c.get("image_id")),  # L1
        "figure_chunks_dropped": n_fig_dropped,  # AD21③
        "sec": round(time.time() - t0, 1),
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    old = final.with_name(final.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    if final.exists():
        final.rename(old)  # Linux: 검색 중인 MCP가 연 파일은 그대로 읽힘
    for i in range(5):  # Windows: 백신·색인이 방금 쓴 파일을 잠깐 잡아 rename이 거부되는 일(10-03 실측 2/126) — 잠깐 쉬고 다시
        try:
            out.rename(final)
            break
        except PermissionError:
            if i == 4:
                raise
            time.sleep(1 + i)
    shutil.rmtree(old, ignore_errors=True)
    out = final
    print(json.dumps(meta, ensure_ascii=False))
    from common.core.runlog import note

    note(f"EDW 묶음: 문서 {len(docs)} · 청크 {len(chunks)} · 차원 {meta['dim']} → {out}")


if __name__ == "__main__":
    import importlib  # 문자열 import — 층 s 파일이 setarg.py를 code_fp 의존으로 끌어오지 않게(리뷰 S9 — CLI 도우미를 고칠 때 서버 전체 재구조화 방지)

    importlib.import_module(
        "common.config.setarg"
    ).apply()  # --set 이름=값(S9 Step A — 호스트 run_docs.py 구조화가 임베딩 동시 수 등을 넘김)
    utf8_stdout()
    main()
