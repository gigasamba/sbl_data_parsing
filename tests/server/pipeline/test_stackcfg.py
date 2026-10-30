"""pipeline.stackcfg 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.stackcfg --selftest`."""

import json
from unittest import mock

from pipeline.stackcfg import EXIT_BAD_ENGINE, engine_problems, engines_of, require_engines, snapshot_bytes


def selftest():

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
    b = cfgtables.Active("stack", 3, "t", dict(reversed(list(body.items()))), a.body_sha, "시험")
    assert snapshot_bytes(a) == snapshot_bytes(b)  # 키 순서 달라도 같은 바이트(색인 재빌드 지문 index_cfg.inputs가 씀)
    snap = json.loads(snapshot_bytes(a))
    assert snap["version_id"] == 3 and snap["parse"] == body["parse"] and snap["body_sha"] == a.body_sha
    # 시드 판(0002 — 한 번 배포하면 고치지 않음)이 모양 검사를 지나고 엔진 이름이 모두 등록부에 있음. PC 파일(resources/config/pipeline_stack.json)과
    # 같은지는 보지 않는다 — PC 기본값을 고친 패치가 반입 관문에서 막히지 않게(VS8b R-2, 시드 = 924a51b 파일은 VS8b ⑤에서 확인)
    from pipeline.extract.engines import registry

    name, reason, seed = cfgtables.seed("stack")
    assert set(seed) <= set(CB.STACK_BODY_KEYS) and name and reason
    unknown = [e for e in engines_of(seed) if e not in registry.engines()]
    assert not unknown, f"시드 판에 등록부에 없는 엔진: {unknown}"
    # pl-32 — 사본 파일 대신 판 번호: 서버는 넘겨받은 판(STACK_VERSION)을 판 표에서, 번호가 없으면 거부(종료 2), PC는 파일
    from common.core import paths
    from pipeline import config as pc

    v5 = cfgtables.Active("stack", 5, "v5", {**body, "k": 5}, cfgtables.sha({**body, "k": 5}), "db 시험")
    keep = dict(cfgtables._CACHE)
    try:
        cfgtables._CACHE[("stack", 5)] = v5  # 판 5(넘겨받은 판) — 활성 판(_CACHE["stack"])과 다름
        cfgtables._CACHE["stack"] = a
        with mock.patch.object(paths, "LOCAL_RUN", False):
            assert pc.stack(5)["version_id"] == 5 and pc.stack(5)["k"] == 5
            with pc.PIPE.env(STACK_VERSION="5"):
                assert pc.stack()["name"] == "v5"  # 인자 없으면 넘겨받은 칸
            with pc.PIPE.env(STACK_VERSION=None):
                try:
                    pc.stack()
                    raise AssertionError("서버에서 판 번호 없이 엔진 구성을 읽음")
                except SystemExit as e:
                    assert e.code == 2
        with mock.patch.object(paths, "LOCAL_RUN", True):
            assert pc.stack(5)["version_id"] == 3  # PC는 판 번호를 무시하고 활성 자리(파일 — 여기서는 캐시에 넣은 a)
    finally:
        cfgtables._CACHE.clear()
        cfgtables._CACHE.update(keep)
    print(
        "[selftest] stackcfg — 엔진 집합(parse ∪ candidates)·없는 엔진 거부(종료 2)·같은 body → 같은 바이트·시드 모양·엔진·판 번호(넘겨받은 판·서버 거부·PC 파일) 통과"
    )
    return 0


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    raise SystemExit(selftest())
