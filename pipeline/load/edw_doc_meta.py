"""적재 때 EDW 조인으로 문서 메타 채우기(pl-29·pl-52, 사용자 11-02·11-03 — 매핑은 적재 몫). 원본 경로(gold doc.file_path = FileStorageMap.s3_key)마다
원천의 사슬을 따라 고객(client_edw)·등록 시각(created_at)·원천 메타(doc.attrs 키)를 구한다 — 외부 파일 file_meta는 쓰지 않는다. 읽기 계정만(SELECT).
사슬(표·칸 이름·단계·SFDC 접두 갈래·attrs 키·거르기 이름·근거 표시)은 설정 파일 resources/config/edw_chain.yaml — 모든 원천이 같은 꼴(steps·fields·
client_edw·created, 머리 주석 참고), 읽기·검사는 common/store/edw_chain.py(검색 MCP와 함께 씀). 코드는 사슬을 따라가는 해석기 하나(_resolve)뿐이다:
단계를 위에서 아래로 — 열쇠(file 또는 앞 단계 칸)로 표를 읽고, 열쇠 목록이면 앞 자리부터 후보가 있는 첫 자리에서 하나로 정하고(둘 이상이면 비움),
when.prefix로 SFDC id 접두 갈래를 고른다. SFDC 분류 힌트의 연결 개체 종류는 접두 표 resources/mappings/sfdc_prefix.json(sfdc_entity 단계).
서버에서 고친 사본은 설정 ops.paths.edw_chain(검색 MCP와 같은 칸 — 비우면 기본 파일, 사용자 11-03). 파일만 점검(EDW·PG 안 붙음): python -m pipeline.load.edw_doc_meta --check [--file F].
EDW를 못 열면 빈 dict와 경고(적재는 메타를 비운 채 계속 — 사용자 11-02, 자동 갱신 없음: 나중에 --replace로 다시 적재해 채움). 한 단계의 칸을 못 읽으면
그 칸만 비고 경고, 표를 못 읽으면 그 원천 메타가 빔(optional 단계면 그 단계만). 설정 파일이 틀리면 ValueError로 멈춘다(이름은 SQL 글자에 들어가므로 검사,
값은 늘 바인딩)."""

import json
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from common.core.paths import RES_ROOT
from common.store import edw_chain as EC
from common.store.db.models import search_tables as ST

CHUNK = 500  # IN 목록 크기


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
    """사슬 설정 읽기 + 검사(common.store.edw_chain) — 틀리면 ValueError. path 없으면 설정 칸(EC.chain_path() — 비우면 기본 파일)."""
    return EC.load(path)


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


def _key(v):
    """열쇠 값 → 글자(앞뒤 공백 뺌 — MSSQL CHAR 채움·int 칸). SQL IN에 넘기는 값."""
    return str(v).strip()


def _norm(v):
    """열쇠 맞추기 — _key + 대소문자 무시(MSSQL 기본 정렬 규칙 CI와 같게 — 옛 SQL 조인과 같은 짝)."""
    return _key(v).casefold()


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
        cand = {_norm(v): _key(v) for r in a for v in _vals(rows, r, path) if _key(v).startswith(prefix)}
        if cand or any(r.partition(".")[0] in decided for r in a):
            return (next(iter(cand.values())) if len(cand) == 1 else None), True
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
        return [tuple(map(_key, t)) for t in tups if all(v not in (None, "") and _key(v) for v in t)]
    if isinstance(ref, list):
        k, done = _pick(rows, path, ref, prefix, decided)
        if done:
            decided.add(s["name"])
        return [(k,)] if k else []
    return [(k,) for k in dict.fromkeys(_key(v) for v in _vals(rows, ref, path)) if k and k.startswith(prefix)]


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
            by_key.setdefault(tuple(_norm(r.get(k)) for k in on), []).append(r)  # 양쪽 모두 _norm(옛 SQL 조인 — CHAR 채움·CI)
        if s.get("latest"):  # 열쇠마다 가장 큰 행 하나(같으면 앞)
            by_key = {k: [max(v, key=lambda r: tuple(_rank(r.get(x)) for x in s["latest"]))] for k, v in by_key.items()}
        for p in paths:
            rows[p][name] = [r for k in dict.fromkeys(tuple(map(_norm, k)) for k in keys[p]) for r in by_key.get(k, [])]
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


def _rank(v):
    """latest 비교 값 — None이 가장 작고, 수는 수로(ContractID 10 > 9), 그 밖은 글자로(날짜·시각은 ISO 글자 순서 = 시간 순서)."""
    if v is None:
        return (0, 0, "")
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
        return (1, 0, v)
    return (1, 1, str(v))


def _field(rows, path, f):
    """attrs 키 하나 — from 열쇠들에서 앞부터 첫 값(형식 바꾼 뒤 빈 값이 아닌 것). type text = 글자(앞뒤 공백 뺌 — int·Decimal·UUID도 글자로,
    JSON에 수로 새지 않게), date = 날짜, flag = '1'/'0', max = 앞 몇 자."""
    conv = {"date": _date, "flag": _flag}.get(f.get("type", "text"), _text)
    for r in EC.refs(f["from"]):
        for v in _vals(rows, r, path):
            v = conv(v)
            if v not in (None, ""):
                return str(v)[: f["max"]] if f.get("max") else v
    return None


def _text(v):
    return None if v is None else str(v).strip()


def _entity(ents):
    """sfdc_entity 단계 — 운영 analyze_clues 규칙: 연결 없음 unlinked · 모두 User면 user_only · 아니면 첫 User 아닌 연결(운영 확인: 문서마다 ≤1개)."""
    pmap = _prefixes()
    ents = [str(e) for e in ents]
    other = [e for e in ents if pmap.get(e[:3], "") != "User"]
    if not other:
        return {"Class": "unlinked" if not ents else "user_only"}
    etype = pmap.get(other[0][:3], "Unknown:" + other[0][:3])
    return {"Id": other[0], "Type": etype, "Class": ENTITY_CLASS.get(etype, "other")}


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


def _flag(v):
    """SFDC 체크박스(BIT·bool·글자) → 글자('1'/'0' — 운영 프롬프트의 Real_RFP__c=1과 같게)."""
    return None if v in (None, "") else str(int(v)) if isinstance(v, (bool, int)) else str(v)


def check(path=None):
    """설정 파일만 점검(EDW·PG 안 붙음) — (종료 코드, 한 줄 요약)."""
    try:
        c = load_chain(path)
    except ValueError as e:
        return 1, str(e)
    per = " · ".join(
        f"{s} 단계 {len(c[s]['steps'])}·키 {len(c[s].get('fields') or {})}(거르기 {len(EC.filters(c, s))})" for s in ST.SOURCES
    )
    return 0, f"[edw_meta] 사슬 설정 OK({Path(path) if path else EC.chain_path()}) — {per}"


def main(argv=None):
    import argparse

    from common.core.console import utf8_stdout

    utf8_stdout()
    ap = argparse.ArgumentParser(description="EDW 조인 사슬 설정 점검(pl-29·pl-52) — 파일만 읽고 검사, EDW·PG에 붙지 않음")
    ap.add_argument("--check", action="store_true", required=True, help="설정 파일 검사(필수 — 이 모듈의 유일한 명령)")
    ap.add_argument("--file", help="점검할 파일(없으면 settings.yaml ops.paths.edw_chain → 비우면 기본 파일)")
    a = ap.parse_args(argv)
    rc, msg = check(a.file)
    print(msg)  # 한 줄(성공·실패 모두 표준 출력 — 판정은 종료 코드)
    return rc


if __name__ == "__main__":
    sys.exit(main())
