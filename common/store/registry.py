#!/usr/bin/env python3
"""문서 대장(doc_registry) — AD16 1단계. 파싱 파이프라인이 이미 만든 산출물(중복 확인 캐시 `output/dedup/fingerprints.jsonl`·
원본 위치 `output/parse/_source/manifest.jsonl`·처리 완료 기록 `output/parse/_source/processed*.jsonl`(SI41 — 원천별로
나뉠 수 있음, 전부 합쳐서 봄)·대표 결과 색인
`output/parse/_rep/sources.jsonl`·`index.json`)을 **읽기만** 해서 doc_key(원본 내용 sha256, common/ids.py)별로
경로·이름·크기·수정 시각(LastModified)·ETag·처음/마지막 본 날·처리 상태·판 이력을 한 표(`common/structdb.py`의
doc_registry·doc_registry_seen, 로컬 SQLite·PostgreSQL 공용 스키마)에 모은다.

이 단계는 **집계만** — 파싱이 새·바뀐·지워진 문서를 어떻게 정하는지는 하나도 안 바꾼다(그건 AD17 다음 단계).
runs.jsonl(common/runlog.py)은 실행 1건 = 1항목(시각·명령·결과)일 뿐 문서별 칸이 없어 여기서는 안 씀(의도적 — 범위 밖).

AD17① — classify(cur_row, snap, fetch_sha256=None): 원본 바이트 비교만(파싱 결과끼리 비교하는 '판' 단위 작업,
AD17②·D10은 범위 밖·다음 단계). names·size·etag·status·source·doc_id·version이 전부 같고 mtime만 다르면
'touched'(날짜만 바뀜) — ETag가 단일 파트 MD5 형식이면 그것만으로 확정, 멀티파트 등 애매하면 fetch_sha256으로
원본 바이트를 받아 doc_key(원본 전체 바이트 sha256)와 대조(D1 — dedup.py sha()·common/ids.py file_sha256()과
같은 규칙). touched는 unchanged와 달리 diff_against()의 별도 칸("touched")으로 나와 new·changed와 구분되고
apply()의 판 이력(doc_registry_seen)·재파싱(OP9 nightly_plan)·변경 보고(cli/registry.py·cli/publish_parse.py)
어디에도 들어가지 않는다(대장의 마지막 본 날·EDW 상태 열 날짜만 갱신 — apply()의 공용 upsert 경로로 이미 됨).

scan(out_dir) → {doc_key: snapshot}(파일만 읽음, DB 없음) · diff_against(db, observed) → new/changed/touched/
unchanged/deleted · apply(db, observed, diff, build_id) → upsert(new·changed만 history 추가, deleted는 쓰지 않음 —
pl-12 사용자 10-30, 옛 status='deleted'·자동 hide() 없앰) · build() = 위 셋 + commit. 결정적: 같은 out_dir 내용이면 같은
observed(딕셔너리 순서·세트 정렬 무관) · 멱등: 다시 build해도 스냅숏이 그대로면 doc_registry_seen에 새 행이
안 늘어남(last_seen·last_build만 갱신).

OP1(원천 변경·삭제 탐지, 조치는 사람) — hide(db, doc_key, by, reason)·unhide(...)·hidden_set(db) = 검색 제외 집합
(common/structdb.py REGISTRY_SCHEMA의 doc_hidden, 이력 없이 지금 상태만·감사 필드 by·reason·at). 숨김·되살리기는 모두
사람(pl-12 — 자동 hide 없앰) — unhide는 사람(cli/registry.py unhide 또는 직접 호출)만. changed는 hide하지 않음
(검색은 그대로, 사람이 재파싱 전까지 옛 내용 서빙 — OP1).
OP9(야간 증분) — nightly_plan(db, observed, reparse_keys=None) = diff_against 결과를 파싱 대상 결정으로: new(처음
보는 doc_key) + unchanged인데 아직 성공 못한(status != 'parsed', 반복 실패·'seen' 포함) doc_key는 **매일 다시**
파싱 대상(독립 검토 BLOCK 10-08 반영 — "안 바뀌었으니 건너뜀"이 실패 문서를 영영 재시도 못 하게 하던 것을 뒤집음) ·
unchanged이고 이미 성공(status=='parsed')한 doc_key는 뺌(다시 할 필요 없음) · changed는 reparse_keys에 명시된
doc_key만(기본은 전부 빠짐 — 사람 조치 전까지 자동 재파싱 안 함, OP1) · deleted는 observed에 없어 자동으로 빠짐.
try_open_db(db_path=None) = 호출자(검색·파싱)가 best-effort로 문서 대장을 열 때 공용 — DOC_REGISTRY=0이거나 연결이
안 되면 None(필터 없이 전과 동일).
재시도 횟수 상한(옛 DET1 Fix2 — fail_count·REGISTRY_RETRY_MAX)은 지웠다(사용자 10-30, pl-32): 실패 문서는 성공 기록이
없으므로 다음 실행에서 늘 다시 시도한다. 실패 이유는 로컬 로그와 EDW ParsingMeta(실패 엔진 칸 — pl-25 D-3)에 남는다.

사용(라이브러리): from common.store import registry as REG ; REG.build(out_dir, db) — CLI는 mcp_server/cli/registry_cli.py(VS3 R-6 — S3 전부터 틀린 import 글자).
DOC_REGISTRY(기본 켬, =0으로 끔) 게이트는 호출자(cli/registry.py·try_open_db) 몫 — build()·apply()·hide() 자체는
env를 보지 않는다(순수 함수 — 호출 여부만 호출자가 정함).

AD17②(10-08, 파싱 뒤 '판 비교', D10) — 위 AD17①은 원본 **바이트** 비교(파싱 전, D1)만. 바이트가 달라 새 doc_key로
관측된 문서(diff()의 "new") 중 같은 파일 이름이 "deleted"(이번엔 더는 관측 안 됨 — 같은 자리를 새 내용이 덮음)에
있으면, 그 둘의 **대표 결과(_rep, 파싱 끝난 뒤의 글)** 를 비교해 이름이 같은 문서의 '판 관계'를 정한다(대표 결과를
직접 다시 읽지 않고 doc_registry.rep_sha·rep_pairs에 미리 남겨 둔 값으로 비교 — 그 이름의 _rep 파일은 다음 파싱이
덮어써 버려서 나중엔 못 읽음, update_rep_fingerprints()가 매 build마다 "new·changed" doc_key만 새로 읽어 저장):
  · "same"(대표 글이 완전히 같음, rep_sha 동일) — 새 판·새 청크·변경 보고 없음(기록만 edition_of)
  · "changed_values"(라벨 집합은 같고 숫자 값만 다름) — 새 판으로 연결(edition_of) + 바뀐 값 목록(label·before·after·page, value_changes)
  · "different"(그 밖 — 라벨이 늘거나 줄거나 글자 값이 바뀜) — 보통 새 판(edition_of 없음)
비교는 common.core.text.normalize_value·common.core.repfmt.pairs_of/locate/nlabel/NUM_RE만 재사용 — 새 해시·새 정규화 규칙
없음. REGISTRY_EDITIONS(기본 켬, =0으로 끔) — 끄면 build()가 이 단계 전체를 안 돌려 이전 동작과 바이트 동일
(rep_sha·rep_pairs·edition_of·content_group·value_changes는 그대로 NULL).

AD15(10-08, 같은 내용 다른 형식) — 같은 내용을 다른 형식으로 받은 문서(.eml↔.msg·PDF↔Word 등, 이름도 다를 수
있음)를 doc_registry.content_group(그룹 안에서 가장 먼저 등록된 doc_key)으로 묶는다(지우거나 숨기지 않음 —
검색 중복만 줄이는 표시). ① rep_sha(정규화한 대표 본문 sha256)가 완전히 같으면 즉시 한 그룹 ② 다르면(형식이
달라 머리말 등 소소한 차이) 정규화한 본문의 5-gram 글자 Jaccard 유사도(CONTENT_GROUP_SIM)로 근접 판정 — 아직
어느 그룹에도 안 묶인 문서끼리만(전수 비교, REGISTRY_EDITIONS와 같은 스위치)."""

import json
import re
import time
from pathlib import Path

from common.config.settings import cfg

# AD17②·AD15가 쓰는 common.core.text·common.repfmt는 각 함수 안에서 지연 import(이 파일의 다른 common.* import들과
# 같은 관례 — try_open_db()·selftest()도 그 안에서 import함 — registry.py를 `python common/registry.py`로 바로
# 돌릴 때(__main__이 sys.path를 늦게 고침) 모듈 맨 위 import가 먼저 실패하지 않게).


def _jl(path):
    rows = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        if ln.strip():
            rows.append(json.loads(ln))
    return rows


def _s(v):
    """None 보존 + 그 외는 문자열로(타임존 변환 없이 원값 그대로 — 결정성)."""
    return None if v is None else str(v)


def scan(out_dir):
    """out_dir(기본 RAG_OUT·dev/out) 아래 기존 산출물을 읽어 {doc_key: snapshot} — DB·네트워크 없음.
    snapshot = {names(정렬 목록), source_keys(정렬 목록 — AD17② 재료, 아래), size, mtime, etag,
    status(seen·parsed·failed·deleted), source(local·s3·rdb), doc_id, version}.
    우선순위: ① dedup/fingerprints.jsonl(로컬·RDB·S3 전부 — cli/pipeline.py가 받은 폴더에 dedup을 돌림, name↔doc_key의
    가장 넓은 근거) → doc_key 기본 틀 ② sources.jsonl(대표 파싱 성공) → status=parsed ③ index.json(실패 문서도 포함,
    engine 없으면 failed) ④ manifest.jsonl(RDB·S3 메타 — etag·size·doc_id·version·is_deleted) + processed*.jsonl(SI41
    — 원천별로 나뉠 수 있음, 전부 합쳐서 업로드 완료 확인, 아직 상태가 없을 때만 parsed로 보강) 순으로 덮어씀(뒤
    단계가 더 구체적인 정보).
    source_keys(engine-qa MAJOR 10-08, AD17②) — "names"는 **파일 이름만**(폴더·버킷 경로가 빠짐)이라 다른 고객·
    폴더의 같은 이름 파일을 구분 못 한다. `f"{source_system}::{원본 전체 키·경로}"` 형식 문자열 집합(SI39의 겹침
    키 (source_system, source_key)와 같은 모양, `modules/load/parsing_meta.py KEY` 참고) — link_editions()가
    이 칸으로만 전 판을 찾는다(이름은 안 봄). **딱 두 곳에서만** 채운다(둘 다 전체 경로·키가 보장되는 원천):
    로컬은 `local::<전체 경로>`(dedup fingerprints의 "path") · S3·RDB는 manifest.jsonl의 `key`(원본 전체 키) +
    `source_system`(SI41, 없으면 d["source"] 카테고리로 대체). sources.jsonl의 `uri`는 **일부러 안 쓴다** —
    `SOURCE_URI_PREFIX`(common/ids.py source_uri())가 걸리면 그 값이 파일 이름만으로 조립돼 베이스네임과 같은
    오탐 위험이 되돌아온다(engine-qa 2차 검토로 발견). manifest가 아예 없는 산출물(시험 더미 등)은 쌓이는 정보가
    없어 빈 집합일 수 있음(그런 경우 link_editions는 안전하게 "연결 안 함"으로 처리 — 이름만으로 다시 잇지 않음)."""
    out_dir = Path(out_dir)
    observed = {}

    def touch(key):
        return observed.setdefault(
            key,
            {
                "names": set(),
                "source_keys": set(),
                "size": None,
                "mtime": None,
                "etag": None,
                "status": "seen",
                "source": None,
                "doc_id": None,
                "version": None,
            },
        )

    name_to_key = {}

    fp = out_dir / "dedup" / "fingerprints.jsonl"
    if fp.exists():
        for r in _jl(fp):
            key, name = r["sha"], Path(r["path"]).name
            name_to_key.setdefault(name, key)
            d = touch(key)
            d["names"].add(name)
            d["source_keys"].add(f"local::{r['path']}")  # 전체 경로(이름만이 아님) — 다른 폴더 같은 이름 구분
            if d["size"] is None:
                d["size"] = r.get("size")
            if d["mtime"] is None:
                d["mtime"] = _s(r.get("mtime"))
            d["source"] = d["source"] or "local"

    src_f = out_dir / "parse" / "_rep" / "sources.jsonl"
    if src_f.exists():
        for r in _jl(src_f):
            key = r["doc_key"]
            name_to_key.setdefault(r["file_name"], key)
            d = touch(key)
            d["names"].add(r["file_name"])
            d["status"] = "parsed"
            if d["source"] is None or d["source"] == "local":
                d["source"] = "s3" if str(r.get("uri") or "").startswith("s3://") else (d["source"] or "local")
            # source_keys는 여기서 안 채움(engine-qa 2차 반영) — 이 uri는 SOURCE_URI_PREFIX가 걸리면 파일 이름만으로
            # 조립돼(common/ids.py source_uri()) 베이스네임과 같은 오탐 위험(다른 폴더가 같은 키로 보임)이 되돌아온다.
            # 전체 경로가 보장되는 fingerprints("path")·manifest("key")만 쓴다(위 scan() 설명).

    idx_f = out_dir / "parse" / "_rep" / "index.json"
    if idx_f.exists():
        for r in json.loads(idx_f.read_text(encoding="utf-8")).get("docs") or []:
            key = r.get("doc_key") or name_to_key.get(r["doc"])
            if not key:
                continue  # 실패 문서인데 dedup·sources 어느 쪽에서도 doc_key를 못 찾음(둘 다 안 돌린 시험 산출물) — 건너뜀
            name_to_key.setdefault(r["doc"], key)
            d = touch(key)
            d["names"].add(r["doc"])
            if not r.get("engine") and d["status"] != "parsed":
                d["status"] = "failed"

    src_dir = out_dir / "parse" / "_source"
    man_f = src_dir / "manifest.jsonl"
    by_name = {r["file_name"]: r for r in _jl(man_f)} if man_f.exists() else {}
    done_object_keys = set()  # SI41 — processed.jsonl(레거시) + processed__<원천 이름>.jsonl(sources.json) 전부 합침
    if src_dir.exists():
        for proc_f in sorted(src_dir.glob("processed*.jsonl")):
            done_object_keys |= {r["key"] for r in _jl(proc_f)}
    for name, r in by_name.items():
        key = name_to_key.get(name)
        if not key:
            continue  # 아직 대표 파싱·중복 확인을 거치지 않은 원본(받기만 한 상태) — doc_key가 아예 없어 등록 못 함(다음 build가 채움)
        d = touch(key)
        d["names"].add(name)
        if r.get("etag"):
            d["etag"] = r["etag"]
        if r.get("size") is not None:
            d["size"] = r["size"]
        if r.get("updated_at") is not None:
            d["mtime"] = _s(r["updated_at"])
        if r.get("doc_id"):
            d["doc_id"] = _s(r["doc_id"])
        ver = r.get("version") or r.get("content_version_id")
        if ver:
            d["version"] = _s(ver)
        d["source"] = (
            "rdb" if r.get("doc_id") else "s3"
        )  # rdb: 질의(AD44)만 manifest에 doc_id를 적음(source.py _rdb_rows) — 그 밖 Object Storage는 s3
        # SI39 겹침 키(source_system, source_key)와 같은 모양 — manifest가 가장 구체적인 원본 전체 키(경로 포함) 정보
        d["source_keys"].add(f"{r.get('source_system') or d['source']}::{r.get('key') or name}")
        # pl-12(사용자 10-30) — 원천의 is_deleted도 status='deleted'로 바꾸지 않음(문서 대장은 deleted를 쓰지 않음 · 검색은 manifest is_deleted로 거름)
        if d["status"] == "seen" and r.get("key") in done_object_keys:
            d["status"] = "parsed"  # 대표 결과 산출물이 이미 지워졌어도(X2) 처리 완료 기록으로 보강

    for d in observed.values():
        d["names"] = sorted(d["names"])
        d["source_keys"] = sorted(d["source_keys"])
    return observed


_SNAP_COLS = ("size", "mtime", "etag", "status", "source", "doc_id", "version")

_MD5_ETAG_RE = re.compile(r"^[0-9a-f]{32}$", re.I)


def _is_md5_etag(etag):
    """ETag가 단일 파트 업로드 MD5 형식(32자 16진수)인지 — 보통은 같으면 원본 바이트가 같다고 믿을 수 있다.
    멀티파트 업로드 ETag(`<hash>-<파트수>` 등 대시 포함 형식)는 같아도 원본 바이트가 같다는 보장이 없어
    (AWS 멀티파트 ETag는 파트 해시들의 해시라 같은 내용도 업로드 방식이 다르면 값이 달라진다) sha256을 직접
    받아 대조해야 한다(D1 — dedup.py sha()·common/ids.py file_sha256()과 같은 전체 바이트 sha256 규칙).
    **한계(engine-qa 독립 검토 10-08)**: SSE-KMS·SSE-C로 서버 쪽 암호화된 버킷은 ETag가 내용 MD5가 아닌데도
    32자 16진수 형식일 수 있다(암호화 메타가 끼어든 해시) — 형식만으로는 그 버킷이 진짜 단일 파트 MD5인지
    구분할 수 없다. 그런 버킷은 `REGISTRY_ETAG_MD5=0`으로 이 형식 지름길을 끄고 fetch_sha256 대조만 쓴다
    (classify() 참고)."""
    return bool(etag) and bool(_MD5_ETAG_RE.match(str(etag).strip().strip('"')))


def _etag_md5_trusted():
    """REGISTRY_ETAG_MD5(기본 켬, =0으로 끔) — 0이면 ETag가 32자 16진수(MD5 형식)여도 그것만으로 touched를
    확정하지 않고 항상 fetch_sha256으로 원본 바이트를 대조한다(없으면 changed로 보수적 처리). SSE-KMS·SSE-C
    암호화 버킷처럼 ETag 형식이 MD5와 똑같아도 실제로는 MD5가 아닐 수 있는 원천을 쓸 때 끈다(_is_md5_etag()
    한계 — env-guide.md §3)."""
    return bool(cfg().store.registry_etag_md5)  # S7b — 설정 객체(켜기 칸 — 옛 판정 꼴 off=("", "0", "none", "false"), 기본 켬)


def classify(cur_row, snap, fetch_sha256=None):
    """AD17① — 파싱 전(D1) 원본 바이트 비교만(파싱 결과끼리 비교하는 '판' 단위 작업은 범위 밖, 다음 단계).
    cur_row(기존 doc_registry 행)와 snap(이번 scan 관측) 비교 → "same"(아무것도 안 바뀜) ·
    "touched"(날짜만 바뀜 — 원본 바이트는 같음, 재파싱·새 판·변경 보고 모두 제외) ·
    "changed"(원본 바이트가 다름, 또는 같은지 확인할 수 없어 안전 쪽으로 다름 취급).
    판정: names·size·etag·status·source·doc_id·version 중 mtime 말고 하나라도 다르면 changed(이 필드들은 원본이
    실제로 바뀌었거나 처리 상태가 바뀐 신호 — 터치 여부와 무관, 손대지 않음). 그 전부가 같고 mtime만 다르면
    원본 바이트 동일 여부만 본다: `REGISTRY_ETAG_MD5`(기본 켬)이고 ETag가 단일 파트 MD5 형식이면 touched로
    확정 · 그 밖(멀티파트 등 애매한 ETag, 또는 REGISTRY_ETAG_MD5=0으로 형식 지름길을 끈 경우)은
    fetch_sha256(cur_row)로 원본 바이트를 받아 sha256을 doc_key(= 원본 전체 바이트 sha256, 처음 등록 때 값)와
    대조 — 같으면 touched, 다르거나 fetch_sha256이 없어 확인할 수 없으면 changed(검증 전에 touched로 단정하지
    않음 — rules/code.md)."""
    if cur_row.get("names") != json.dumps(snap["names"], ensure_ascii=False):
        return "changed"
    other_cols = [c for c in _SNAP_COLS if c != "mtime"]
    if any(cur_row.get(c) != snap[c] for c in other_cols):
        return "changed"
    if cur_row.get("mtime") == snap["mtime"]:
        return "same"
    if _etag_md5_trusted() and _is_md5_etag(snap.get("etag")):
        return "touched"
    if fetch_sha256 is None:
        return "changed"
    try:
        actual = fetch_sha256(cur_row)
    except Exception:
        return "changed"
    return "touched" if actual == cur_row.get("doc_key") else "changed"


def diff_against(db, observed, fetch_sha256=None):
    """지금 doc_registry(DB) 상태와 observed(이번 scan) 비교 →
    {new, changed, touched, unchanged, deleted}(doc_key 정렬 목록).
    touched(AD17①) = 원본 바이트는 같고 날짜만 바뀜 — new·changed와 달리 재파싱·새 판·변경 보고 대상이 아니다
    (apply()의 판 이력 추가·report의 '바뀜' 목록 모두 changed만 봄). deleted = 전에는 있었는데 이번 관측에 없고
    아직 status='deleted'로 표시되지 않은 것(쓰기는 안 함 — apply() 몫). fetch_sha256(선택) = classify()에 그대로
    전달(멀티파트 ETag처럼 애매할 때만 호출됨, 없으면 그 경우 changed로 보수적 처리)."""
    current = {r["doc_key"]: r for r in db.query("SELECT * FROM doc_registry")}
    new, changed, touched, unchanged = [], [], [], []
    for key in sorted(observed):
        cur = current.get(key)
        if cur is None:
            new.append(key)
            continue
        verdict = classify(cur, observed[key], fetch_sha256=fetch_sha256)
        if verdict == "changed":
            changed.append(key)
        elif verdict == "touched":
            touched.append(key)
        else:
            unchanged.append(key)
    deleted = sorted(k for k in current if k not in observed and current[k].get("status") != "deleted")
    return {"new": new, "changed": changed, "touched": touched, "unchanged": unchanged, "deleted": deleted}


def apply(db, observed, diff, build_id, seen_at=None):
    """diff에 따라 doc_registry를 upsert하고(모든 관측 doc_key), new·changed만 doc_registry_seen에 한 행 추가
    (판 이력 — 바뀔 때만). unchanged·touched(AD17① — 원본 바이트는 같고 날짜만 바뀜)는 last_seen·last_build·
    mtime만 갱신, 이력 행은 안 늘어남(멱등 — touched는 새 판·변경 보고 대상이 아니라 changed_keys에 안 들어감).
    pl-12(사용자 10-30) — diff["deleted"]는 쓰지 않는다(옛 OP1의 status='deleted'·자동 hide() 없앰 — 숨김은 사람이 hide()로만).
    status는 관측 그대로(seen·parsed·failed) — 성공(parsed)만 "끝남"이라 실패 문서는 nightly_plan()이 늘 다시 고른다
    (재시도 횟수 칸 fail_count는 쓰지 않음 — 사용자 10-30, pl-32 · 칸 자체는 0.1.0 마이그레이션이 지움)."""
    seen_at = seen_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    changed_keys = set(diff["new"]) | set(diff["changed"])
    for key in sorted(observed):
        snap = observed[key]
        names_json = json.dumps(snap["names"], ensure_ascii=False)
        source_keys_json = json.dumps(snap.get("source_keys") or [], ensure_ascii=False)  # AD17② engine-qa MAJOR — names와
        # 같은 관측 칸(매 build 그대로 씀, 보존 불필요)
        prev = db.query(
            "SELECT first_seen, rep_sha, rep_pairs, edition_of, content_group, value_changes FROM doc_registry WHERE doc_key=?",
            (key,),
        )
        first_seen = prev[0]["first_seen"] if prev else seen_at
        keep = prev[0] if prev else {}  # AD17②·AD15 — INSERT OR REPLACE는 열 목록 밖 칸을 지운다(SQLite는 행째
        # 바꿔치기) — update_rep_fingerprints()·link_editions()·content_groups()가
        # 이 build에서 바뀐 doc_key만 새로 덮어쓸 때까지 기존 값을 그대로 들고 간다.
        db.execute(
            """INSERT OR REPLACE INTO doc_registry
                      (doc_key, names, size, mtime, etag, status, source, doc_id, version, first_seen, last_seen, last_build,
                       rep_sha, rep_pairs, edition_of, content_group, value_changes, source_keys)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                key,
                names_json,
                snap["size"],
                snap["mtime"],
                snap["etag"],
                snap["status"],
                snap["source"],
                snap["doc_id"],
                snap["version"],
                first_seen,
                seen_at,
                build_id,
                keep.get("rep_sha"),
                keep.get("rep_pairs"),
                keep.get("edition_of"),
                keep.get("content_group"),
                keep.get("value_changes"),
                source_keys_json,
            ),
        )
        if key in changed_keys:
            db.execute(
                """INSERT INTO doc_registry_seen (doc_key, build_id, names, size, mtime, etag, status, source, seen_at)
                          VALUES (?,?,?,?,?,?,?,?,?)""",
                (key, build_id, names_json, snap["size"], snap["mtime"], snap["etag"], snap["status"], snap["source"], seen_at),
            )
    # pl-12(사용자 10-30): diff["deleted"](이번 관측에 없음)는 쓰지 않는다 — status='deleted'·자동 hide() 길 없앰
    # (관측이 일부만 보여도 다른 문서를 지우던 위험). diff["deleted"]는 판 잇기(link_editions)용 정보로만 남는다.


# ── AD17②·AD15(10-08, 파싱 뒤 '판 비교') — 모듈 docstring 참고 ───────────────
def editions_on():
    """REGISTRY_EDITIONS(기본 켬, =0으로 끔) — 끄면 build()가 update_rep_fingerprints·link_editions·content_groups를
    안 불러 이전 동작과 바이트 동일(새 칸은 그대로 NULL)."""
    return bool(cfg().store.registry_editions)  # S7b — 설정 객체(켜기 칸, 기본 켬)


def _load_rep(out_dir, name):
    """대표 결과(modules/parse/represent.py가 `out_dir/parse/_rep/<name>.json`에 씀, name = 관측한 파일 이름
    그대로 — represent.py의 "doc" 키와 같은 값) — 없거나 못 읽으면 None(아직 파싱 전·실패)."""
    f = Path(out_dir) / "parse" / "_rep" / f"{name}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _rep_pairs(rep):
    """그 대표 결과의 (라벨, 값, 쪽, 등장 순번) 목록 — common.core.repfmt.pairs_of(라벨:값 줄 + 표)·locate(쪽 찾기)만
    재사용. doc_registry.rep_pairs에 저장해 두면 이 _rep 파일이 나중에(같은 이름 재파싱으로) 덮여도 '이전 판'과
    비교할 수 있다(AD17②).
    engine-qa MAJOR(10-08) 반영 — 라벨만으로 중복 제거하면(첫 값만 남김) 견적서처럼 '단가'·'수량'이 품목마다
    반복되는 표에서 두 번째 이후 행의 값 변화가 통째로 사라져(두 판 다 '그 라벨의 첫 값'만 비교) 실제로는 바뀐
    값이 있는데 'same'으로 오판할 수 있다 — 라벨을 지우는 대신 각 pairs_of 등장을 **(정규화 라벨, 그 라벨의
    등장 순번)**으로 구분해 전부 들고 간다("seq"). _edition_verdict()가 이 키로 양쪽을 맞춰 비교한다."""
    from common.core.repfmt import locate, nlabel, pairs_of

    text = rep.get("text") or ""
    out, seq = [], {}
    for label, value in pairs_of({"text": text, "facts": rep.get("facts") or []}):
        if not value:
            continue
        key = nlabel(label)
        n = seq.get(key, 0)
        seq[key] = n + 1
        idx = text.find(value)
        page = locate(text, idx, idx + len(value))["page"] if idx >= 0 else None
        out.append({"label": label, "value": value, "page": page, "seq": n})
    return out


def update_rep_fingerprints(db, out_dir, diff):
    """AD17②·AD15 재료 — 이번 build에서 대표 결과가 새로(또는 다시) 생겼을 doc_key(diff["new"]·diff["changed"]
    만 — unchanged·touched는 대표 결과가 그대로이므로 다시 읽을 필요 없음)만 _rep/<이름>.json을 읽어 rep_sha
    (정규화한 본문 sha256, common.core.text.normalize_value 재사용 — 새 해시 규칙 아님)·rep_pairs(_rep_pairs())를
    doc_registry에 적어 둔다. 대표 결과가 없으면(실패 문서 등) 손대지 않음(그대로 NULL)."""
    import hashlib

    from common.core.text import normalize_value

    keys = set(diff.get("new") or ()) | set(diff.get("changed") or ())
    if not keys:
        return
    rows = {r["doc_key"]: r for r in db.query("SELECT doc_key, names FROM doc_registry")}
    for key in keys:
        row = rows.get(key)
        if not row:
            continue
        rep = None
        for n in json.loads(row.get("names") or "[]"):
            rep = _load_rep(out_dir, n)
            if rep is not None:
                break
        if rep is None:
            continue
        sha = hashlib.sha256(normalize_value(rep.get("text") or "").encode("utf-8")).hexdigest()
        pairs = _rep_pairs(rep)
        db.execute("UPDATE doc_registry SET rep_sha=?, rep_pairs=? WHERE doc_key=?", (sha, json.dumps(pairs, ensure_ascii=False), key))


def _edition_verdict(prev_row, row):
    """AD17② — prev_row(전 판)·row(이번 build의 새 doc_key 행) 비교(둘 다 doc_registry 행, rep_sha·rep_pairs 열
    필요) → (edition, value_changes). rep_sha가 같으면 'same'(대표 글이 완전히 같음 — 새 판 아님) · 다르면
    rep_pairs를 (정규화 라벨, 등장 순번) 키로 맞춰(_rep_pairs — 반복 라벨도 행마다 구분) 키 집합이 같은지 본다:
    다르면(늘거나 줄면) 'different'(글이 달라짐) · 같으면 값을 비교해 **전부 숫자끼리만** 다르면
    (repfmt.NUM_RE.fullmatch — 전체가 숫자 모양일 때만, 'A-2024'처럼 글자가 섞인 값은 숫자로 안 침)
    'changed_values'(바뀐 값 목록) · 숫자가 아닌 값도 하나라도 다르면 'different'(바뀐 값 목록은 버림 — 글
    자체가 바뀐 판이라 "숫자만 바뀜" 주장이 틀림). 비교 재료가 없으면(대표 결과 자체가 없어 rep_sha가 NULL)
    안전 쪽으로 'different'(검증 전 'same' 단정 안 함).
    engine-qa MAJOR(10-08) 반영 — rep_sha가 **다른데** 추적한 (라벨,순번) 쌍 전부가 값까지 똑같아 보이는 경우
    (추적 못 하는 본문 변화 — 자유 문장 변경 등)는 'same'으로 단정하지 않고 'different'로 보낸다(안전 쪽,
    rep_sha 불일치라는 실제 신호를 "값 비교 재료가 부족해서"로 덮어 놓치면 안 됨 — 바이트가 다르다고 판정된
    두 판을 재료 부족으로 '같다'고 기록하는 게 더 위험하다)."""
    from common.core.repfmt import NUM_RE, nlabel
    from common.core.text import normalize_value

    if not prev_row.get("rep_sha") or not row.get("rep_sha"):
        return "different", []
    if prev_row["rep_sha"] == row["rep_sha"]:
        return "same", []
    try:
        prev_pairs = json.loads(prev_row.get("rep_pairs") or "[]")
        new_pairs = json.loads(row.get("rep_pairs") or "[]")
    except ValueError:
        return "different", []

    def pkey(p):
        return (nlabel(p["label"]), p.get("seq", 0))  # 반복 라벨(견적서 품목별 단가 등)도 등장 순서로 구분

    prev_by_key = {pkey(p): p["value"] for p in prev_pairs}
    new_by_key = {pkey(p): p for p in new_pairs}
    if not prev_by_key or set(prev_by_key) != set(new_by_key):
        return "different", []  # 라벨:값 구조가 없거나(비교 재료 없음) (라벨,순번) 집합이 다름 — 안전 쪽(단정 안 함)
    changes, text_changed = [], False
    for key, p in new_by_key.items():
        old_v = prev_by_key.get(key)
        if old_v is None or normalize_value(old_v) == normalize_value(p["value"]):
            continue
        if NUM_RE.fullmatch(str(old_v).strip()) and NUM_RE.fullmatch(str(p["value"]).strip()):
            changes.append({"label": p["label"], "before": old_v, "after": p["value"], "page": p.get("page")})
        else:
            text_changed = True
    if text_changed:
        return "different", []
    if not changes:
        # rep_sha는 다른데 추적한 (라벨,순번) 쌍은 전부 같음 — 추적 못 하는 본문(자유 문장 등)이 바뀐 경우라
        # "같은 판"으로 단정하지 않는다(engine-qa MAJOR — 이전엔 여기서 'same'을 돌려줬다, 안전 쪽으로 변경).
        return "different", []
    return "changed_values", changes


def link_editions(db, diff):
    """AD17② — diff["new"]인 doc_key 중 **같은 원천 키**(source_system + 원본 전체 키·경로, SI39 겹침 키와 같은
    모양·scan()의 source_keys)의 전 판이 diff["deleted"]에 있으면(원본 바이트가 바뀌어 새 doc_key가 됐지만 같은
    자리의 같은 문서) _edition_verdict()로 판 관계를 정해 doc_registry.edition_of·value_changes에 기록한다
    (update_rep_fingerprints()가 이미 이번 build의 rep_sha·rep_pairs를 채워 둔 뒤에 불러야 함). → {new_doc_key:
    edition 문자열}(로그·보고용 — "same"·"changed_values"일 때만 DB에 기록, "different"는 기록 안 함 — 보통 새 판 그대로).
    engine-qa MAJOR(10-08) 반영 — 전엔 파일 **이름**(names, 폴더·버킷 경로 없음)만으로 짝을 찾아 다른 고객·폴더의
    같은 이름 파일(예: customerA/report.pdf ↔ customerB/report.pdf)이 엉뚱하게 이어질 수 있었다. 이제는 이름이
    아니라 source_keys(전체 경로·키 포함)로만 짝을 찾는다 — source_keys가 하나도 안 겹치면(원천 메타가 전혀
    없는 시험 산출물 포함) 연결하지 않는다(이름만으로 다시 잇지 않음 — 안전 쪽)."""
    current = {r["doc_key"]: r for r in db.query("SELECT * FROM doc_registry")}
    deleted_by_key = {}
    for key in diff.get("deleted") or ():
        row = current.get(key)
        if not row:
            continue
        for sk in json.loads(row.get("source_keys") or "[]"):
            deleted_by_key.setdefault(sk, key)
    result = {}
    for key in diff.get("new") or ():
        row = current.get(key)
        if not row:
            continue
        source_keys = json.loads(row.get("source_keys") or "[]")
        prev_key = next((deleted_by_key[sk] for sk in source_keys if sk in deleted_by_key), None)
        if not prev_key or prev_key == key or prev_key not in current:
            continue
        edition, changes = _edition_verdict(current[prev_key], row)
        result[key] = edition
        if edition in ("same", "changed_values"):
            db.execute(
                "UPDATE doc_registry SET edition_of=?, value_changes=? WHERE doc_key=?",
                (prev_key, json.dumps(changes, ensure_ascii=False) if changes else None, key),
            )
    return result


CONTENT_GROUP_SIM = 0.6  # AD15 — 5-gram 글자 Jaccard 문턱(형식만 다른 같은 내용 판단) — modules/parse/represent.py의
# HIDDEN_AGREE_MIN(2-gram·숨은 글자층 전용)과 같은 값을 재사용(새 기준을 또 만들지 않음).
CONTENT_GROUP_MIN_LEN = 40  # 너무 짧은 본문은 우연히 겹칠 수 있어 비교하지 않음(판단 불가 — 안 묶는 쪽이 안전).
# engine-qa MINOR(10-08) — 이 문턱(0.6)은 '글자가 비슷하다'만 본다: 같은 양식(표준 계약서 템플릿)을 쓴 **다른**
# 계약서는 본문 대부분(조항 문구)이 같고 엔티티(이름·날짜·계약번호·금액)만 달라 5-gram 유사도가 쉽게 0.6을
# 넘을 수 있다 — content_group을 "검색 중복 제거"(같은 결과를 하나로 줄이기)에 실제로 쓰기 전에는 그룹 멤버의
# 핵심 엔티티(고객명·날짜·계약 번호 등, rep_pairs나 구조화 결과로 확인)가 실제로 같은지 반드시 먼저 대조해야
# 한다 — 지금 이 함수는 '후보 묶음'만 만들 뿐, 그 확인은 아직 하지 않는다(다음 단계, backlog AD15 행에도 기록).


def _ngrams5(text):
    from common.core.text import normalize_value

    s = normalize_value(text)
    return {s[i : i + 5] for i in range(len(s) - 4)} if len(s) >= 5 else set()


def content_groups(db, out_dir):
    """AD15 — doc_registry 중 대표 결과가 있고(rep_sha not null) 숨김 처리되지 않은(status != 'deleted') doc_key끼리
    '같은 내용 다른 형식' 묶음을 찾아 content_group(그룹 안에서 가장 먼저 등록된 doc_key, first_seen 오름차순 —
    결정적)에 기록한다. ① rep_sha 완전 일치(이미 doc_registry에 저장된 값만 써서 파일을 다시 안 읅음) ② 아직
    못 묶인 것들만 대표 결과를 다시 읽어 5-gram 유사도(CONTENT_GROUP_SIM 이상)로 근접 판정.
    ponytail: ②는 전수(O(n²)) 비교 — 문서 수가 수천+로 늘면 크기 버킷으로 좁히는 게 다음 단계(지금 규모에선
    불필요). 한번 묶인 그룹 id는 그대로 유지(지우지 않음 — 다음 build가 새 멤버를 더할 뿐 기존 묶음을 안 풂)."""
    from common.core.text import normalize_value

    rows = db.query(
        "SELECT doc_key, rep_sha, names, first_seen FROM doc_registry "
        "WHERE rep_sha IS NOT NULL AND status != 'deleted' ORDER BY first_seen, doc_key"
    )
    by_sha = {}
    for r in rows:
        by_sha.setdefault(r["rep_sha"], []).append(r["doc_key"])
    groups = {}
    for keys in by_sha.values():
        if len(keys) < 2:
            continue
        gid = keys[0]  # rows가 first_seen,doc_key 순이라 keys[0]이 가장 먼저 등록된 doc_key
        for k in keys:
            groups[k] = gid
    texts = {}
    for r in rows:
        if r["doc_key"] in groups:
            continue
        rep = None
        for n in json.loads(r["names"] or "[]"):
            rep = _load_rep(out_dir, n)
            if rep is not None:
                break
        if rep is None:
            continue
        t = rep.get("text") or ""
        if len(normalize_value(t)) >= CONTENT_GROUP_MIN_LEN:
            texts[r["doc_key"]] = _ngrams5(t)  # rows 순서 그대로(first_seen,doc_key) — 아래 비교에서 앞선 것이 그룹 id
    keys_list = list(texts)
    for i, a in enumerate(keys_list):
        if a in groups:
            continue
        for b in keys_list[i + 1 :]:
            if b in groups or not texts[a] or not texts[b]:
                continue
            sim = len(texts[a] & texts[b]) / len(texts[a] | texts[b])
            if sim >= CONTENT_GROUP_SIM:
                gid = groups.get(a, a)
                groups[a] = gid
                groups[b] = gid
    for k, gid in groups.items():
        db.execute("UPDATE doc_registry SET content_group=? WHERE doc_key=?", (gid, k))


# ── OP1 — 숨김·복구(검색 제외, 색인 행 삭제 없음) ───────────────────────
def hide(db, doc_key, by, reason=None, at=None):
    """검색에서 뺄 문서(원천에서 사라짐·사람 판단 등) — doc_hidden에 지금 상태만 upsert(누가·언제·왜 기록, 이력은
    안 쌓음 — ponytail 주석, structdb.REGISTRY_SCHEMA). ensure_registry_schema(db)가 먼저 돌아 있어야 함."""
    at = at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    db.execute("INSERT OR REPLACE INTO doc_hidden (doc_key, hidden, reason, by, at) VALUES (?,?,?,?,?)", (doc_key, 1, reason, by, at))


def try_open_db(db_path=None):
    """OP1/OP9 — 숨김 집합·증분 판단에 쓸 문서 대장 연결을 best-effort로. DOC_REGISTRY(기본 켬, =0으로 끔)이거나
    연결이 안 되면 None(호출자는 필터 없이 그대로 — 바이트 동일, 검색·파싱을 막지 않음)."""
    if not cfg().store.doc_registry:  # S7b — 설정 객체(켜기 칸, 기본 켬)
        return None
    from common.config.settings import guard_run_env
    from common.store.structdb import StructDBError, open_backend

    try:
        return open_backend(db_path)
    except StructDBError:
        if guard_run_env() not in (None, "local"):
            raise  # pl-12 — 서버의 거부(SQLite 대체 금지)는 삼키지 않음
        return None
    except Exception:
        return None


def nightly_plan(db, observed, reparse_keys=None, fetch_sha256=None):
    """OP9 — 야간 증분(독립 검토 BLOCK 반영, 10-08: "안 바뀌었으니 건너뜀"이 실패 문서를 영영 재시도 못 하게
    했던 것을 뒤집음). parse_names에 넣는 것 = ① new(처음 보는 doc_key) ② unchanged·touched(AD17① — 원본
    바이트는 같고 날짜만 바뀜)인데 **아직 성공 못한** doc_key(status != 'parsed' — 반복 실패·아직 파싱 전
    'seen' 포함, 매일 밤 재시도 대상) ③ changed인데 reparse_keys에 명시된 doc_key(사람이 승인한 재파싱, OP1).
    **뺀 것** = changed인데 reparse_keys에 없는 doc_key(사람 조치 전까지 옛 내용 그대로 서빙, 자동 재파싱 안 함,
    OP1) · unchanged·touched이고 이미 성공한(status=='parsed') doc_key(다시 할 필요 없음 — touched는 원본
    바이트가 안 바뀌었으니 성공했으면 재파싱 자체가 대상에서 빠짐) · deleted(observed에 아예 없어 자동으로 빠짐)
    실패 문서는 횟수 상한 없이 늘 다시(사용자 10-30, pl-32 — 옛 REGISTRY_RETRY_MAX 컷·"retry_stopped" 지움).
    읽기만(apply()를 안 부름 — 문서 대장 쓰기는 build()/apply() 쪽 몫, 이 함수는 결정만).
    reparse_keys(선택) = 사람이 명시적으로 승인한 재파싱 대상 doc_key 집합(없으면 changed는 전부 빠짐 — 전과 동일)."""
    diff = diff_against(db, observed, fetch_sha256=fetch_sha256)
    reparse_keys = set(reparse_keys or ())
    current = {r["doc_key"]: r for r in db.query("SELECT * FROM doc_registry")}
    retry = {k for k in diff["unchanged"] + diff["touched"] if (current.get(k) or {}).get("status") != "parsed"}
    parse_keys = set(diff["new"]) | retry | (set(diff["changed"]) & reparse_keys)
    parse_names = sorted({n for k in parse_keys for n in observed[k]["names"]})
    return {"parse_names": parse_names, **diff}


def build(out_dir, db, build_id=None, seen_at=None, fetch_sha256=None):
    """scan → diff_against → apply → (REGISTRY_EDITIONS면) 대표 결과 비교 → commit. build_id 생략 시 UTC 초 단위
    타임스탬프(같은 초 안에 두 번 부르면 합쳐짐 — 시험·배치 호출은 --build-id로 명시). fetch_sha256(선택) =
    diff_against()에 그대로 전달. AD17②·AD15(10-08, editions_on() 기본 켬) — apply() 뒤 update_rep_fingerprints
    (이번 build의 new·changed doc_key만 _rep 읽어 rep_sha·rep_pairs 저장)·link_editions(이름이 같은 new/deleted
    짝만 판 관계 — diff["editions"]에 담아 돌려줌)·content_groups(전체 doc_registry, 같은 내용 다른 형식 묶음).
    → (diff, build_id)."""
    observed = scan(out_dir)
    diff = diff_against(db, observed, fetch_sha256=fetch_sha256)
    build_id = build_id or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    apply(db, observed, diff, build_id, seen_at)
    if editions_on():
        update_rep_fingerprints(db, out_dir, diff)
        diff["editions"] = link_editions(db, diff)
        content_groups(db, out_dir)
    db.commit()
    return diff, build_id
