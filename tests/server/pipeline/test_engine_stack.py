"""pipeline.extract.engine_stack 시험."""

from unittest import mock

from pipeline.extract.engine_stack import EXIT_BAD_ENGINE, engine_problems, engines_of, require_engines


def selftest():

    from common.store.db import cfgfile

    body = {
        "parse": {".txt": ["plaintext"]},
        "embed": "api",
        "chunk": "structure",
        "graph": "table+entity",
        "retrieve": "hybrid",
        "k": 10,
    }
    assert engines_of({**body, "parse": {".txt": ["plaintext", "markitdown"]}}) == ["markitdown", "plaintext"] and not engine_problems(body)
    bad = {**body, "parse": {".txt": ["no_such_engine_xyz"]}}
    probs = engine_problems(bad)
    assert len(probs) == 1 and "등록 안 됨" in probs[0], probs
    try:
        require_engines(bad, "시험")
        raise AssertionError("없는 엔진인데 거부 안 됨")
    except SystemExit as e:
        assert e.code == EXIT_BAD_ENGINE
    assert cfgfile.sha(body) == cfgfile.sha(dict(reversed(list(body.items()))))  # 키 순서 달라도 같은 sha(서버·PC 같은 값)
    # 사용자 11-01 — 서버도 저장소 파일(resources/config/pipeline_stack.json)을 읽는다: 그 파일이 모양 검사를 지나고 엔진 이름이 모두 등록부에 있음
    from common.core import paths
    from common.core.paths import STACK_FILE
    from pipeline import config as pc
    from pipeline.extract.engines import registry

    shipped = cfgfile.read_file("stack", STACK_FILE)
    unknown = [e for e in engines_of(shipped.body) if e not in registry.engines()]
    assert not unknown, f"엔진 구성 파일에 등록부에 없는 엔진: {unknown}"
    keep = dict(cfgfile._CACHE)
    try:
        cfgfile._CACHE.pop("stack", None)
        with mock.patch.object(paths, "LOCAL_RUN", False):  # 서버 길 = PC와 같은 파일(판 번호 없음)
            got = pc.stack()
        assert got["body_sha"] == shipped.body_sha and "version_id" not in got, got.get("name")
    finally:
        cfgfile._CACHE.clear()
        cfgfile._CACHE.update(keep)
    print(
        "[selftest] engine_stack — 엔진 집합(parse 합집합)·없는 엔진 거부(종료 2)·같은 body → 같은 sha·저장소 파일 모양·엔진·서버도 같은 파일 통과"
    )
    return 0


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    raise SystemExit(selftest())
