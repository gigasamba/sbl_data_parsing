"""pipeline.stackcfg 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.stackcfg --selftest`."""

import json
import os

from pipeline.stackcfg import EXIT_BAD_ENGINE, engine_problems, engines_of, require_engines, reuse, snapshot_bytes, write_snapshot


def selftest():
    import tempfile

    from common.store.db import cfgtables
    from common.store.db.schemas import config_body as CB

    body = {
        "parse": {".txt": ["plaintext"]},
        "embed": "api",
        "chunk": "structure",
        "graph": "table+entity",
        "retrieve": "hybrid",
        "k": 10,
        "candidates": ["markitdown"],
    }
    assert engines_of(body) == ["markitdown", "plaintext"] and not engine_problems(body)
    bad = {**body, "candidates": ["no_such_engine_xyz"]}
    probs = engine_problems(bad)
    assert len(probs) == 1 and "등록 안 됨" in probs[0], probs
    try:
        require_engines(bad, "시험")
        raise AssertionError("없는 엔진인데 거부 안 됨")
    except SystemExit as e:
        assert e.code == EXIT_BAD_ENGINE
    a = cfgtables.Active("stack", 3, "t", body, cfgtables.sha(body), "시험")
    with tempfile.TemporaryDirectory() as td:
        p1 = write_snapshot(a, td)
        p2 = write_snapshot(cfgtables.Active("stack", 3, "t", dict(reversed(list(body.items()))), a.body_sha, "시험"), td)
        assert (
            p1.name == f"stack-v3-{a.body_sha[:8]}.json" and p1 == p2 and p1.read_bytes() == snapshot_bytes(a)
        )  # 키 순서 달라도 같은 바이트
        snap = json.loads(p1.read_text(encoding="utf-8"))
        assert snap["version_id"] == 3 and snap["parse"] == body["parse"] and snap["body_sha"] == a.body_sha
        assert write_snapshot(cfgtables.Active("stack", None, "t", body, a.body_sha, "f"), td).name.startswith("stack-vfile-")
    # 시드 판(0002 — 한 번 배포하면 고치지 않음)이 모양 검사를 지나고 엔진 이름이 모두 등록부에 있음. PC 파일(resources/config/pipeline_stack.json)과
    # 같은지는 보지 않는다 — PC 기본값을 고친 패치가 반입 관문에서 막히지 않게(VS8b R-2, 시드 = 924a51b 파일은 VS8b ⑤에서 확인)
    from pipeline.extract.engines import registry

    name, reason, seed = cfgtables.seed("stack")
    assert set(seed) <= set(CB.STACK_BODY_KEYS) and name and reason
    unknown = [e for e in engines_of(seed) if e not in registry.engines()]
    assert not unknown, f"시드 판에 등록부에 없는 엔진: {unknown}"
    # 결과 폴더에 쓴 사본 다시 쓰기(run_docs 구조화 — R-1): 없으면 None, 있으면 가장 새 것
    with tempfile.TemporaryDirectory() as td:
        assert reuse(td) is None
        old = write_snapshot(cfgtables.Active("stack", 1, "t", body, a.body_sha, "시험"), td)
        os.utime(old, (1, 1))
        new = write_snapshot(cfgtables.Active("stack", 2, "t", body, a.body_sha, "시험"), td)
        assert reuse(td)[0] == new and reuse(td)[1]["version_id"] == 2
        os.utime(new, (2, 2))  # VS9 R-2 — v1 → v2 → v1(--activate 1): 같은 바이트인 v1을 다시 쓰면 그것이 가장 새 것
        again = write_snapshot(cfgtables.Active("stack", 1, "t", body, a.body_sha, "시험"), td)
        assert again == old and reuse(td)[0] == old and reuse(td)[1]["version_id"] == 1
    print(
        "[selftest] stackcfg — 엔진 집합(parse ∪ candidates)·없는 엔진 거부(종료 2)·사본 파일(같은 판·body → 같은 이름·바이트)·시드 모양·엔진·폴더 사본 다시 쓰기 통과"
    )
    return 0


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    raise SystemExit(selftest())
