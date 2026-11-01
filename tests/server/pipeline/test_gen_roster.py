"""pipeline.transform.structure.gen_roster 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.structure.gen_roster --selftest`."""

from pathlib import Path

from common.config.settings import COMMON
from common.core import terms as T
from pipeline.transform.structure.gen_roster import (
    ROSTER_COLS,
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

    # --kind client — csv: 추출본 → CLIENT_ROSTER (별칭 합침·결정적 순서)
    (d / "client_master.csv").write_text(
        "company_name,aka\nCelltrion,CT Inc\nCelltrion,셀트리온\nNorthfield Biologics,\n", encoding="utf-8-sig"
    )
    mapping = {"name": "company_name", "aliases": "aka"}
    rows = rows_from_csv(d / "client_master.csv")
    roster = build_roster(rows, mapping)
    assert roster == {"Celltrion": ["CT Inc", "셀트리온"], "Northfield Biologics": []}, roster
    out = d / "CLIENT_ROSTER.csv"
    write_client_roster(roster, out)
    assert out.read_text(encoding="utf-8").splitlines()[0] == ",".join(ROSTER_COLS)  # GL3 — new roster format

    # GL3 — optional columns from the master (id, Korean name, status): inactive rows are dropped by the reader
    (d / "master2.csv").write_text(
        "cust_id,eng,kor,state\nC-1,Acme Bio,에이크미,active\nC-2,Old Pharma,올드,Inactive\n", encoding="utf-8-sig"
    )
    m2 = load_mapping({"name": "eng", "client_id": "cust_id", "name_ko": "kor", "status": "state"})
    rows2 = rows_from_csv(d / "master2.csv")
    out2 = d / "CLIENT_ROSTER2.csv"
    write_client_roster(build_roster(rows2, m2), out2, build_client_extra(rows2, m2), source="csv:master2.csv")
    assert "C-1,Acme Bio,에이크미,,,,,,active,,csv:master2.csv," in out2.read_text(encoding="utf-8")
    assert T.read_roster(out2) == {"Acme Bio": ["에이크미"]}, T.read_roster(out2)  # inactive dropped, name_ko → alias
    with COMMON.env(CLIENT_ROSTER=str(out)):  # op-09 — 인계 파일(terms.py)도 설정 객체로 읽음
        al = T._aliases()
        assert al.get("Celltrion") and set(al["Celltrion"]) == {"CT Inc", "셀트리온"}, al  # 생성 파일을 terms.py가 그대로 읽음

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
    print("[selftest] SI43③ — gen_roster: csv: 추출본→CLIENT_ROSTER(별칭 합침·terms.py가 그대로 읽음)·제품 draft(멱등)·매핑 검증 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
