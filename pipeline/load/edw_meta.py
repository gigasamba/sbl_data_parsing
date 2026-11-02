"""적재 때 EDW 조인으로 문서 메타 채우기(pl-29, 사용자 11-02 — 매핑은 적재 몫). 원본 경로(gold doc.file_path = FileStorageMap.s3_key)마다
원천별 사슬을 따라 고객(client_edw)·원천 전용 칸·등록 시각(created_at)을 구한다 — 외부 파일 file_meta는 쓰지 않는다. 읽기 계정만(SELECT).
사슬(운영 gold 스키마 노트 — 실제 칸 이름은 DB 담당자 확인, refactor.md C-76 · db_schema §1 원천별 사슬):
- SFDC: FileStorageMap.content_version_id → ContentVersion(Id → ContentDocumentId, CreatedDate) → ContentDocumentLink(IsDeleted=0).LinkedEntityId
  접두로 영업 기회: 006 직접 > 00T Task.WhatId > 00U Event.WhatId > 0Q0 Quote.OpportunityId(표가 없으면 건너뜀) · 고객: 기회.AccountId → Account.Name,
  기회가 없으면 Task/Event.WhatId 001 > LinkedEntityId 001(계정 직접) · 같은 단계에 후보가 둘 이상이면 비움(NULL).
- CRMS: FileStorageMap_CRMS.rm_contract_code → RM_CM_PJTLIST(SF_ACC_NAME·DIVISION·RM_CONTRACT_NAME·INIT_DTTM) · 등록 시각 RM_CM_DOCU.INIT_DTTM(4 키).
- LAS: FileStorageMap_LAS.manage_no → LAS.Contract(최신 판 — IsActive·ContractID 내림차순) · 등록 시각 FileManager.CreateDate(las_file_id).
- FAQ·Other: FileStorageMap.created_at만.
분류 힌트(pl-33, 사용자 11-02 — 운영 analyze_clues와 같은 규칙, gold 칸 이름은 원본 칸 이름의 소문자 — project_code__c처럼): SFDC는 ContentVersion.Title + 첫 번째 User 아닌 연결 개체
(title·entity_type·entity_id·entity_class — 접두 → 개체 표는 resources/mappings/sfdc_prefix.json) + 그 개체가 Task/Event면 Subject(120자)·Sent_Received__c,
영업 기회면 StageName·Real_RFP__c·RFP_Received_Start/End_Date__c. LAS는 Contract.ApprovalName. 힌트 칸을 못 읽는 EDW면 힌트만 비움(경고).
EDW를 못 열면 빈 dict와 경고(적재는 메타를 비운 채 계속 — 사용자 11-02, 자동 갱신 없음: 나중에 --replace로 다시 적재해 채움)."""

import json
import sys
from datetime import UTC, date, datetime

from common.core.paths import RES_ROOT
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

    def q_in(self, sql, values):
        """sql 안의 `{IN}`을 값 목록 자리표시로 — CHUNK개씩 나눠 묻고 행을 합친다."""
        out, values = [], sorted(set(v for v in values if v not in (None, "")))
        for k in range(0, len(values), CHUNK):
            part = values[k : k + CHUNK]
            out += self.q(sql.replace("{IN}", ", ".join(["?"] * len(part))), part)
        return out

    def close(self):
        self.cn.close()


def fetch(docs, edw=None):
    """docs = [(source_system, file_path)] → ({file_path: {칸: 값}}, 메타를 못 구한 문서 수). EDW를 못 열면 ({}, len(docs)) + 경고."""
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
                out.update({"sfdc": _sfdc, "crms": _crms, "las": _las}.get(src, _plain)(edw, paths))
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


def _plain(edw, paths):
    """FAQ·Other — 등록 시각만(FileStorageMap.created_at)."""
    return {
        r["s3_key"]: {"created_at": _ts(r["created_at"])}
        for r in edw.q_in("SELECT s3_key, created_at FROM AI.FileStorageMap WHERE s3_key IN ({IN})", paths)
    }


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


def _sfdc(edw, paths):
    files = edw.q_in(
        "SELECT f.s3_key, f.created_at, f.content_version_id, cv.ContentDocumentId AS doc_id, cv.CreatedDate AS cv_created "
        "FROM AI.FileStorageMap f LEFT JOIN SFDC.ContentVersion cv ON cv.Id = f.content_version_id WHERE f.s3_key IN ({IN})",
        paths,
    )
    links = {}
    for r in edw.q_in(
        "SELECT ContentDocumentId, LinkedEntityId FROM SFDC.ContentDocumentLink WHERE IsDeleted = 0 AND ContentDocumentId IN ({IN}) "
        "ORDER BY ContentDocumentId, LinkedEntityId",
        [f["doc_id"] for f in files],
    ):
        links.setdefault(r["ContentDocumentId"], []).append(str(r["LinkedEntityId"] or ""))
    ents = [e for v in links.values() for e in v]
    what = {}
    for tbl, pre in (("Task", "00T"), ("Event", "00U")):
        for r in edw.q_in(f"SELECT Id, WhatId FROM SFDC.{tbl} WHERE Id IN ({{IN}})", [e for e in ents if e.startswith(pre)]):
            what[r["Id"]] = str(r["WhatId"] or "")
    quote = {}
    qids = [e for e in ents if e.startswith("0Q0")]
    if qids:
        try:
            quote = {r["Id"]: r for r in edw.q_in("SELECT Id, OpportunityId, AccountId FROM SFDC.Quote WHERE Id IN ({IN})", qids)}
        except Exception as e:  # 서버 EDW 복사본에는 Quote 표가 아직 없음(C-76) — 그 단계만 건너뜀
            print(f"[edw_meta] 경고: SFDC.Quote를 못 읽음 — Quote 단계(0Q0) 건너뜀: {type(e).__name__}", file=sys.stderr, flush=True)
    pick = {}
    for f in files:
        le = links.get(f["doc_id"], [])
        task_ev = [what.get(e, "") for e in le if e[:3] in ("00T", "00U")]
        steps = [
            [e for e in le if e.startswith("006")],
            [what.get(e, "") for e in le if e.startswith("00T") and what.get(e, "").startswith("006")],
            [what.get(e, "") for e in le if e.startswith("00U") and what.get(e, "").startswith("006")],
            [str(quote[e]["OpportunityId"] or "") for e in le if e in quote],
        ]
        opp, had_opp = None, False
        for cand in steps:  # 단계 순서대로 — 그 단계에 후보가 있으면 거기서 정함(둘 이상이면 비움)
            if {c for c in cand if c}:
                opp, had_opp = _one(cand), True
                break
        acc_steps = [[w for w in task_ev if w.startswith("001")], [e for e in le if e.startswith("001")]]
        acc = None
        if not had_opp:  # 기회 후보가 아예 없을 때만 계정 단계로(기회가 동률이면 고객도 비움 — 다른 사슬의 고객을 붙이지 않음)
            for cand in acc_steps:
                if {c for c in cand if c}:
                    acc = _one(cand)
                    break
        pick[f["s3_key"]] = (opp, acc, _ts(f.get("cv_created"), UTC) or _ts(f.get("created_at")))  # SFDC CreatedDate는 UTC
    opps = {
        r["Id"]: r
        for r in edw.q_in(
            "SELECT Id, Name, AccountId, Project_Code__c, Record_Type__c, X1st_Contract_Execution_Date__c FROM SFDC.Opportunity WHERE Id IN ({IN})",
            [o for o, _, _ in pick.values()],
        )
    }
    acc_ids = [(opps.get(o) or {}).get("AccountId") or a for o, a, _ in pick.values()]
    accs = {r["Id"]: r["Name"] for r in edw.q_in("SELECT Id, Name FROM SFDC.Account WHERE Id IN ({IN})", acc_ids)}
    out = {}
    for key, (opp, acc, created) in pick.items():
        o = opps.get(opp) or {}
        out[key] = {
            "created_at": created,
            "sf_op_id": o.get("Id"),
            "sf_op_name": o.get("Name"),
            "project_code__c": o.get("Project_Code__c"),
            "service_type": o.get("Record_Type__c"),
            "contract_date": _date(o.get("X1st_Contract_Execution_Date__c")),
            "client_edw": accs.get(o.get("AccountId") or acc),
        }
    hints = _sfdc_hints(edw, files, links)
    for key, h in hints.items():
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


def _hint_rows(edw, sql, values, what):
    """힌트 칸 조회 — 서버 EDW에 칸·표가 없으면 빈 목록 + 경고(힌트만 비고 메타는 그대로)."""
    try:
        return edw.q_in(sql, values)
    except Exception as e:
        print(f"[edw_meta] 경고: 분류 힌트 {what}를 못 읽음 — 그 힌트 없이: {type(e).__name__}", file=sys.stderr, flush=True)
        return []


def _flag(v):
    """SFDC 체크박스(BIT·bool·글자) → 글자('1'/'0' — 운영 프롬프트의 Real_RFP__c=1과 같게)."""
    return None if v in (None, "") else str(int(v)) if isinstance(v, (bool, int)) else str(v)


def _sfdc_hints(edw, files, links):
    """운영 analyze_clues와 같은 규칙 — 연결 없음 unlinked · 모두 User면 user_only · 아니면 첫 User 아닌 연결(운영 확인: 문서마다 ≤1개)."""
    pmap = _prefixes()
    titles = {
        str(r["Id"]): r["Title"]
        for r in _hint_rows(
            edw, "SELECT Id, Title FROM SFDC.ContentVersion WHERE Id IN ({IN})", [str(f["content_version_id"]) for f in files], "Title"
        )
    }
    pick = {}
    for f in files:
        le = [e for e in links.get(f["doc_id"], []) if e]
        other = [e for e in le if pmap.get(e[:3], "") != "User"]
        h = {"title": titles.get(str(f["content_version_id"])), "entity_class": "unlinked" if not le else "user_only"}
        if other:
            e = other[0]
            etype = pmap.get(e[:3], "Unknown:" + e[:3])
            h.update(entity_id=e, entity_type=etype, entity_class=ENTITY_CLASS.get(etype, "other"))
        pick[f["s3_key"]] = h
    by_type = {}
    for h in pick.values():
        by_type.setdefault(h.get("entity_type"), []).append(h.get("entity_id"))
    chan = {}
    for tbl in ("Task", "Event"):
        for r in _hint_rows(
            edw, f"SELECT Id, Subject, Sent_Received__c FROM SFDC.{tbl} WHERE Id IN ({{IN}})", by_type.get(tbl, []), f"{tbl} Subject"
        ):
            chan[r["Id"]] = r
    opp = {
        r["Id"]: r
        for r in _hint_rows(
            edw,
            "SELECT Id, StageName, Real_RFP__c, RFP_Received_Start_Date__c, RFP_Received_End_Date__c FROM SFDC.Opportunity WHERE Id IN ({IN})",
            by_type.get("Opportunity", []),
            "Opportunity StageName",
        )
    }
    for h in pick.values():
        c = chan.get(h.get("entity_id")) if h.get("entity_type") in ("Task", "Event") else None
        if c:
            h.update(subject=(c["Subject"] or "")[:120], sent_received__c=c["Sent_Received__c"])
        o = opp.get(h.get("entity_id")) if h.get("entity_type") == "Opportunity" else None
        if o:
            h.update(
                stagename=o["StageName"],
                real_rfp__c=_flag(o["Real_RFP__c"]),
                rfp_received_start_date__c=_date(o["RFP_Received_Start_Date__c"]),
                rfp_received_end_date__c=_date(o["RFP_Received_End_Date__c"]),
            )
    return pick


def _crms(edw, paths):
    rows = edw.q_in(
        "SELECT m.s3_key, f.created_at, m.rm_contract_code, p.SF_ACC_NAME, p.DIVISION, p.RM_CONTRACT_NAME, p.INIT_DTTM AS contract_dt, d.INIT_DTTM AS docu_dt "
        "FROM AI.FileStorageMap_CRMS m JOIN AI.FileStorageMap f ON f.s3_key = m.s3_key "
        "LEFT JOIN CRMS.RM_CM_PJTLIST p ON p.RM_CONTRACT_CODE = m.rm_contract_code "
        "LEFT JOIN CRMS.RM_CM_DOCU d ON d.RM_CONTRACT_CODE = m.rm_contract_code AND d.GATE_CODE = m.gate_code "
        "AND d.GATE_VERSION = m.gate_version AND d.DOCU_SEQ = m.docu_seq WHERE m.s3_key IN ({IN})",
        paths,
    )
    return {
        r["s3_key"]: {
            "created_at": _ts(r["docu_dt"]) or _ts(r["created_at"]),
            "client_edw": r["SF_ACC_NAME"],
            "division": r["DIVISION"],
            "prod_name": r["RM_CONTRACT_NAME"],
            "contract_id": r["rm_contract_code"],
            "contract_date": _date(r["contract_dt"]),
        }
        for r in rows
    }


def _las(edw, paths):
    rows = edw.q_in(
        "SELECT m.s3_key, f.created_at, m.manage_no, m.signed_date, fm.CreateDate AS file_dt "
        "FROM AI.FileStorageMap_LAS m JOIN AI.FileStorageMap f ON f.s3_key = m.s3_key "
        "LEFT JOIN LAS.FileManager fm ON fm.FileID = m.las_file_id WHERE m.s3_key IN ({IN})",
        paths,
    )
    contracts = {}
    for c in edw.q_in(
        "SELECT ManageNo, ContractID, IsActive, ContractDate, PartnerCorpName FROM LAS.Contract WHERE ManageNo IN ({IN})",
        [r["manage_no"] for r in rows],
    ):
        best = contracts.get(c["ManageNo"])  # 최신 판 — IsActive 먼저, 그다음 ContractID 큰 것
        if best is None or (int(c["IsActive"] or 0), c["ContractID"] or 0) > (int(best["IsActive"] or 0), best["ContractID"] or 0):
            contracts[c["ManageNo"]] = c
    out = {}
    for r in rows:
        c = contracts.get(r["manage_no"]) or {}
        out[r["s3_key"]] = {
            "created_at": _ts(r["file_dt"]) or _ts(r["created_at"]),
            "contract_id": r["manage_no"] or c.get("ContractID"),
            "contract_date": _date(c.get("ContractDate")) or _date(r["signed_date"]),
            "client_edw": c.get("PartnerCorpName") or None,  # 지금은 모두 비어 있음(상대사 출처 미정 — G2)
        }
    appr = {  # 분류 힌트(pl-33) — 품의 제목. 최신 판의 것(ContractID로 짝지음)
        r["ContractID"]: r["ApprovalName"]
        for r in _hint_rows(
            edw,
            "SELECT ContractID, ApprovalName FROM LAS.Contract WHERE ContractID IN ({IN})",
            [c["ContractID"] for c in contracts.values()],
            "ApprovalName",
        )
    }
    for r in rows:
        c = contracts.get(r["manage_no"]) or {}
        out[r["s3_key"]]["approvalname"] = appr.get(c.get("ContractID"))
    return out
