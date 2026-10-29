"""대체판(superseded) 판정 단일 규칙(AR4②) — "이 레코드가 더 최신판으로 대체됐나"를 한 곳에서.
aggregate.doc_location_list(doc_location SQL 기반, AD45①)가 이 모듈을 거친다(manifest 기반 do_list_documents는 10-30 지움 — e2-18) — 전에는 같은 패턴(supersedes_doc_id를 모아 집합을 만들고, 레코드 자신의
doc_id가 그 집합에 있으면 구판으로 판정)이 두 곳에 따로 적혀 있었다. 두 호출자는 데이터 원천이 다르다
(manifest.jsonl의 레코드 vs doc_location 테이블의 행)지만 doc_id·supersedes_doc_id 필드 모양은 같아서 레코드
dict 리스트만 받으면 된다.

retriever.py가 hits에 싣는 `superseded`(dev/common/docmeta.py의 is_superseded·doc_meta, L3-1)는 **다른
결정**이다 — 여기서 판정하는 "manifest/doc_location 체인상 이 문서를 가리키는 더 최신판이 있다"가 아니라
"이 문서 본문 자체에 구판 표지어([구판]·superseded·obsolete)가 있다"이다. 데이터 원천(manifest·SQL 레코드
vs 본문 텍스트)도 쓰이는 곳(목록에서 뺄지 vs 검색 결과 순위 조정·표시)도 달라 합치지 않는다 —
docmeta.recency_rerank가 그 결정을 계속 맡는다.

엣지 케이스(독립 검토 지적, 동작 유지 — 고치지 않음): 최신판 자신이 is_deleted면 그 문서군(family) 전체가
목록에서 사라진다. superseded_set()은 is_deleted 여부와 무관하게 전체 레코드에서 만들어지므로(최신판이
구판을 가리키는 supersedes_doc_id는 최신판 자신의 is_deleted와 무관하게 그대로 집합에 들어간다) 구판은
여전히 그 집합에 걸려 제외되고, 최신판은 자신의 is_deleted로 따로 제외된다 — 둘 다 빠져 체인 전체가 안
보인다. latest_only를 꺼서 구판을 다시 보여도 최신판 자신은 include_deleted를 켜야만 돌아온다."""


def superseded_set(records, key="supersedes_doc_id"):
    """records(dict 리스트, supersedes_doc_id 필드가 있는 것 — manifest.jsonl 레코드 또는 doc_location 행) →
    대체된(구판) doc_id 집합. is_deleted 여부와 무관하게 전체 레코드에서 만든다(모듈 docstring 엣지 케이스)."""
    return {r[key] for r in records if r.get(key)}


def is_superseded(doc_id, superseded):
    """단일 규칙: doc_id가 superseded_set()의 결과 안에 있으면 구판(대체됨)."""
    return doc_id in superseded
