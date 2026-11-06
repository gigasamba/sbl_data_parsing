"""pipeline.transform.structure.roster_from_edw 시험."""

from pathlib import Path

from common.core import terms as T
from common.store import master as M
from pipeline.transform.structure.roster_from_edw import (
    build_client_extra,
    build_roster,
    check_roster,
    load_mapping,
    rows_from_csv,
    write_client_roster,
)


def selftest():
    import tempfile

    d = Path(tempfile.mkdtemp())

    def clients(path):  # glossary.csv → {정식 이름: [별칭…]}(terms가 마스터에서 읽는 것과 같은 규칙)
        return T._merge_roster(T._roster_dicts(M.Master(M.read_csv(path)).rows("client_roster")))

    # --kind client — csv: 추출본 → glossary.csv 고객 줄(별칭 합침·결정적 순서)
    (d / "client_master.csv").write_text(
        "company_name,aka\nCelltrion,CT Inc\nCelltrion,셀트리온\nNorthfield Biologics,\n", encoding="utf-8-sig"
    )
    mapping = {"name": "company_name", "aliases": "aka"}
    rows = rows_from_csv(d / "client_master.csv")
    roster = build_roster(rows, mapping)
    assert roster == {"Celltrion": ["CT Inc", "셀트리온"], "Northfield Biologics": []}, roster
    out = d / "glossary.csv"
    write_client_roster(roster, out)
    assert out.read_text(encoding="utf-8").splitlines()[0] == ",".join(M.COLS)  # op-17 — glossary 꼴(master load가 그대로 읽음)

    # GL3 — optional columns from the master (id, Korean name, status): inactive rows are dropped by the reader
    (d / "master2.csv").write_text(
        "cust_id,eng,kor,state\nC-1,Acme Bio,에이크미,active\nC-2,Old Pharma,올드,Inactive\n", encoding="utf-8-sig"
    )
    m2 = load_mapping({"name": "eng", "client_id": "cust_id", "name_ko": "kor", "status": "state"})
    rows2 = rows_from_csv(d / "master2.csv")
    out2 = d / "glossary2.csv"
    write_client_roster(build_roster(rows2, m2), out2, build_client_extra(rows2, m2), source="csv:master2.csv")
    acme = M.Master(M.read_csv(out2)).rows("client_roster")[0]
    assert (acme["client_id"], acme["name_ko"], acme["status"], acme["source"]) == ("C-1", "에이크미", "active", "csv:master2.csv"), acme
    assert clients(out2) == {"Acme Bio": ["에이크미"]}, clients(out2)  # inactive dropped, name_ko → alias
    al = clients(out)
    assert al.get("Celltrion") and set(al["Celltrion"]) == {"CT Inc", "셀트리온"}, al
    # 있는 glossary.csv — 고객 줄만 바꾸고 용어·ID 꼴 줄은 그대로
    term = dict(zip(M.COLS, ("term", "Drug Substance", "PROC.DS", "concept_id", "", "", "")))
    M.write_csv([dict(zip(M.COLS, ("client", "Gone Bio", "G1", "client_id", "", "", ""))), term], out2)
    write_client_roster(roster, out2)
    assert clients(out2) == clients(out) and [r for r in M.read_csv(out2) if r["kind"] != "client"] == [term]
    try:  # glossary 꼴이 아닌 파일은 덮지 않음
        write_client_roster(roster, d / "client_master.csv")
        raise AssertionError("glossary 꼴이 아닌 파일을 덮음")
    except SystemExit:
        pass
    assert check_roster(out)[0] == [] and check_roster(out)[2] == 2  # --check는 glossary.csv도 읽음

    # E15 — --check: cp949(한국어 Excel) 읽힘·짧은 영문 별칭 무시·별칭 충돌·같은 이름 여러 줄 경고, 빈 명부는 오류
    chk = d / "sfdc_export.csv"
    chk.write_bytes("고객,별칭\n셀트리온,Celltrion;CT;셀트\n셀트리온,셀트리온헬스\n한라바이오,셀트|HRB\n".encode("cp949"))
    errs, warns, n = check_roster(chk)
    assert errs == [] and n == 2, (errs, n)
    joined = "\n".join(warns)
    assert "cp949" in joined and "같은 이름 2줄" in joined and "CT, HRB" in joined and "'셀트'를 고객 2곳" in joined, warns
    assert T.read_roster(chk)["셀트리온"] == ["Celltrion", "셀트", "셀트리온헬스"]  # CT(2자) 빠짐
    (d / "empty.csv").write_text("name,aliases\n", encoding="utf-8")
    assert check_roster(d / "empty.csv")[0] == ["고객 0건(머리글만 있거나 1열이 비어 있음)"]
    assert check_roster(d / "없음.csv")[0][0].startswith("읽기 실패")

    # --kind product — 제품 마스터 → output/ draft CSV(GLOSSARY_DIR 아님, 독립 검토 BLOCK 1) — 두 번째 호출은 새 행 없이 카운트만 증가
    draft_out = d / "output" / "domain_terms_draft_product.csv"
    added1 = T.write_draft_terms(["MRH-MAB-01", "MRH-ADC-02"], draft_out, category="product_example")
    assert added1 == ["MRH-ADC-02", "MRH-MAB-01"], added1  # 결정적 순서(이름 오름차순)
    draft = T.load_draft_glossary(draft_out)
    assert len(draft) == 2 and all(r["category"] == "product_example" for r in draft.values())
    added2 = T.write_draft_terms(["MRH-MAB-01"], draft_out, category="product_example")
    assert added2 == []  # 이미 있음 — 새 행 없음(카운트만 +1), 멱등

    # mapping 검증 — name 없음·화이트리스트 밖
    try:
        load_mapping({"aliases": "x"})
        raise AssertionError("name 없는 매핑이 통과함")
    except ValueError:
        pass
    try:
        load_mapping({"name": "x;drop"})
        raise AssertionError("식별자 아닌 name이 통과함")
    except ValueError:
        pass
    print(
        "[selftest] SI43③ — gen_roster: csv: 추출본→glossary 고객 줄(별칭 합침·있는 파일은 고객 줄만 바꿈)·제품 draft(멱등)·매핑 검증 통과"
    )


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
