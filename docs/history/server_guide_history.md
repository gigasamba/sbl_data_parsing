moved from server-guide.md on 10-30, do-04

# 서버 가이드 — 옛 동작 기록

지금 운영에는 영향이 없다. 현재 절차는 [server-guide.md](../operations/server-guide.md).

## §0 이미지·코드 폴더
- 이미지 2개 구성은 S6b(D-020)에서 정했고, 이름은 사용자 10-27에 바꿨다: `data-parsing`·`data-structure` → `data-pipeline`, `data-retrieval` → `mcp-server`. 상주 트리거 컨테이너도 `data-parsing`·`data-structure` → `data-pipeline-parse`·`data-pipeline-structure`.
- `full`은 S6c(10-27) 전에는 두 이미지가 갈라져 있어 거부됐다. `tool index`도 S6c부터 찾는다.
- S6b 전에는 호스트 스크립트·compose·systemd 파일이 `live/app/docker/`에 섞여 있었다.

## §1-2 설정 파일
- S7e1 전에는 설정 파일이 `pipeline.env.example`·`pipeline.env`였다.
- S8b 전 버전의 원천 목록 동작: I4 버전부터 호스트 python(venv·네이티브 실행)은 `SERVER_ENV_DIR`이 있어야 `$SERVER_ENV_DIR/sources.json`을 봤다. 없으면 안내 없이 코드 폴더의 기본 `resources/mappings/sources.json`(S2 전에는 `common_tools/runtime/sources.json`)을 썼다. I4 전에는 `/srv/rag/env/sources.json`이 있으면 늘 우선했다. S8b(D-031)부터는 버전 표를 쓰고 이 파일 덮어쓰기는 읽지 않는다.
- 값 바꾸기 규칙: S7e3(사용자 10-28)에 정함. `--set`은 S9 Step A(사용자 10-28). 옛 env 이름 덮어쓰기 무효화는 S7e2. 오버레이 설정 파일 도구 서버 거부는 VS7e2 B-2. 하위 셸 `( … )` 권고는 VS7e1 R-2.
- 옛 env `CLIENT_ROSTER`·`GLOSSARY_DIR`은 S7e2부터 읽지 않는다. compose에 `/srv/rag/env/` 마운트가 없는 것은 리팩토링 전부터다.

## §1-3 selftest
- 알려진 FAIL은 S9b 전에는 2개였다.

## §2-4 테스트 스크립트
- `validation.e2e.answer_gen`은 S10 전에는 `answer_gen_test.py`였다.

## §5 회사 맞춤
- 정답 세트 `valid_env/eval_sets/`는 10-30에 지웠다. `pipeline.host.gold_dir` 마운트는 S7e3.
