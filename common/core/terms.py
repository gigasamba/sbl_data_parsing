"""고객 이름·별칭(명부)·ID 모양·용어 사전(T2·X3·X4) — 구조화(고객 판별)와 검색(질문 고객·질문 확장)이 같은 규칙을 써야 함.
pl-38(사용자 11-03): 명부·용어 사전·ID 모양은 PG 마스터 표(`<PG_SCHEMA>_master` — common.store.master, 원본 git CSV)에서 읽는다(프로세스마다 한 번).
dir 인자(오프라인 도구·시험)를 주면 그 폴더의 CSV를 읽는다.
명부 = stack.json client_aliases + 마스터 client_roster + 용어 사전 org_*(category에 org_client 태그 포함).
용어 사전(domain-glossary.md): 마스터 domain_terms — concept_id마다 canonical·synonyms·abbreviations·weak_synonyms·broader·related·
context_required(동음이의 약어 문맥 조건)·case_sensitive·definition_ko/en·status(approved만 검색에 반영)·category(SI43① `|` 구분 다중 태그 가능,
예 org_client|org_cdmo — 회사가 고객이면서 CDMO). SI43⑦: 이름·개념 표기 뒤 한글 조사가 붙어도 매칭(_name_pat — expand_query·match_clients 공유)."""
import sys as _sys
from pathlib import Path as _Path
import functools
import json
import os
import re
from pathlib import Path

from common.core.paths import PKG_ROOT, RES_ROOT
from common.core.text import tokens


def _cfg():
    """common 설정 객체(op-09 — 옛 env 다리 DRAFT_TERMS_* 대신). import 순환을 피해 늦게 읽음."""
    from common.config.settings import cfg
    return cfg()


ROOT = PKG_ROOT


ID_LIKE = re.compile(r"(?=.*\d)(?=.*[A-Za-z-])[A-Za-z0-9][A-Za-z0-9\-_/.]{4,}")

PARTICLES = ("에서", "으로", "한테", "까지", "부터", "과", "와", "의", "은", "는", "이", "가", "을", "를", "에", "로", "도", "만", "께")
# SI43⑦ — 한글 고유명사 뒤에 붙는 조사(실측: '셀트리온과'·'론자의'가 안 잡힘 — 긴 조사부터 시도, _name_pat 전용)


def norm(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def split_terms(s):
    """사전 필드(synonyms·abbreviations·weak_synonyms·broader·related·category)는 `|` 구분."""
    return [x.strip() for x in str(s or "").split("|") if x.strip()]


@functools.lru_cache(maxsize=None)
def _name_pat(name, flags=re.I):
    """이름(별칭·동의어·정식명)이 질문에 나왔는지 찾는 **컴파일된** 정규식(SI43⑦, 성능: RV11① — name·flags별
    `re.compile`을 한 번만, 호출부는 매 질문·매 사전 항목마다 결과를 재사용. name이 한글로 끝나고 2자 이상이면 조사
    (PARTICLES) 중 하나가 뒤에 붙어도 매칭(어간이 정확히 name과 같을 때만, 퍼지 없음) · 앞뒤가 한글이면 매칭 안
    함(다른 단어 일부에 오탐 방지 — 'name'이 1자거나 영문·숫자로 끝나면 기존 단어 경계 \\b만).
    _entry_hit(expand_query)·match_clients 공용 — 한 곳에서만 조사 규칙을 바꾼다. name·flags 쌍의 수는 사전·명부
    크기로 유한해 캐시가 무한히 안 자람(질문 수가 아니라 이름 수에 비례) — lru_cache(maxsize=None)."""
    esc = re.escape(name)
    if len(name) >= 2 and re.search(r"[가-힣]$", name):
        alt = "|".join(sorted(PARTICLES, key=len, reverse=True))
        pat = rf"(?<![가-힣]){esc}(?:{alt})?(?![가-힣])"
    else:
        pat = rf"\b{esc}\b"
    return re.compile(pat, flags)


def _id_rows(dir=None):
    """ID 모양 행 — dir(오프라인 도구·시험)이면 그 폴더 id_patterns.csv(없으면 빈 목록), 아니면 마스터 id_patterns(pl-38)."""
    if dir is None:
        from common.store import master
        return master.get().rows("id_patterns")
    p = Path(dir) / "id_patterns.csv"
    if not p.exists():
        return []
    import csv
    with p.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def load_id_patterns_typed(dir=None):
    """ID 모양(L4-7) 컴파일 — [(id_type, 정규식), …](대소문자 무시). 마스터 id_patterns(pl-38) — dir을 주면 그 폴더 CSV(없으면 빈 목록).
    검색 tie-break·엔티티 힌트(mcp local)가 id_type(계약 번호·제품 코드 등)으로 씀."""
    pats = []
    for r in _id_rows(dir):
        try:
            pats.append((r["id_type"], re.compile(r["regex"], re.I)))
        except re.error:
            continue   # validate_glossary가 오류를 알림 — 매칭 용도로는 조용히 건너뜀
    return pats


def load_id_patterns(dir=None):
    """ID 모양 정규식 목록(load_id_patterns_typed에서 id_type만 뺌)."""
    return [pat for _, pat in load_id_patterns_typed(dir)]


def validate_glossary(rows, dir=None, id_rows=None):
    """용어 사전 검증(X3) — 개념 ID 중복 · broader·related 참조 해소 · ID 모양 정규식 컴파일(id_rows, 또는 dir의 id_patterns.csv). 오류 문자열 목록(없으면 통과)."""
    errs = []
    ids = [r["concept_id"] for r in rows]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errs.append(f"개념 ID 중복: {dup}")
    idset = set(ids)
    for r in rows:
        for field in ("broader", "related"):
            for ref in split_terms(r.get(field)):
                if ref not in idset:
                    errs.append(f"{r.get('concept_id')}.{field} 참조 없음: {ref}")
    if id_rows is None and dir is not None:
        id_rows = _id_rows(dir)
    for r in id_rows or ():
        try:
            re.compile(r["regex"])
        except re.error as ex:
            errs.append(f"id_patterns {r.get('id_type')} 정규식 오류: {ex}")
    return errs


def _read_text(path):
    """사람이 만든 CSV — UTF-8(BOM 포함) 먼저, 실패하면 cp949(한국어 Excel 'CSV' 저장 기본). (글자, 인코딩)."""
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp949"), "cp949"


def _fill_glossary_blanks(rows):
    """10-15 긴급 — 외부에서 채운 용어집은 칸이 비어 있을 수 있다(설명·카테고리·상태 등):
    status 빈칸 = approved(명시한 draft·rejected 등만 뺌) · concept_id 빈칸 = 'AUTO.<정식 이름>'(정식 이름도 없으면 그 행 버림)
    · 아예 없는 열은 빈 값. 진짜 충돌(명시한 ID 중복·끊긴 참조·깨진 정규식)은 그대로 검증 오류."""
    rows = [{k: (v or "").strip() if isinstance(v, str) or v is None else v for k, v in r.items() if k is not None} for r in rows]
    taken = {r.get("concept_id") for r in rows if r.get("concept_id")}
    out = []
    for r in rows:
        canon = r.get("canonical", "")
        if not r.get("concept_id"):
            if not canon:
                continue
            auto = "AUTO." + re.sub(r"\s+", "_", canon)
            if auto in taken:   # 같은 정식 이름이 ID 없이 또 나옴 = 같은 용어 — 버리고 한 줄 알림(시트 실수 하나로 사전 전체가 멈추지 않게, 94 검토)
                print(f"[terms] 용어집: ID 없는 같은 용어 '{canon}' 한 줄 더 — 건너뜀", file=_sys.stderr)
                continue
            taken.add(auto)
            r["concept_id"] = auto
        if not r.get("status"):
            r["status"] = "approved"
        out.append(r)
    return out


def _mtime(p):
    """파일 (크기, 고친 시각 ns) — 없으면 None. 읽은 결과 캐시 열쇠(파일이 바뀌면 다시 읽음 — fp-perf B2, contract.file_hash와 같은 열쇠)."""
    try:
        st = os.stat(p)
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


_CACHE = {}  # (종류, 경로·크기·고친 시각…) → 읽은 결과 — 문서마다 명부·사전을 다시 읽지 않게(fp-perf B2, 0.2.0)
_CACHE_MAX = 4  # ponytail: 상주 검색 서버에서 파일을 바꿀 때마다 옛 결과가 쌓이지 않게 — 넘으면 가장 오래된 것부터 버림


def _cached(key, build):
    if key not in _CACHE:
        while len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = build()
    return _CACHE[key]


def load_glossary(dir=None):
    """용어 사전 로더(X3) — 마스터 domain_terms(pl-38)를 검증 후 approved만 {concept_id: row}로. dir을 주면 그 폴더 domain_terms.csv
    (오프라인 도구·시험). 같은 마스터 해시(또는 같은 파일)면 한 번만 만든다 — 돌려주는 사전은 얕은 사본(호출부가 고쳐도 캐시는 그대로)."""
    if dir is None:
        from common.store import master
        return dict(_master_glossary(master.get()))
    key = ("glossary", str(dir), _mtime(Path(dir) / "domain_terms.csv"), _mtime(Path(dir) / "id_patterns.csv"))  # 검증이 id_patterns도 읽음
    return dict(_cached(key, lambda: _load_glossary(dir)))


def _master_glossary(m):
    """마스터(common.store.master.Master)의 용어 사전 — 같은 해시면 한 번만 만든다."""
    return _cached(("glossary", m.hash), lambda: _build_glossary(m.rows("domain_terms"), None, m.rows("id_patterns")))


def _load_glossary(d):
    import csv
    return _build_glossary(csv.DictReader(_read_text(Path(d) / "domain_terms.csv")[0].splitlines()), d)


def _build_glossary(rows, d=None, id_rows=None):
    rows = _fill_glossary_blanks(rows)
    errs = validate_glossary(rows, d, id_rows)
    if errs:
        raise ValueError("용어 사전 검증 실패:\n- " + "\n- ".join(errs))
    return {r["concept_id"]: r for r in rows if r.get("status") == "approved"}


DRAFT_TERMS_MAX = 500   # SI43③④ — 자동 draft 파일 행 수 상한 기본값(가장 빈번한 것만 유지, 독립 검토 BLOCK 1 10-13)


def _draft_terms_max():
    """DRAFT_TERMS_MAX — 설정 common.text.draft_terms_max(시험용으로 작게·운영에서 크게, 기본 500 — op-09).
    모듈 전역이 아니라 설정에서 읽는 이유: `python -m common.core.terms`처럼 이 모듈이 `__main__`으로 실행되면 또 다른
    모듈 객체가 생겨(run-as-script 함정) 모듈 전역을 직접 바꿔도 __main__ 쪽 함수는 못 봄."""
    v = _cfg().text.draft_terms_max
    return DRAFT_TERMS_MAX if v is None else int(v)  # 0도 그대로(상한 0)
_DRAFT_FIELDS = ["concept_id", "canonical", "category", "synonyms", "abbreviations", "weak_synonyms",
                 "broader", "related", "context_required", "case_sensitive", "definition_ko", "definition_en",
                 "source", "owner", "status", "updated"]   # cli/glossary_suggest.py(T6)의 FIELDS와 같은 칸(source에 카운트 저장)


def draft_terms_path(path=None):
    """SI43③④ 자동 draft 파일 — **GLOSSARY_DIR이 아니라 output/ 아래**(독립 검토 BLOCK 1, 10-13: 서버에서 GLOSSARY_DIR은
    이미지 밖 실 운영 사전 폴더라 거기 쓰면 PermissionError로 구조화 전체가 깨짐 · cli/glossary_suggest.py(T6)도
    같은 이유로 draft를 output/에만 쓰고 domain_terms.csv는 사람이 손으로 승격). 기본
    APP_ROOT/output/glossary_draft/domain_terms_draft_auto.csv — DRAFT_TERMS_OUT env 또는 인자로 바꿀 수 있음(시험용)."""
    from common.core.paths import APP_ROOT
    return Path(path or _cfg().paths.draft_terms_out or (APP_ROOT / "output" / "glossary_draft" / "domain_terms_draft_auto.csv"))


class _DraftLock:
    """SI43③④ — output/ draft 파일의 read-modify-write 경합(동시에 도는 구조화·EDW 추출 여러 실행) 방지. cli/index.py의
    O_EXCL 잠금과 같은 틀이지만 실패해도 멈추지 않는다 — 짧게(timeout초) 재시도만 하고 못 잡으면 acquired=False로
    돌아가 호출부가 이번 쓰기를 조용히 건너뛴다(이 draft 수집은 멱등·최선형이라 — 다음 실행이 다시 모은다,
    구조화 전체를 막을 이유가 없음). stale_sec(기본 2분)보다 오래된 잠금은 죽은 프로세스로 보고 회수."""
    def __init__(self, path, timeout=5.0, stale_sec=120):
        self.p = Path(str(path) + ".lock")
        self.timeout, self.stale_sec = timeout, stale_sec
        self.acquired = False

    def __enter__(self):
        import time as _time
        self.p.parent.mkdir(parents=True, exist_ok=True)
        deadline = _time.time() + self.timeout
        while True:
            try:
                fd = os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.acquired = True
                return self
            except FileExistsError:
                try:
                    age = _time.time() - self.p.stat().st_mtime
                except FileNotFoundError:
                    continue                                # 그 사이 풀림 — 다시 시도
                if age > self.stale_sec:
                    self.p.unlink(missing_ok=True)           # 죽은 프로세스의 잠금 — 회수
                    continue
                if _time.time() >= deadline:
                    return self                              # acquired=False — 호출부가 이번 쓰기를 건너뜀
                _time.sleep(0.05)

    def __exit__(self, *exc):
        if self.acquired:
            self.p.unlink(missing_ok=True)


def load_draft_glossary(path=None):
    """SI43③④ — draft_terms_path(path)의 자동 draft CSV에서 status==draft 행 {concept_id: row}로(실제로는 그
    파일 전부가 draft). 사전 없음(파일 없음)이면 빈 사전."""
    p = draft_terms_path(path)
    if not p.exists():
        return {}
    import csv
    with p.open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return {r["concept_id"]: r for r in rows if r.get("status") == "draft"}


def _draft_concept_id(name, prefix="DRAFT.ORG"):
    """draft concept_id(결정적) — 영문·숫자만 남겨 대문자(예 'Northfield Biologics Inc.' → 'NORTHFIELDBIOLOGICSINC')
    24자 상한, 한글 등 영문·숫자가 하나도 없으면 이름의 sha1 앞 10자(짧고 안정적, 이름이 같으면 항상 같은 id)."""
    ascii_part = re.sub(r"[^A-Za-z0-9]+", "", name)[:24].upper()
    if ascii_part:
        return f"{prefix}.{ascii_part}"
    import hashlib
    return f"{prefix}.{hashlib.sha1(name.encode('utf-8')).hexdigest()[:10].upper()}"


def _draft_count(source):
    """source 칸("auto:count=N")에서 N(없거나 모양이 안 맞으면 1)."""
    m = re.match(r"auto:count=(\d+)", source or "")
    return int(m.group(1)) if m else 1


def write_draft_terms(names, path=None, category="org_client"):
    """SI43④(회사 이름, 구조화 쪽 structure/draft_terms.py가 후보를 찾음)·SI43③(제품 이름, cli/gen_roster.py —
    EDW 제품 마스터 추출본) — 새 이름 후보를 **output/ 자동 draft CSV**(draft_terms_path, GLOSSARY_DIR이 아님 —
    독립 검토 BLOCK 1)에 status=draft 행으로 쌓는다(사람 승인 없이 — approved 승격은 사람이 domain_terms.csv로
    손수 옮기는 옵션, 여기서는 안 함). 같은 이름이 다시 들어오면 새 행을 안 만들고 source 칸의 카운트만
    +1("auto:count=N") — DRAFT_TERMS_MAX(기본 500)를 넘으면 **카운트가 가장 낮은 것부터** 쳐낸다(여러 번
    구조화에서 되풀이로 나온 이름일수록 남는다, 독립 검토 BLOCK 1 "keep most frequent"). concept_id 접두는
    category에서(org_client·org_cdmo 등 org_*는 DRAFT.ORG, 그 밖(product_example 등)은 category 대문자 — 두
    호출자가 접두가 겹쳐 concept_id가 충돌하지 않게). 파일 잠금(_DraftLock, 동시 실행 경합 방지) 못 잡으면
    이번 호출은 조용히 아무것도 안 하고 빈 목록 반환(구조화를 막지 않음, 다음 실행이 다시 모음) · 쓰기는
    임시 파일 + os.replace(원자적 — 쓰다 죽어도 반쪽 파일이 안 남음). names 비면 아무것도 안 함. 반환: 이번
    호출에서 **새로 생긴**(이미 있던 이름의 카운트 증가는 제외) 이름 중 캡 적용 뒤에도 남은 것(결정적 순서 —
    이름 오름차순)."""
    if not names:
        return []
    import csv
    p = draft_terms_path(path)
    lock_timeout = float(_cfg().runtime.draft_terms_lock_timeout)   # 시험용으로 짧게 줄일 수 있음(기본 5초 — 설정 모델)
    with _DraftLock(p, timeout=lock_timeout) as lk:
        if not lk.acquired:
            return []                                        # 경합 — 이번엔 포기(다음 실행이 다시 모음, 멱등)
        rows, fields = [], _DRAFT_FIELDS
        if p.exists():
            with p.open(encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
            if rows:
                fields = list(rows[0].keys())
        prefix = "DRAFT.ORG" if category.startswith("org_") else f"DRAFT.{category.upper()}"
        by_canon = {norm(r.get("canonical")): r for r in rows}
        existing_ids = {norm(r.get("concept_id")) for r in rows}
        added = []
        for name in sorted(set(names)):
            nn = norm(name)
            if nn in by_canon:
                r = by_canon[nn]
                r["source"] = f"auto:count={_draft_count(r.get('source')) + 1}"
                continue
            cid = _draft_concept_id(name, prefix)
            if norm(cid) in existing_ids:
                continue
            row = {**{f: "" for f in fields}, "concept_id": cid, "canonical": name, "category": category,
                   "source": "auto:count=1", "status": "draft"}
            rows.append(row)
            by_canon[nn] = row
            existing_ids.add(norm(cid))
            added.append(name)
        if not added and not rows:
            return []
        rows.sort(key=lambda r: (-_draft_count(r.get("source")), norm(r.get("canonical"))))   # 빈도 내림 — 가장 빈번한 것부터
        kept = rows[:_draft_terms_max()]
        kept_canon = {norm(r.get("canonical")) for r in kept}
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + f".tmp{os.getpid()}")
        with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(kept)
        os.replace(tmp, p)                                    # 원자적 교체 — 쓰다 죽어도 반쪽 파일이 안 남음
    return [n for n in added if norm(n) in kept_canon]


def related_concepts(cid, glossary=None):
    """개념의 상위(broader)·관련(related) 개념(X4 related) — 확장에는 쓰지 않음, 탐색·설명용."""
    glossary = load_glossary() if glossary is None else glossary
    r = glossary.get(cid)
    if not r:
        return []
    ids = split_terms(r.get("broader")) + split_terms(r.get("related"))
    return [{"concept_id": x, "canonical": glossary[x]["canonical"]} for x in ids if x in glossary]


# T6 — 약어 정의 패턴 추출("<정식명>(<약어>)"·"<약어>(<정식명>)", 한·영 혼용) → 사람 승인 전 draft 후보만
# (설계 §4-B③ 원문 괄호 패턴). 검색엔 반영 안 됨 — cli/glossary_suggest.py가 쓰는 CSV만 만든다.
_DEF_TERM = r"[A-Za-z가-힣][A-Za-z가-힣0-9]*(?:[ \-/&][A-Za-z가-힣0-9]+){0,5}"   # 1~6 단어(공백·-·/·& 구분), 숫자 시작 금지
_DEF_ABBR = r"[A-Z]{2,6}[0-9]{0,2}"                                            # 대문자만 2~6자(+숫자 0~2) — 소문자 섞인 단위(mL 등)는 자동 제외
_DEF_BOUND = r"(?<![A-Za-z0-9가-힣])"                                           # 앞이 글자·숫자가 아닐 때만(단어 중간에서 안 끊김)
_DEF_PATTERN = re.compile(
    rf"{_DEF_BOUND}(?P<term1>{_DEF_TERM})\s?\((?P<abbr1>{_DEF_ABBR})\)"
    rf"|{_DEF_BOUND}(?P<abbr2>{_DEF_ABBR})\s?\((?P<term2>{_DEF_TERM})\)"
)


def scan_definitions(records):
    """records: [(text, location), …] → 약어 정의 후보([{term,abbr,count,example}], 많이 나온 순) — 길이·문자
    제약만 여기서 거름(사전·명부 대조는 filter_definitions). "바이러스 불활화(VI)"·"MTOP(최소 구매 약정)"·
    "Out of Specification (OOS)" 형태를 한 정규식 두 방향(정식명 먼저/약어 먼저)으로 찾는다."""
    found = {}
    for text, loc in records:
        for m in _DEF_PATTERN.finditer(str(text)):
            term = (m.group("term1") or m.group("term2")).strip()
            abbr = (m.group("abbr1") or m.group("abbr2")).strip()
            if not (2 <= len(term) <= 60 and 2 <= len(abbr) <= 8):
                continue
            row = found.setdefault((term.lower(), abbr), {"term": term, "abbr": abbr, "count": 0, "example": loc})
            row["count"] += 1
    return sorted(found.values(), key=lambda r: (-r["count"], r["term"]))


_DEF_NOISE_ABBR = {"ID", "NO", "OK", "VS", "ETC", "INC", "LTD", "CO", "CORP", "PTE", "PLC", "LLC",
                    "USD", "KRW", "EUR", "JPY", "GBP", "CNY", "CHF", "HKD", "SGD", "AUD", "CAD"}  # 정의 약어가 아닌 흔한 대문자 토큰·통화 코드(ISO 4217)
_DEF_FILE_EXT = re.compile(r"\.(pdf|docx?|xlsx?|csv|txt|png|jpe?g|pptx?)$", re.I)
_DEF_FILE_EXT_BARE = {"pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "png", "jpg", "jpeg", "ppt", "pptx"}  # 앞 '.'이 토큰 경계에서 잘려 term이 확장자만 남는 경우
_DEF_NUMERIC = re.compile(r"^[0-9][0-9.,\s]*$")   # 정식명 자리가 숫자뿐(연도·수량)


def _is_known_pair(term, abbr, glossary):
    """term·abbr 짝이 같은 사전 항목(canonical/synonyms 쪽 term, abbreviations 쪽 abbr)에 이미 있는지(공백·대소문자
    무시). term이 알려진 표기 뒤에 앞 낱말이 더 붙어 길어진 것도 같은 짝으로 본다(product code·문항 번호가 앞에
    끼어들어 "FX-MAB-01 하류 공정"처럼 되는 경우 — 실측 T6, 진짜 새 개념이 아니라 기존 DSP 표기의 접두 잡음)."""
    tn, an = norm(term), norm(abbr)
    for r in glossary.values():
        names = {norm(x) for x in [r.get("canonical")] + split_terms(r.get("synonyms")) if x}
        abbrs = {norm(x) for x in split_terms(r.get("abbreviations"))}
        if an not in abbrs:
            continue
        if tn in names or any(name and tn.endswith(name) for name in names):
            return True
    return False


def filter_definitions(candidates, glossary=None, aliases=None):
    """scan_definitions 결과에서 ① 사전(approved)에 이미 있는 짝 ② 뜻없는 잡음(파일명 확장자·숫자뿐·흔한 대문자
    토큰·명부(roster) 고객 표기와 같은 글자)을 뺀다 — 남는 것만 '새 후보'(자동 반영 없음, T6)."""
    glossary = load_glossary() if glossary is None else glossary
    aliases = _aliases() if aliases is None else aliases
    alias_norms = {norm(a) for names in aliases.values() for a in names} | {norm(c) for c in aliases}
    out = []
    for c in candidates:
        term, abbr = c["term"], c["abbr"]
        if abbr in _DEF_NOISE_ABBR:
            continue
        if _DEF_FILE_EXT.search(term) or _DEF_NUMERIC.match(term) or term.lower() in _DEF_FILE_EXT_BARE:
            continue
        if norm(abbr) in alias_norms or norm(term) in alias_norms:
            continue
        if _is_known_pair(term, abbr, glossary):
            continue
        out.append(c)
    return out


_SHORT_EN = re.compile(r"[A-Za-z0-9]{1,3}")   # 고객 판별은 부분 문자열이라 영문 3자 이하 약어(PFE·SK)는 solution·risk에 걸림


def _roster_rows(path):
    """CLIENT_ROSTER 파일 → [(정식 이름, [별칭…]), …](파일 순서, 걸러내기 전) · 인코딩: UTF-8(BOM 포함) 먼저,
    실패하면 cp949(한국어 Excel 'CSV' 저장 기본 — E15 SFDC 내보내기). JSON {이름: [별칭]} 또는 CSV(1열 이름,
    2열 별칭 ; 또는 | 구분, 머리글 'name'/'고객'/'client' 건너뜀). 반환 둘째 값 = 실제로 읽은 인코딩."""
    txt, enc = _read_text(path)
    if str(path).lower().endswith(".json"):
        return [(k, list(v or [])) for k, v in json.loads(txt).items()], enc
    import csv
    lines = txt.splitlines()
    head = [h.strip().lower() for h in next(csv.reader(lines[:1]), [])]
    if "canonical_name" in head:   # 10-15 긴급 — 새 형식(docs: env-guide 'CLIENT_ROSTER' 표): 정식 이름 빈칸이면 name_ko로, 둘 다 빈칸이면 버림
        return _roster_dicts(csv.DictReader(lines)), enc
    return [(r[0].strip(), [x.strip() for x in re.split(r"[;|]", r[1]) if x.strip()] if len(r) > 1 else [])
            for r in csv.reader(txt.splitlines())
            if r and r[0].strip() and r[0].strip().lower() not in ("name", "고객", "client")], enc


def _roster_dicts(rows):
    """새 형식 명부 행(사전 — CSV DictReader·마스터 client_roster 같은 칸) → [(정식 이름, [별칭…]), …]."""
    out = []
    for r in rows:
        # extra cells (unquoted comma) land under key None as a list — skip them like _fill_glossary_blanks does
        r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k is not None}
        if r.get("status", "").lower() in ("inactive", "deleted"):   # SFDC exports write "Inactive"
            continue
        name = r.get("canonical_name") or r.get("name_ko")
        if not name:
            continue
        al = [x.strip() for x in re.split(r"[;|]", r.get("aliases", "")) if x.strip()]
        if r.get("name_ko") and r["name_ko"] != name:
            al.append(r["name_ko"])
        out.append((name, al))
    return out


def _merge_roster(pairs):
    """[(정식 이름, [별칭…])] → {정식 이름: [별칭…]}(같은 이름 여러 줄은 합침 · 영문 3자 이하 별칭은 뺌 — 용어집 org_client와 같은 규칙)."""
    out = {}
    for name, al in pairs:
        out[name] = sorted(set(out.get(name, [])) | {x for x in al if not _SHORT_EN.fullmatch(x)})
    return out


def read_roster(path):
    """E15 — 명부 파일(gen_roster·시험) → {정식 이름: [별칭…]}(같은 이름 여러 줄은 합침 · 영문 3자 이하 별칭은 뺌)."""
    return _merge_roster(_roster_rows(path)[0])


def _aliases():
    """고객 명부 = stack.json client_aliases + 마스터 client_roster(SFDC 고객 마스터 내보내기 — pl-38) + 마스터 용어 사전 org_client.
    같은 마스터 해시·같은 stack 파일이면 한 번만 만든다(fp-perf B2) — 돌려주는 사전은 얕은 사본."""
    from common.store import master
    stack, m = RES_ROOT / "config" / "pipeline_stack.json", master.get()
    return dict(_cached(("aliases", _mtime(stack), m.hash), lambda: _build_aliases(stack, m)))


def _build_aliases(stack, m):
    try:
        out = dict(json.loads(stack.read_text(encoding="utf-8")).get("client_aliases") or {})
    except (OSError, ValueError):
        out = {}
    for c, al in _merge_roster(_roster_dicts(m.rows("client_roster"))).items():
        out[c] = sorted(set(out.get(c, [])) | set(al))
    # 용어 사전(T3, docs/architecture.md) — org_*(client 태그)·approved의 동의어·약어(로더는 load_glossary 한 곳)
    for r in _master_glossary(m).values():
        if "org_client" in split_terms(r.get("category")):   # SI43① category는 `|` 구분 다중 태그 가능(예 org_client|org_cdmo) — 기존 한 칸 값도 그대로 맞음
            al = split_terms(r.get("synonyms")) + split_terms(r.get("abbreviations"))
            # 영문 3자 이하 약어(PFE·SOL)는 뺌 — 여기 판별은 부분 문자열이라 solution·sold에 걸림. ponytail: 단어 경계 일치는 T2 질문 확장에서
            al = [x for x in al if not _SHORT_EN.fullmatch(x)]
            out[r["canonical"]] = sorted(set(out.get(r["canonical"], [])) | set(al))
    return out


def _name_hit(name, question):
    """SI43⑦ — name이 question에 나왔는지. 공백 없이 한글로 끝나는 이름(2자+)은 조사가 붙어도 매칭(_name_pat,
    _entry_hit과 같은 규칙 공유) · 그 밖(영문·공백 포함 다단어)은 기존 규칙(공백 무시 부분일치 — OCR 공백 차이 보정,
    'Contoso Pharma'·'ContosoPharma')을 그대로 유지."""
    if name and " " not in name and len(name) >= 2 and re.search(r"[가-힣]$", name):
        return bool(_name_pat(name).search(question))
    return bool(name) and norm(name) in norm(question)


def match_clients(question, clients, aliases=None):
    """질문에 나온 고객(이름 전체 · 별칭(stack.json client_aliases) · 영문 첫 단어 4자+) — 순서 유지."""
    out, seen = [], set()
    aliases = _aliases() if aliases is None else aliases
    for c in sorted((c for c in clients if c), key=len, reverse=True):
        names = [c] + list(aliases.get(c, []))
        first = re.match(r"[A-Za-z]{4,}", c)
        if norm(c) not in seen and (any(_name_hit(n, question) for n in names) or (first and re.search(r"\b" + re.escape(first.group(0)) + r"\b", question, re.I))):
            out.append(c)
            seen.add(norm(c))                                # 'Contoso Pharma'·'ContosoPharma'(OCR 공백 차이)는 한 고객
    return out

