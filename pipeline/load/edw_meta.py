"""적재 때 EDW 조인으로 문서 메타 채우기(pl-29, 사용자 11-02 — 매핑은 적재 몫). 원본 경로(gold doc.file_path = FileStorageMap.s3_key)마다
원천별 사슬을 따라 고객(client_edw)·원천 전용 칸·등록 시각(created_at)을 구한다 — 외부 파일 file_meta는 쓰지 않는다. 읽기 계정만(SELECT).
사슬의 표·칸 이름·SFDC 단계 순서·gold 칸 대응은 설정 파일 resources/config/edw_chain.yaml(운영 쪽이 고침 — 사용자 11-02, load_chain이 검사).
서버에서 고친 사본은 설정 ops.pipeline_paths.edw_chain(비우면 기본 파일 — 사용자 11-03). 파일만 점검(EDW·PG 안 붙음): python -m pipeline.load.edw_meta --check [--file F].
사슬의 모양(코드):
- SFDC: FileStorageMap → ContentVersion(문서 id·등록 시각 UTC) → ContentDocumentLink(지우지 않은 연결) → 연결 개체 접두로 영업 기회 — 설정의
  steps 순서(지금: 006 직접 > 00T Task > 00U Event; Quote 표는 없음 — 생기면 설정 한 줄, optional이면 표를 못 읽을 때 그 단계만 건너뜀) ·
  고객: 기회의 계정 → Account 이름, 기회 후보가 아예 없으면 단계 표 값 001 > 연결 개체 001(계정 직접) · 같은 단계에 후보가 둘 이상이면 비움(NULL).
- CRMS: FileStorageMap_CRMS → 계약 목록(RM_CM_PJTLIST) · 등록 시각 문서 표(RM_CM_DOCU, 키 4개).
- LAS: FileStorageMap_LAS → 계약(최신 판 — active·id 내림차순) · 등록 시각 FileManager.
- FAQ·Other: FileStorageMap 등록 시각만.
분류 힌트(pl-33, 사용자 11-02 — 운영 analyze_clues 규칙, 설정 sfdc.hints·las.hints): SFDC는 제목 + 첫 User 아닌 연결 개체(종류·갈래·id —
접두 표 resources/mappings/sfdc_prefix.json) + 그 개체가 Task/Event면 방향·제목(120자), 영업 기회면 단계·Real_RFP__c·RFP 기간. LAS는 품의 제목.
gold 칸 이름 = 원본 칸 이름의 소문자(search_tables.DOC_HINTS). 힌트 조회는 따로 — 서버 EDW에 칸이 없으면 그 힌트만 비움(경고).
EDW를 못 열면 빈 dict와 경고(적재는 메타를 비운 채 계속 — 사용자 11-02, 자동 갱신 없음: 나중에 --replace로 다시 적재해 채움).
설정 파일이 틀리면(빠진 이름·SQL에 넣을 수 없는 이름·doc 표에 없는 gold 칸) ValueError로 멈춘다 — 이름은 SQL 글자에 들어가므로 검사, 값은 늘 바인딩."""

import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from common.core.paths import RES_ROOT
from common.store import edw_chain as EC
from common.store.db.models import search_tables as ST

CHUNK = 500  # IN 목록 크기
CHAIN_FILE = RES_ROOT / "config" / "edw_chain.yaml"
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*")
_PREFIX = re.compile(r"[0-9A-Za-z]{3}")
_REQ = {  # 설정 자리 → 꼭 있어야 하는 이름
    ("files",): ("table", "key", "created"),
    ("sfdc", "version"): ("table", "file_col", "id", "doc", "created"),
    ("sfdc", "link"): ("table", "doc", "entity", "deleted"),
    ("sfdc",): ("opp_prefix", "account_prefix", "steps"),
    ("sfdc", "opportunity"): ("table", "id", "account", "out"),
    ("sfdc", "account"): ("table", "id", "name"),
    ("crms", "map"): ("table", "key", "contract", "gate", "gate_version", "seq", "out"),
    ("crms", "project"): ("table", "contract", "out"),  # out을 빠뜨리면 CRMS 고객·칸이 조용히 비지 않게(#98 리뷰)
    ("crms", "docu"): ("table", "contract", "gate", "gate_version", "seq", "created"),
    ("las", "map"): ("table", "key", "manage_no", "signed", "file_id"),
    ("las", "file"): ("table", "id", "created"),
    ("las", "contract"): ("table", "manage_no", "active", "id", "date", "client"),
    ("sfdc", "hints"): ("title", "channel", "opportunity"),
    ("sfdc", "hints", "opportunity"): ("stage", "real_rfp", "rfp_start", "rfp_end"),
    ("las", "hints"): ("approval",),
}
_CHANNEL = ("type", "table", "id", "direction", "subject")  # sfdc.hints.channel 항목마다


def chain_file():
    """쓸 사슬 설정 파일 — 설정 pipeline.paths.edw_chain(서버에서 고친 사본), 비우면 기본 CHAIN_FILE."""
    from pipeline import config as pc

    p = pc.cfg().paths.edw_chain
    return Path(p) if p else CHAIN_FILE


def legacy_load_chain(path=None):
    """사슬 설정 읽기 + 검사 — 틀리면 ValueError(어디가 왜 틀렸는지 모두). path 없으면 chain_file()(설정 → 기본 파일).
    파일이 없거나 YAML이 깨져도 ValueError — 기본 파일로 조용히 돌아가지 않는다(적재가 시작할 때 멈춤)."""
    import yaml

    path = Path(path) if path else chain_file()
    try:
        c = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(
            f"[edw_meta] 사슬 설정 파일을 못 읽음({path}): {type(e).__name__} — settings.yaml ops.pipeline_paths.edw_chain을 확인(비우면 기본 파일)"
        ) from e
    except yaml.YAMLError as e:
        raise ValueError(f"[edw_meta] 사슬 설정 YAML 오류({path}): {e}") from e
    if not isinstance(c, dict):
        raise ValueError(f"[edw_meta] 사슬 설정 오류({path}): 최상위가 사전(원천: …)이 아님")
    errs = []
    for where, names in _REQ.items():
        sec = c
        for k in where:
            sec = sec.get(k) if isinstance(sec, dict) else None
        if not isinstance(sec, dict):
            errs.append(f"{'.'.join(where)}: 없음")
            continue
        errs += [f"{'.'.join(where)}.{n}: 없음" for n in names if n not in sec]
    sf = c.get("sfdc") if isinstance(c, dict) else None
    steps = sf.get("steps") if isinstance(sf, dict) else None
    if not isinstance(steps, list) or not steps:
        errs.append("sfdc.steps: 단계 목록이 비었거나 목록이 아님")
    for i, st in enumerate(steps if isinstance(steps, list) else []):
        need = ("prefix", "id", "value") if isinstance(st, dict) and "table" in st else ("prefix",)
        errs += [f"sfdc.steps[{i}].{n}: 없음" for n in need if not isinstance(st, dict) or n not in st]
    hs = sf.get("hints") if isinstance(sf, dict) else None
    ch = hs.get("channel") if isinstance(hs, dict) else None
    for i, st in enumerate(ch if isinstance(ch, list) else []):
        errs += [f"sfdc.hints.channel[{i}].{n}: 없음" for n in _CHANNEL if not isinstance(st, dict) or n not in st]
    _check(c, "", "", None, errs)
    if errs:
        raise ValueError(f"[edw_meta] 사슬 설정 오류({path}): " + "; ".join(errs))
    return c


def _out_cols(src):
    """설정 out으로 채울 수 있는 gold 칸 — 그 원천 전용 칸(분류 라벨 doc_class 빼고) + client_edw(SFDC는 코드가 계정에서 채움).
    키·경로(file_path·doc_id)·created_at(코드가 사슬에서 정함)은 안 됨 — 적재가 이 값으로 문서 행을 덮어쓰므로(리뷰)."""
    out = {  # 원천 → attrs 키(pl-52 — 옛 원천 전용 칸 이름, 사슬 파일 새 꼴에서 fields로 바뀜)
        "sfdc": {"sf_op_id", "sf_op_name", "project_code__c", "service_type", "contract_date"},
        "crms": {"division", "prod_name", "contract_id", "contract_date"},
        "las": {"contract_id", "contract_date"},
    }
    if src not in out:
        return set()
    return out[src] | (set() if src == "sfdc" else {"client_edw"})


def _check(node, where, key, src, errs):
    """이름 검사 — table은 `스키마.표`, *prefix는 3자, optional은 참거짓, out은 {그 원천 doc 칸: EDW 칸}, 나머지 글자는 칸 이름."""
    if isinstance(node, dict):
        for k, v in node.items():
            w = f"{where}.{k}" if where else str(k)
            if k == "out":
                cols = _out_cols(src)
                if not isinstance(v, dict) or not v:
                    errs.append(f"{w}: {{gold 칸: EDW 칸}} 꼴이어야 함")
                    continue
                errs += [f"{w}.{g}: {src}에서 설정으로 채울 수 없는 칸(허용 {sorted(cols)})" for g in v if g not in cols]
                for g, e in v.items():
                    _check(e, f"{w}.{g}", g, src, errs)
            elif k == "optional":
                if not isinstance(v, bool):
                    errs.append(f"{w}: true 또는 false")
            else:
                _check(v, w, k, src or (k if not where else None), errs)
    elif isinstance(node, list):
        for i, x in enumerate(node):
            _check(x, f"{where}[{i}]", key, src, errs)
    else:
        rx = _TABLE if key == "table" else _PREFIX if str(key).endswith("prefix") else _ID
        if not isinstance(node, str) or not rx.fullmatch(node):
            errs.append(f"{where}: {node!r} — {'스키마.표' if rx is _TABLE else '3자 접두' if rx is _PREFIX else '영문·숫자·_ 이름'}만")


class _Edw:
    """읽기 연결 — PC는 가짜 EDW sqlite(common.connections.rdb.sqlite), 서버는 읽기 계정 MSSQL. q(sql, 값) → dict 행(자리표시 `?`)."""

    def __init__(self):
        from common.store import mssql

        p = mssql.standin_path()
        if p:
            self.cn, self.ph = mssql.standin(p, readonly=True), "?"
        else:
            kw, miss = mssql.login("read")
            if miss:
                raise RuntimeError(f"EDW 읽기 계정 없음: {', '.join(miss)}")
            self.cn, self.ph = mssql.raw(**kw), "%s"

    def q(self, sql, params=()):
        cur = self.cn.cursor()
        cur.execute(sql.replace("?", self.ph), tuple(params))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def q_in(self, sql, values, pre=()):
        """sql 안의 `{IN}`을 값 목록 자리표시로 — CHUNK개씩 나눠 묻고 행을 합친다. pre = `{IN}` 앞 자리표시 값(고정 조건)."""
        out, values = [], sorted(set(v for v in values if v not in (None, "")))
        for k in range(0, len(values), CHUNK):
            part = values[k : k + CHUNK]
            out += self.q(sql.replace("{IN}", ", ".join(["?"] * len(part))), [*pre, *part])
        return out

    def close(self):
        self.cn.close()


def load_chain(path=None):
    """사슬 설정 읽기 + 검사(common.store.edw_chain) — 틀리면 ValueError. path 없으면 chain_file()(설정 → 기본 파일)."""
    return EC.load(path or chain_file())


def fetch(docs, edw=None, chain=None):
    """docs = [(source_system, file_path)] → ({file_path: {"created_at", "client_edw", "attrs": {키: 값}}}, 메타를 못 구한 문서 수).
    EDW를 못 열면 ({}, len(docs)) + 경고. chain — 사슬 설정(기본 load_chain() — 틀리면 ValueError로 멈춤). attrs에는 값이 있는 키만."""
    chain = chain or load_chain()
    own = edw is None
    try:
        edw = edw or _Edw()
    except Exception as e:  # 연결 정보 없음·접속 실패 — 메타 없이 적재(사용자 11-02)
        print(
            f"[edw_meta] 경고: EDW를 못 엶 — 문서 메타를 비운 채 적재({len(docs)}건, 나중에 --replace로 다시 적재): {type(e).__name__}",
            file=sys.stderr,
            flush=True,
        )
        return {}, len(docs)
    by_src = {}
    for sys_, path in docs:
        by_src.setdefault(ST.source_of(sys_), []).append(path)
    out = {}
    try:
        for src, paths in by_src.items():
            try:
                out.update(_resolve(edw, paths, chain[src]))
            except Exception as e:  # 한 원천의 사슬 실패(표·칸 이름 다름 등) — 그 원천만 비움
                print(
                    f"[edw_meta] 경고: {src} 메타 조회 실패 — 그 원천 문서는 메타를 비움({len(paths)}건): {type(e).__name__}: {str(e)[:160]}",
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        if own:
            edw.close()
    return out, sum(1 for _, p in docs if not _found(out.get(p)))


def _found(m):
    return bool(m) and (m["created_at"] is not None or m["client_edw"] is not None or bool(m["attrs"]))


def _vals(rows, ref, path):
    """열쇠 하나 → 값 목록(빈 값 뺌) — file = 문서 원본 경로, <단계>.<칸> = 그 단계 행들의 칸 값(행 순서)."""
    if ref == EC.FILE:
        return [path]
    step, _, col = ref.partition(".")
    return [r.get(col) for r in rows.get(step, []) if r.get(col) not in (None, "")]


def _pick(rows, path, alts, prefix, decided):
    """열쇠 목록 — 앞 자리부터 후보(접두 맞는 값)가 있는 첫 자리에서 정함: (열쇠 또는 None(동률), 정해짐). 앞 자리가 이미 정해진 목록 단계를
    가리키면 후보가 없어도 거기서 정함(그 단계가 비었으면 이것도 빔 — 다른 사슬의 값을 붙이지 않음)."""
    for a in alts:
        a = a if isinstance(a, list) else [a]
        cand = {str(v) for r in a for v in _vals(rows, r, path) if str(v).startswith(prefix)}
        if cand or any(r.partition(".")[0] in decided for r in a):
            return (next(iter(cand)) if len(cand) == 1 else None), True
    return None, False


def _columns(c):
    """단계 → (열쇠로 쓰이는 칸, 값으로 쓰이는 칸) — 앞은 꼭 읽어야 하고 뒤는 못 읽으면 그 칸만 빈다."""
    join, value = {}, {}
    for s in c["steps"]:
        for r in [x for v in s.get("on", {}).values() for x in EC.refs(v)] + EC.refs(s.get("sfdc_entity", [])):
            if r != EC.FILE:
                join.setdefault(r.partition(".")[0], set()).add(r.partition(".")[2])
    fields = [x for f in (c.get("fields") or {}).values() for x in EC.refs(f["from"])]
    for r in fields + EC.refs(c.get("client_edw", [])) + EC.refs(c["created"]):
        if r != EC.FILE:
            value.setdefault(r.partition(".")[0], set()).add(r.partition(".")[2])
    return join, value


def _read(edw, s, keys, core, extra):
    """단계 표 읽기 — 열쇠 첫 칸 IN + 고정 조건. 칸을 못 읽으면 꼭 필요한 칸만 다시 묻고 값 칸은 하나씩 더해 본다(못 읽은 칸만 비고 경고).
    표 자체를 못 읽으면 optional이면 [] + 경고, 아니면 예외(그 원천 메타 전체가 빔)."""
    where = s.get("where") or {}
    cond = "".join(f"{k} = ? AND " for k in where)
    first = next(iter(s["on"]))

    def ask(cols):
        return edw.q_in(f"SELECT {', '.join(cols)} FROM {s['table']} WHERE {cond}{first} IN ({{IN}})", keys, list(where.values()))

    try:
        return ask(core + extra)
    except Exception as e:
        try:
            rows, ok = ask(core), list(core)
        except Exception:
            if not s.get("optional"):
                raise
            print(f"[edw_meta] 경고: {s['table']}를 못 읽음 — {s['name']} 단계 건너뜀: {type(e).__name__}", file=sys.stderr, flush=True)
            return []
    for col in extra:
        try:
            rows, ok = ask(ok + [col]), ok + [col]
        except Exception as e:
            print(f"[edw_meta] 경고: {s['table']}.{col}을 못 읽음 — 그 칸 없이: {type(e).__name__}", file=sys.stderr, flush=True)
    return rows


def _keys(s, rows, path, decided):
    """단계 하나 · 문서 하나 → 열쇠 묶음 목록(글자 튜플 — on 칸 순서). 열쇠 목록이면 decided에 이 단계를 더할 수 있음."""
    on, prefix = list(s["on"]), str((s.get("when") or {}).get("prefix", ""))
    ref = s["on"][on[0]]
    if len(on) > 1:  # 키 여러 개 — 한 단계의 행마다 칸 값 묶음
        cols = [s["on"][k].partition(".") for k in on]
        tups = [tuple(r.get(cc) for _, _, cc in cols) for r in rows.get(cols[0][0], [])]
        return [tuple(map(str, t)) for t in tups if all(v not in (None, "") for v in t)]
    if isinstance(ref, list):
        k, done = _pick(rows, path, ref, prefix, decided)
        if done:
            decided.add(s["name"])
        return [(k,)] if k else []
    return [(str(v),) for v in dict.fromkeys(_vals(rows, ref, path)) if str(v).startswith(prefix)]


def _resolve(edw, paths, c):
    """원천 하나 — 사슬(steps)을 위에서 아래로 따라가 문서마다 {created_at, client_edw, attrs}. 첫 단계에 행이 없는 문서는 결과 없음."""
    join, value = _columns(c)
    rows = {p: {} for p in paths}  # 문서 → {단계: 행 목록}
    decided = {p: set() for p in paths}  # 문서 → 열쇠 목록으로 정해진 단계
    tz = {s["name"]: UTC for s in c["steps"] if s.get("tz") == "UTC"}
    for i, s in enumerate(c["steps"]):
        name = s["name"]
        if "sfdc_entity" in s:
            for p in paths:
                rows[p][name] = [_entity(_vals(rows[p], s["sfdc_entity"], p))]
            continue
        on = list(s["on"])
        keys = {p: _keys(s, rows[p], p, decided[p]) for p in paths}
        core = list(dict.fromkeys([*on, *(s.get("latest") or []), *sorted(join.get(name, set()) - set(on))]))
        extra = sorted(value.get(name, set()) - set(core))
        firsts = sorted({k[0] for ks in keys.values() for k in ks})
        by_key = {}
        for r in sorted(_read(edw, s, firsts, core, extra) if firsts else [], key=lambda r: tuple(str(v) for v in r.values())):
            by_key.setdefault(tuple(str(r.get(k)) for k in on), []).append(r)
        if s.get("latest"):  # 열쇠마다 가장 큰 행 하나(같으면 앞)
            by_key = {k: [max(v, key=lambda r: tuple(r.get(x) or 0 for x in s["latest"]))] for k, v in by_key.items()}
        for p in paths:
            rows[p][name] = [r for k in keys[p] for r in by_key.get(k, [])]
        if i == 0:
            paths = [p for p in paths if rows[p][name]]
    out = {}
    for p in paths:
        created = (_ts(v, tz.get(r.partition(".")[0])) for r in EC.refs(c["created"]) for v in _vals(rows[p], r, p))
        attrs = {k: _field(rows[p], p, f) for k, f in (c.get("fields") or {}).items()}
        out[p] = {
            "created_at": next((t for t in created if t), None),
            "client_edw": _field(rows[p], p, {"from": c["client_edw"]}) if "client_edw" in c else None,
            "attrs": {k: v for k, v in attrs.items() if v is not None},
        }
    return out


def _field(rows, path, f):
    """attrs 키 하나 — from 열쇠들에서 앞부터 첫 값(형식 바꾼 뒤 빈 값이 아닌 것). type date = 날짜, flag = '1'/'0', max = 앞 몇 자."""
    conv = {"date": _date, "flag": _flag}.get(f.get("type", "text"), lambda v: v)
    for r in EC.refs(f["from"]):
        for v in _vals(rows, r, path):
            v = conv(v)
            if v not in (None, ""):
                return str(v)[: f["max"]] if f.get("max") else v
    return None


def _entity(ents):
    """sfdc_entity 단계 — 운영 analyze_clues 규칙: 연결 없음 unlinked · 모두 User면 user_only · 아니면 첫 User 아닌 연결(운영 확인: 문서마다 ≤1개)."""
    pmap = _prefixes()
    ents = [str(e) for e in ents]
    other = [e for e in ents if pmap.get(e[:3], "") != "User"]
    if not other:
        return {"Class": "unlinked" if not ents else "user_only"}
    etype = pmap.get(other[0][:3], "Unknown:" + other[0][:3])
    return {"Id": other[0], "Type": etype, "Class": ENTITY_CLASS.get(etype, "other")}


def legacy_fetch(docs, edw=None, chain=None):
    """docs = [(source_system, file_path)] → ({file_path: {칸: 값}}, 메타를 못 구한 문서 수). EDW를 못 열면 ({}, len(docs)) + 경고.
    chain — 사슬 설정(기본 load_chain() — 틀리면 ValueError로 멈춤)."""
    chain = chain or legacy_load_chain()
    own = edw is None
    try:
        edw = edw or _Edw()
    except Exception as e:  # 연결 정보 없음·접속 실패 — 메타 없이 적재(사용자 11-02)
        print(
            f"[edw_meta] 경고: EDW를 못 엶 — 문서 메타를 비운 채 적재({len(docs)}건, 나중에 --replace로 다시 적재): {type(e).__name__}",
            file=sys.stderr,
            flush=True,
        )
        return {}, len(docs)
    by_src = {}
    for sys_, path in docs:
        by_src.setdefault(ST.source_of(sys_), []).append(path)
    out = {}
    try:
        for src, paths in by_src.items():
            try:
                out.update({"sfdc": _sfdc, "crms": _crms, "las": _las}.get(src, _plain)(edw, paths, chain))
            except Exception as e:  # 한 원천의 사슬 실패(표·칸 이름 다름 등) — 그 원천만 비움
                print(
                    f"[edw_meta] 경고: {src} 메타 조회 실패 — 그 원천 문서는 메타를 비움({len(paths)}건): {type(e).__name__}: {str(e)[:160]}",
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        if own:
            edw.close()
    return out, sum(1 for _, p in docs if not any(v is not None for v in (out.get(p) or {}).values()))


def _plain(edw, paths, c):
    """FAQ·Other — 등록 시각만(FileStorageMap)."""
    F = c["files"]
    return {
        r["k"]: {"created_at": _ts(r["created_at"])}
        for r in edw.q_in(f"SELECT {F['key']} AS k, {F['created']} AS created_at FROM {F['table']} WHERE {F['key']} IN ({{IN}})", paths)
    }


def _conv(col, v):
    """gold 칸에 맞게 — contract_date는 날짜, created_at은 시각, 그 밖은 그대로."""
    return _date(v) if col == "contract_date" else _ts(v) if col == "created_at" else v


def _ts(v, tz=None):
    """EDW 시각(datetime·'YYYY-MM-DD HH:MM:SS'·'YYYYMMDDHHMMSS') → datetime(시간대 없는 값은 tz — 기본 그대로 두어 적재가 KST로 읽음). 못 읽으면 None."""
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo or tz is None else v.replace(tzinfo=tz)
    t = str(v).strip()
    try:
        d = datetime.strptime(t[:14], "%Y%m%d%H%M%S") if len(t) >= 14 and t[:14].isdigit() else datetime.fromisoformat(t)
    except ValueError:
        return None
    return d if d.tzinfo or tz is None else d.replace(tzinfo=tz)


def _date(v):
    """EDW 날짜(date·datetime·'YYYY-MM-DD…'·'YYYYMMDD…') → date. 못 읽으면 None(DATE 칸에 넣다 적재 전체가 되돌려지지 않게)."""
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    t = str(v).strip()
    try:
        return datetime.strptime(t[:8], "%Y%m%d").date() if t[:8].isdigit() else date.fromisoformat(t[:10])
    except ValueError:
        return None


def _one(values):
    """후보 집합 → 하나면 그 값, 둘 이상이면 None(같은 단계 동률 — 비움), 없으면 None."""
    vs = {v for v in values if v}
    return next(iter(vs)) if len(vs) == 1 else None


def _sfdc(edw, paths, c):
    F, S = c["files"], c["sfdc"]
    V, L, Op, A = S["version"], S["link"], S["opportunity"], S["account"]
    files = edw.q_in(
        f"SELECT f.{F['key']} AS k, f.{F['created']} AS created_at, f.{V['file_col']} AS cv_id, cv.{V['doc']} AS doc_id, "
        f"cv.{V['created']} AS cv_created "
        f"FROM {F['table']} f LEFT JOIN {V['table']} cv ON cv.{V['id']} = f.{V['file_col']} WHERE f.{F['key']} IN ({{IN}})",
        paths,
    )
    links = {}
    for r in edw.q_in(
        f"SELECT {L['doc']} AS d, {L['entity']} AS e FROM {L['table']} WHERE {L['deleted']} = 0 AND {L['doc']} IN ({{IN}}) "
        f"ORDER BY {L['doc']}, {L['entity']}",
        [f["doc_id"] for f in files],
    ):
        links.setdefault(r["d"], []).append(str(r["e"] or ""))
    ents = [e for v in links.values() for e in v]
    opp_pre, acc_pre = S["opp_prefix"], S["account_prefix"]
    looked = [st for st in S["steps"] if "table" in st]  # 단계 표(연결 개체 id → 값)
    val = {}
    for st in looked:
        ids = [e for e in ents if e.startswith(st["prefix"])]
        if not ids:
            continue
        try:
            rows = edw.q_in(f"SELECT {st['id']} AS i, {st['value']} AS v FROM {st['table']} WHERE {st['id']} IN ({{IN}})", ids)
        except Exception as e:
            if not st.get("optional"):
                raise
            print(f"[edw_meta] 경고: {st['table']}를 못 읽음 — {st['prefix']} 단계 건너뜀: {type(e).__name__}", file=sys.stderr, flush=True)
            continue
        val.update({r["i"]: str(r["v"] or "") for r in rows})
    pick = {}
    for f in files:
        le = links.get(f["doc_id"], [])
        steps = [
            [e for e in le if e.startswith(st["prefix"])]
            if "table" not in st
            else [val.get(e, "") for e in le if e.startswith(st["prefix"]) and val.get(e, "").startswith(opp_pre)]
            for st in S["steps"]
        ]
        opp, had_opp = None, False
        for cand in steps:  # 단계 순서대로 — 그 단계에 후보가 있으면 거기서 정함(둘 이상이면 비움)
            if {c for c in cand if c}:
                opp, had_opp = _one(cand), True
                break
        via = [val.get(e, "") for e in le if any(e.startswith(st["prefix"]) for st in looked)]
        acc_steps = [[w for w in via if w.startswith(acc_pre)], [e for e in le if e.startswith(acc_pre)]]
        acc = None
        if not had_opp:  # 기회 후보가 아예 없을 때만 계정 단계로(기회가 동률이면 고객도 비움 — 다른 사슬의 고객을 붙이지 않음)
            for cand in acc_steps:
                if {c for c in cand if c}:
                    acc = _one(cand)
                    break
        pick[f["k"]] = (opp, acc, _ts(f.get("cv_created"), UTC) or _ts(f.get("created_at")))  # SFDC CreatedDate는 UTC
    outs = ", ".join(f"{col} AS o_{g}" for g, col in Op["out"].items())
    opps = {
        r["i"]: r
        for r in edw.q_in(
            f"SELECT {Op['id']} AS i, {Op['account']} AS a, {outs} FROM {Op['table']} WHERE {Op['id']} IN ({{IN}})",
            [o for o, _, _ in pick.values()],
        )
    }
    acc_ids = [(opps.get(o) or {}).get("a") or a for o, a, _ in pick.values()]
    accs = {
        r["i"]: r["n"] for r in edw.q_in(f"SELECT {A['id']} AS i, {A['name']} AS n FROM {A['table']} WHERE {A['id']} IN ({{IN}})", acc_ids)
    }
    out = {}
    for key, (opp, acc, created) in pick.items():
        o = opps.get(opp) or {}
        out[key] = {
            "created_at": created,
            **{g: _conv(g, o.get(f"o_{g}")) for g in Op["out"]},
            "client_edw": accs.get(o.get("a") or acc),
        }
    for key, h in _sfdc_hints(edw, files, links, S).items():
        out.setdefault(key, {}).update(h)
    return out


ENTITY_CLASS = {  # 운영 analyze_clues 그대로 — 개체 종류 → 분류 힌트 갈래(표에 없으면 other)
    "IF_Log__c": "if_log",
    "EventLogFile__c": "event_log",
    "Task": "task",
    "Event": "event",
    "Quote": "quote",
    "Opportunity": "opportunity",
    "Account": "account",
    "Contract": "contract",
    "Dashboard": "dashboard",
    "User": "user_only",
    "Organization": "organization",
}


def _prefixes():
    return json.loads((RES_ROOT / "mappings" / "sfdc_prefix.json").read_text(encoding="utf-8"))["prefixes"]


def _try_rows(edw, sql, values, what):
    """분류 힌트 조회 — 서버 EDW에 칸·표가 없으면 빈 목록 + 경고(그 힌트만 빠지고 적재 메타는 그대로)."""
    try:
        return edw.q_in(sql, values)
    except Exception as e:
        print(f"[edw_meta] 경고: 분류 힌트 {what}를 못 읽음 — 그 힌트 없이: {type(e).__name__}", file=sys.stderr, flush=True)
        return []


def _flag(v):
    """SFDC 체크박스(BIT·bool·글자) → 글자('1'/'0' — 운영 프롬프트의 Real_RFP__c=1과 같게)."""
    return None if v in (None, "") else str(int(v)) if isinstance(v, (bool, int)) else str(v)


def _sfdc_hints(edw, files, links, S):
    """운영 analyze_clues와 같은 규칙 — 연결 없음 unlinked · 모두 User면 user_only · 아니면 첫 User 아닌 연결(운영 확인: 문서마다 ≤1개)."""
    V, H, Op = S["version"], S["hints"], S["opportunity"]
    pmap = _prefixes()
    titles = {
        str(r["i"]): r["t"]
        for r in _try_rows(
            edw,
            f"SELECT {V['id']} AS i, {H['title']} AS t FROM {V['table']} WHERE {V['id']} IN ({{IN}})",
            [str(f["cv_id"]) for f in files],
            "제목",
        )
    }
    pick = {}
    for f in files:
        le = [e for e in links.get(f["doc_id"], []) if e]
        other = [e for e in le if pmap.get(e[:3], "") != "User"]
        h = {"title": titles.get(str(f["cv_id"])), "entity_class": "unlinked" if not le else "user_only"}
        if other:
            e = other[0]
            etype = pmap.get(e[:3], "Unknown:" + e[:3])
            h.update(entity_id=e, entity_type=etype, entity_class=ENTITY_CLASS.get(etype, "other"))
        pick[f["k"]] = h
    by_type = {}
    for h in pick.values():
        by_type.setdefault(h.get("entity_type"), []).append(h.get("entity_id"))
    chan = {}
    for ch in H["channel"]:
        for r in _try_rows(
            edw,
            f"SELECT {ch['id']} AS i, {ch['subject']} AS s, {ch['direction']} AS d FROM {ch['table']} WHERE {ch['id']} IN ({{IN}})",
            by_type.get(ch["type"], []),
            f"{ch['type']} 방향·제목",
        ):
            chan[r["i"]] = r
    Oh = H["opportunity"]
    opp = {
        r["i"]: r
        for r in _try_rows(
            edw,
            f"SELECT {Op['id']} AS i, {Oh['stage']} AS st, {Oh['real_rfp']} AS rr, {Oh['rfp_start']} AS rs, {Oh['rfp_end']} AS re "
            f"FROM {Op['table']} WHERE {Op['id']} IN ({{IN}})",
            by_type.get("Opportunity", []),
            "영업 기회 단계",
        )
    }
    for h in pick.values():  # chan·opp는 그 종류의 id로만 물었으므로 id가 맞으면 종류도 맞음
        c = chan.get(h.get("entity_id"))
        if c:
            h.update(subject=(c["s"] or "")[:120], sent_received__c=c["d"])
        o = opp.get(h.get("entity_id"))
        if o:
            h.update(
                stagename=o["st"],
                real_rfp__c=_flag(o["rr"]),
                rfp_received_start_date__c=_date(o["rs"]),
                rfp_received_end_date__c=_date(o["re"]),
            )
    return pick


def _crms(edw, paths, c):
    F, M, P, D = c["files"], c["crms"]["map"], c["crms"]["project"], c["crms"]["docu"]
    mo, po = M["out"], P["out"]
    sel = [f"m.{col} AS m_{g}" for g, col in mo.items()] + [f"p.{col} AS p_{g}" for g, col in po.items()]
    rows = edw.q_in(
        f"SELECT m.{M['key']} AS k, f.{F['created']} AS created_at, d.{D['created']} AS docu_dt{''.join(', ' + x for x in sel)} "
        f"FROM {M['table']} m JOIN {F['table']} f ON f.{F['key']} = m.{M['key']} "
        f"LEFT JOIN {P['table']} p ON p.{P['contract']} = m.{M['contract']} "
        f"LEFT JOIN {D['table']} d ON d.{D['contract']} = m.{M['contract']} AND d.{D['gate']} = m.{M['gate']} "
        f"AND d.{D['gate_version']} = m.{M['gate_version']} AND d.{D['seq']} = m.{M['seq']} WHERE m.{M['key']} IN ({{IN}})",
        paths,
    )
    return {
        r["k"]: {
            "created_at": _ts(r["docu_dt"]) or _ts(r["created_at"]),
            **{g: _conv(g, r[f"m_{g}"]) for g in mo},
            **{g: _conv(g, r[f"p_{g}"]) for g in po},
        }
        for r in rows
    }


def _las(edw, paths, c):
    F, M, Fm, C = c["files"], c["las"]["map"], c["las"]["file"], c["las"]["contract"]
    rows = edw.q_in(
        f"SELECT m.{M['key']} AS k, f.{F['created']} AS created_at, m.{M['manage_no']} AS manage_no, m.{M['signed']} AS signed_date, "
        f"fm.{Fm['created']} AS file_dt FROM {M['table']} m JOIN {F['table']} f ON f.{F['key']} = m.{M['key']} "
        f"LEFT JOIN {Fm['table']} fm ON fm.{Fm['id']} = m.{M['file_id']} WHERE m.{M['key']} IN ({{IN}})",
        paths,
    )
    contracts = {}
    for k in edw.q_in(
        f"SELECT {C['manage_no']} AS mn, {C['id']} AS cid, {C['active']} AS act, {C['date']} AS dt, {C['client']} AS cl "
        f"FROM {C['table']} WHERE {C['manage_no']} IN ({{IN}})",
        [r["manage_no"] for r in rows],
    ):
        best = contracts.get(k["mn"])  # 최신 판 — active 먼저, 그다음 id 큰 것
        if best is None or (int(k["act"] or 0), k["cid"] or 0) > (int(best["act"] or 0), best["cid"] or 0):
            contracts[k["mn"]] = k
    out = {}
    for r in rows:
        k = contracts.get(r["manage_no"]) or {}
        out[r["k"]] = {
            "created_at": _ts(r["file_dt"]) or _ts(r["created_at"]),
            "contract_id": r["manage_no"] or k.get("cid"),
            "contract_date": _date(k.get("dt")) or _date(r["signed_date"]),
            "client_edw": k.get("cl") or None,  # 지금은 모두 비어 있음(상대사 출처 미정 — G2)
        }
    appr = {  # 분류 힌트(pl-33) — 최신 판 계약의 품의 제목(따로 조회 — 칸이 없으면 이것만 빔)
        r["i"]: r["a"]
        for r in _try_rows(
            edw,
            f"SELECT {C['id']} AS i, {c['las']['hints']['approval']} AS a FROM {C['table']} WHERE {C['id']} IN ({{IN}})",
            [k["cid"] for k in contracts.values()],
            "품의 제목",
        )
    }
    for r in rows:
        out[r["k"]]["approvalname"] = appr.get((contracts.get(r["manage_no"]) or {}).get("cid"))
    return out


def check(path=None):
    """설정 파일만 점검(EDW·PG 안 붙음) — (종료 코드, 한 줄 요약)."""
    try:
        c = load_chain(path)
    except ValueError as e:
        return 1, str(e)
    per = " · ".join(
        f"{s} 단계 {len(c[s]['steps'])}·키 {len(c[s].get('fields') or {})}(거르기 {len(EC.filters(c, s))})" for s in ST.SOURCES
    )
    return 0, f"[edw_meta] 사슬 설정 OK({Path(path) if path else chain_file()}) — {per}"


def main(argv=None):
    import argparse

    from common.core.console import utf8_stdout

    utf8_stdout()
    ap = argparse.ArgumentParser(description="EDW 조인 사슬 설정 점검(pl-29·pl-52) — 파일만 읽고 검사, EDW·PG에 붙지 않음")
    ap.add_argument("--check", action="store_true", required=True, help="설정 파일 검사(필수 — 이 모듈의 유일한 명령)")
    ap.add_argument("--file", help="점검할 파일(없으면 settings.yaml ops.pipeline_paths.edw_chain → 비우면 기본 파일)")
    a = ap.parse_args(argv)
    rc, msg = check(a.file)
    print(msg)  # 한 줄(성공·실패 모두 표준 출력 — 판정은 종료 코드)
    return rc


if __name__ == "__main__":
    sys.exit(main())
