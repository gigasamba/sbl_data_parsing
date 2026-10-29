"""인계 지문(FINGERPRINT)·지문용 옛 이름 대응표(legacy_names)·인계 형식 버전(CONTRACT)·판 표기(pipeline_version).
S3(10-26, refactor_plan 4-3·D-001) — 옛 common_tools/__init__.py에서 그대로 옮김(값·동작 그대로 — FINGERPRINT 87588ce7c88d70ee).
HANDOFF_FILES·_unclassified의 기준 폴더는 이 파일의 폴더(core/)가 아니라 공용 패키지 루트(common/) — 이름은 'core/…'.
common/__init__.py가 CONTRACT·FINGERPRINT·legacy_names·pipeline_version을 다시 내보낸다(`from common import CONTRACT` —
HANDOFF 파일 core/contract.py의 import 줄이 그대로여야 지문이 같다).

FINGERPRINT = HANDOFF_FILES(이 폴더의 일부 .py만) 내용의 지문 — 모듈 끝 표시(_DONE.json)에 남기고 다음 모듈이
자기 것과 비교해, 다른 커밋으로 만든 이미지끼리 규칙이 어긋나면(예: 토큰 규칙만 바뀐 구조화 이미지) 시작을
거부한다(종료 코드 3). RV10(10-09, 리뷰 후속) — 예전엔 common/*.py 전부를 지문에 넣어 atomic.py·paths.py·
artifacts.py 캐시 정리·embed.py 질의 캐시처럼 인계 내용과 무관한 파일을 고쳐도 지문이 바뀌어 다음 모듈이
거부해(종료 코드 3) 서버가 멀쩡한 결과를 다시 파싱해야 했다(10-09 실측). 이제는 HANDOFF_FILES(아래, 선정
기준 주석 포함)만 본다 — 새 common/**/*.py(S4부터 하위 폴더 포함)를 추가하면 HANDOFF_FILES나 EXCLUDED_FILES 둘 중
하나에 넣어야 한다(안 넣으면 import 때 바로 거부 — _unclassified()).
사용: python -m common.__init__ --selftest(이 파일 selftest — 직접 -m으로 돌리면 패키지가 먼저 import해 runpy 경고가 남)
"""

import hashlib
from pathlib import Path

CONTRACT = 2  # 인계 파일 형식 버전 — 형식이 바뀌면 올림(지문은 코드가 바뀌면 자동으로 바뀜)

_ROOT = Path(__file__).resolve().parent.parent  # 공용 패키지 루트(common/) — HANDOFF_FILES·_unclassified·PATCH_VERSION 기준

# 선정 기준(RV10) — parse→structure·structure→load 두 경계 양쪽이 **같은 값을 각자 계산해서 맞춰야 하는** 파일만.
# 한쪽 모듈만 내부적으로 쓰거나(결과를 다른 쪽이 다시 계산해 맞출 필요가 없음) 연결·캐시·로그 같은 운영 코드는
# EXCLUDED_FILES로 뺀다 — 포함 기준을 넓게 잡을수록 이 파일들이 조금만 바뀌어도 앞 모듈을 다시 돌려야 해서(위
# 사고가 그 예) 일부러 좁게 잡았다. 각 파일 이유는 EXCLUDED_FILES 옆 주석.
HANDOFF_FILES = (
    "core/contract.py",  # 인계 형식 자체(_rep REP_KEYS·bundle CHUNK_KEYS/DOC_KEYS 스키마, jl() 읽기) + doc_key(file_sha256)·chunk_key
    # (CT1 — 옛 contract.py·ids.py 병합) — structure·load가 시작 전에 이걸로 거부 판정, parse·structure가 독립적으로 다시 계산해 맞춤
    "core/repfmt.py",  # (라벨,값) 쌍 추출·계약번호/고객 정규식 — parse(crosscheck→_rep meta.pairs)가 뽑고 structure(build_bundle.py AQ.pick)가 같은 규칙으로 해석(engine-qa RV10 BLOCK)
    "core/terms.py",  # 고객 명부·별칭·모달리티 — modules/parse(post/fuse.py 융합)·structure(사실 추출)·load(structured.py 계약 연결)가 "같은 규칙"으로 명시(docstring)
    "core/text.py",  # 토큰·정규화 규칙 — structure(색인 본문 chunk_term)·search(질의 토큰)이 반드시 같아야 함(docs/architecture.md §2)
)

# 나머지 common/**/*.py — 핸드오프(=parse→structure의 _rep·structure→load의 bundle) 내용·해석과 무관(연결·캐시·로그·
# 운영 설정), 또는 두 모듈 중 한쪽만 내부적으로 써서 이미지 사이에 맞출 값이 없음. 새 파일을 추가하면 이유를
# 적어 이 목록이나 HANDOFF_FILES에 넣는다(_check_classified가 둘 다에 없으면 거부).
EXCLUDED_FILES = (
    "__init__.py",  # 패키지 입구(S3 — fingerprint를 부르고 다시 내보내기만 · S7e2 영구 다리 settings.pin_env를 부름)
    "ai/__init__.py",  # 하위 패키지 입구(빈 파일 — S4부터 _unclassified가 하위 폴더까지 봄)
    "check/__init__.py",  # 하위 패키지 입구(빈 파일)
    "config/__init__.py",  # 하위 패키지 입구(빈 파일)
    "core/__init__.py",  # 하위 패키지 입구(빈 파일)
    "store/__init__.py",  # 하위 패키지 입구(빈 파일)
    "check/check_modules.py",  # 모듈 경계 점검 — 개발·반입 점검 도구, 인계 내용과 무관
    "check/os_put.py",  # 시험용 Object Storage 올리기 — 운영 도구
    "check/ping_models.py",  # 모델 연결 확인 — 운영 도구
    "core/exitclean.py",  # 종료 정리(pl-27 — 임시 파일 지우기·자식 회수) — 프로세스 관리, 인계 내용과 무관
    "core/console.py",  # CLI 표준 출력을 UTF-8로(S12 /simplify — utf8_stdout) — 화면 출력만, 인계 내용과 무관
    "core/fingerprint.py",  # 이 파일 자신(S3 — 옛 __init__.py) — CONTRACT는 따로 버전으로 확인, pipeline_version()은 인계 내용과 무관
    "config/boot.py",  # 컨테이너 시작 설정(S7e2 — entrypoint의 RUN_ENV 관문·셸 칸·라이브러리 env) — 운영 도구
    "config/overrides.py",  # 덮기 파일 만들기(S7e2 — PC 한 번 실행) — 운영 도구
    "config/setarg.py",  # 명령 인자 --set 이름=값(S9 Step A — 한 번 실행 덮기, 서버 포함) — 운영 설정, 인계 내용과 무관
    "config/keyscan.py",  # 설정 키 모으기(S7a) — 개발 점검 도구, 인계 내용과 무관
    "config/settings.py",  # settings.yaml 읽기·common 절 모델(S7a, D-015) — 운영 설정, 인계 내용과 무관
    "config/export.py",  # 설정 절 → KEY=VALUE(셸·compose 다리, S7a) — 운영 도구
    "config/migrate.py",  # 옛 env 파일 → settings.yaml(S7a) — 운영 도구
    "config/sample.py",  # settings.sample.yaml 만들기·대조(S7a) — 개발 도구
    "config/show.py",  # 앱 설정 확인 명령(S7a) — 운영 도구
    "ai/adk.py",  # LLM·VLM 호출 메커니즘(세션·재시도) — 생성된 글자 자체는 agent_prompts(별도로 agent_platform._package_digest가 추적)·모델 설정이 결정
    "ai/agent_prompts.py",  # 지시문 글자 변경은 agent_platform.pipeline._package_digest가 이미 따로 추적(여기서 또 볼 필요 없음)
    "core/artifacts.py",  # 실험 저장소 계약(code_fp·캐시 정리) — cli/stack_matrix.py·파싱 이식 도구 전용, parse↔structure↔load 런타임 핸드오프 밖
    "core/docmeta.py",  # structure(build_bundle.py)↔search(retriever.py) 전용(날짜·구판 판정) — parse·load는 안 씀, 이 FINGERPRINT가 보는 두 경계(parse→structure·structure→load) 밖
    "ai/embed.py",  # 임베딩 계산은 structure(쓰기)·search(질의)가 맞아야 하지만 search는 이 FINGERPRINT 경계 밖(MARK에 없음)이라 넣어도 그 위험을 못 막고,
    # 질의 캐시 코드(RV1)가 내용과 무관하게 자주 바뀌어 넣으면 그 캐시 수정마다 재파싱을 유발(10-09 사고). structure 쪽 재사용 판정은 common/artifacts.code_fp("s")가 이미 embed.py를 따로 잡음(cli/index.py)
    "ai/guard.py",  # 내부망 확인(허용/거부) — 통과하면 호출 내용을 바꾸지 않음, _rep/bundle 바이트·해석과 무관
    "core/index_cfg.py",  # 색인 설정·주소(index_id·PG 스키마) — search·cli/index.py 전용, parse·structure·load 경계 밖
    "ai/llm.py",  # LLM 클라이언트(재시도·캐시·예산) — 호출 메커니즘 + 모델 프로필(주소·이름) env 조회(CT1 — 옛 models.py 병합)
    "core/meaning.py",  # 유의미 토큰 — parse 내부(대표 선정·QA)·structure 내부(쪽 번호 제거) 각자 전용, 서로 맞출 공유 값이 없음(CT1 — text.py와 tokens() 이름이 겹쳐 병합 안 하고 그대로 둠)
    "store/mssql.py",  # S8b — 회사 DB(SQL Server) SQLAlchemy 연결 — 연결 방법만
    "store/objectstore.py",  # Object Storage(S3) 연결 설정
    "store/parsing_meta_db.py",  # EDW AI.ParsingMeta 메타 저장 — 운영 기록, 핸드오프 내용 아님
    "core/paths.py",  # cli 평가 도구 경로 기본값 + 원자적 파일 쓰기 헬퍼(CT1 — 옛 atomic.py 병합, 쓰는 방식만·내용은 안 바꿈)
    "store/pg.py",  # PostgreSQL 연결 설정
    "store/pg_standin.py",  # AD41 — pg.py의 연결 정보 없을 때 스탠드인(sqlite) — 연결 방법만, 핸드오프 내용과 무관(pg.py가 shared라 같이 있음)
    "store/registry.py",  # 문서 대장(doc_registry) — 기존 산출물을 읽기만, 핸드오프 스키마를 바꾸지 않음
    "core/resources.py",  # 실행 자원(CPU·메모리) 판단 — 병렬 수 결정만
    "core/runlog.py",  # 실행 로그(output/RUNLOG.md 등)
    "store/services.py",  # 외부 서비스 탐색(Docker pgvector 등) — 연결 방법만
    "core/sources.py",  # 수집(ingest) 원천 표 목록 — parse 이전 단계(수집 서버), 모듈 핸드오프 밖
    "store/structdb.py",  # 로컬 정형 저장소(EDW 시뮬레이션) 스키마 — _rep/bundle/색인과 별도인 표
    "store/db/",  # S8a — pgvector 표 정의·행 모양·Alembic 판·migrate 명령(폴더째 — "/"로 끝나면 그 아래 전부). DB 표 모양만,
    # _rep/bundle 내용과 무관 · 판을 더할 때마다 이 파일을 고치지 않게(이 파일은 모든 층의 공용 의존 — code_fp)
)
# 10-14 모듈 소유 정리(MOD) — qa_log.py·synth_score.py는 data_retrieval 전용이라 그쪽으로 옮김(여기 두 목록에서 빠짐).
# numcheck.py는 git grep 기준 실사용자가 없어(research.py가 호출 안 함) 지움.
# CT1(10-16) — common_tools 하위를 역할 묶음(model/·store/·contract/·runtime/)으로 재편, 경로만 바뀜(§_unclassified는
# 최상위 *.py만 보므로 옮긴 파일은 더 이상 거기 잡히지 않음 — 위 목록은 fingerprint() 읽기 경로 용으로 계속 정확히 유지).
# S3(10-26, refactor_plan 9-1·9-2) — common_tools → common/{core,ai,store,check}. 위 두 목록은 새 자리(이 폴더 기준)이고,
# 지문에 넣는 이름은 아래 _HANDOFF_LEGACY의 옛 상대 경로 그대로(경로 글자만 바뀐 것으로 FINGERPRINT가 바뀌지 않게).
# store/objectstore.py 등 store/·check/ 아래 나머지는 처음부터 이 목록 밖이었다(최상위만 _unclassified가 봄).
# S4(10-26, VS3 R-1 — 코디네이터 Task) — _unclassified가 common/ 하위 폴더까지 본다(S3 전에는 최상위 common_tools/*.py
# 4개를 봤는데, S3로 그 파일들이 core/로 내려가 최상위에는 __init__.py만 남아 검사가 사실상 비어 있었음). 빠져 있던
# 하위 패키지 __init__.py 5개·check/ 도구 3개를 EXCLUDED_FILES에 더함 — FINGERPRINT는 HANDOFF_FILES만 보므로 그대로.

# 지문 계산용 옛 상대 경로(새 자리 → 옛 common_tools/ 기준 이름) — 지우지 않는다(CLAUDE.md 3절 인계 지문).
_HANDOFF_LEGACY = {
    "core/contract.py": "contract/contract.py",
    "core/repfmt.py": "contract/repfmt.py",
    "core/terms.py": "terms.py",
    "core/text.py": "text.py",
}


def _unclassified(root=None, handoff=HANDOFF_FILES, excluded=EXCLUDED_FILES):
    """root(기본 공용 패키지 루트 common/) 아래 .py 파일(하위 폴더 포함, __pycache__ 제외 — S4) 중 handoff·excluded
    어느 쪽에도 없는 이름 목록(root 기준 상대 경로 'core/x.py', 정렬) — 비어야 함. "/"로 끝나는 항목은 그 폴더 아래 전부(S8a)."""
    folder = Path(root) if root else _ROOT
    names = {f.relative_to(folder).as_posix() for f in folder.rglob("*.py") if "__pycache__" not in f.parts}
    dirs = tuple(e for e in excluded if e.endswith("/"))
    return sorted(n for n in names - set(handoff) - set(excluded) if not n.startswith(dirs))


_missing = _unclassified()
if _missing:
    raise RuntimeError(
        f"common/**/*.py에 분류 안 된 파일: {_missing} — common/core/fingerprint.py의 HANDOFF_FILES(인계 내용에 영향) "
        "또는 EXCLUDED_FILES(운영·헬퍼, 무관)에 추가하세요."
    )


# 앞에서부터 차례로 바꾸므로 순서가 결과를 정한다 — 뒤 쌍은 앞 쌍이 바꾼 글자를 다시 본다(먼저 맞은 쌍이 이기는 게 아니라
# 이어서 적용됨). I2(10-23) 맨 앞 두 쌍: data_etl 이름을 10-14 이름(data_parsing.*)으로 먼저 되돌리면 바로 뒤
# data_parsing. 쌍이 이어서 옛 data_pipeline.parse.로 바꿔 엔진 지문(run_all.engine_code_fp)이 옮기기 전과 같다.
# 이 두 쌍은 반드시 data_parsing. 쌍보다 앞에 둔다(뒤에 두면 data_etl.* 글자가 그대로 남아 지문이 바뀜).
# S2(10-26, 사용자 1a) 맨 앞 세 쌍: HANDOFF 파일 terms.py의 데이터 경로 글자만 resources/로 바뀐 것(엔진 구성·용어집 이동)을
# 옛 글자로 되돌려 인계 FINGERPRINT를 옮기기 전과 같게 둔다(엔진 파일에는 이 글자가 없어 엔진 지문 영향 없음).
# S3(10-26, 사용자 원칙 — 경로·모듈 이름 글자만 바뀐 것은 지문 유지) 맨 앞 일곱 쌍: common_tools → common/{core,ai} 이름을
# S3 전 글자(common_tools.*)로 먼저 되돌린다 — 그 뒤 S2 쌍·옛 쌍이 S3 전과 똑같이 이어서 적용된다. 앞 다섯 쌍은 HANDOFF 파일
# (contract·repfmt·terms·text의 import 줄·사용 안내 글자), 뒤 두 쌍은 엔진 import 줄(docling·qwen_vlm의 guard, rapidocr의 resources).
# 반드시 common_tools. 쌍보다 앞에 둔다(뒤에 두면 common.* 글자가 그대로 남아 지문이 바뀜) — VS3 실험으로 확인한 실제 제약은
# 이것뿐이다(S2 쌍과는 글자가 겹치지 않아 순서가 결과를 바꾸지 않음 — 그래도 지금처럼 맨 앞에 두면 안전).
# S4(10-26, 같은 사용자 원칙) 맨 앞 두 쌍: data_etl/ → pipeline/ 이동으로 엔진 import 줄(…extract.engines._common 18곳·등록부
# import_module 글자 1·qwen_vlm의 …figures.vgate 1)에 생긴 새 이름을 I2 글자(data_etl.*)로 먼저 되돌린다 — 바로 뒤가 아니라
# 아래 I2 쌍(data_etl.* → data_parsing.*)보다 앞이기만 하면 된다(그 뒤 쌍들은 S4 전과 똑같이 이어서 적용). HANDOFF 파일에는
# 이 글자가 없어 인계 지문 영향 없음.
_LEGACY_NAMES = (
    (b"pipeline.extract.engines.", b"data_etl.extract.engines."),
    (b"pipeline.transform.figures.vgate", b"data_etl.transform.figures.vgate"),
    (b"from common import CONTRACT", b"from common_tools import CONTRACT"),
    (b"common.core.contract", b"common_tools.contract.contract"),
    (b"common.core.paths", b"common_tools.contract.paths"),
    (b"common.core.terms", b"common_tools.terms"),
    (b"common.core.text", b"common_tools.text"),
    (b"common.ai.guard", b"common_tools.model.guard"),
    (b"from common.core import resources", b"from common_tools.runtime import resources"),
    (b"paths import PKG_ROOT, RES_ROOT", b"paths import PKG_ROOT"),
    (b'RES_ROOT / "config" / "pipeline_stack.json"', b'ROOT / "pipeline_stack.json"'),
    (b'RES_ROOT / "vocab" / "glossary"', b'ROOT / "glossary"'),
    (b"data_etl.extract.engines.", b"data_parsing.engines."),
    (b"data_etl.transform.figures.vgate", b"data_parsing.postprocess.vgate"),
    (b"data_parsing.", b"data_pipeline.parse."),
    (b"data_structure.", b"data_pipeline.structure."),
    (b"data_retrieval.", b"data_pipeline.search."),
    (b"common_tools.evaluation", b"data_pipeline.evaluation"),
    (b"common_tools.cli", b"data_pipeline.cli"),
    (b"common_tools.", b"data_pipeline.common."),
    (b"from common_tools import", b"from data_pipeline.common import"),
    (b"data_parsing ", b"data_pipeline.parse "),
)


def legacy_names(data):
    """10-14 이미지별 폴더 분리 — 지문(인계 FINGERPRINT·run_all 엔진 코드 지문)을 옛 패키지 이름으로 되돌려 계산:
    import 이름만 바뀐 것으로 서버의 멀쩡한 결과가 낡음 처리(전 문서 재파싱·종료 코드 3)되지 않게.
    ponytail: 바이트 치환 — 해당 파일 내용이 실제로 바뀌면 지문은 어차피 바뀌므로 그 판 이후엔 지워도 됨."""
    for new, old in _LEGACY_NAMES:
        data = data.replace(new, old)
    return data


def fingerprint(root=None, handoff=HANDOFF_FILES):
    """HANDOFF_FILES(기본)만 — 줄 끝(CRLF/LF) 차이는 무시(Windows 사본과 Linux 사본이 같은 지문).
    해시에 넣는 이름은 옛 상대 경로(_HANDOFF_LEGACY, S3) — 대응표에 없는 이름(selftest 가짜 파일)은 그대로."""
    folder = Path(root) if root else _ROOT
    h = hashlib.sha256()
    for name in sorted(handoff, key=lambda n: _HANDOFF_LEGACY.get(n, n)):
        f = folder / name
        h.update(_HANDOFF_LEGACY.get(name, name).encode())
        h.update(legacy_names(f.read_bytes().replace(b"\r\n", b"\n")))
    return h.hexdigest()[:16]


FINGERPRINT = fingerprint()


def _semver(text):
    """'MAJOR.MINOR.PATCH' → 비교용 튜플, 그 꼴이 아니면 None."""
    parts = text.split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return tuple(int(p) for p in parts)
    return None


def pipeline_version(root=None):
    """버전 표기(한 곳 — D-036, 사용자 10-29: 버전만) — 두 이미지 공통 SemVer. 후보는 저장소 루트 VERSION(이미지 /app/deploy/VERSION)과
    common/PATCH_VERSION(make_patch 오버레이 패치 묶음 — 이미지 위에 올린 코드의 버전) 둘이고, 더 높은 버전을 쓴다(새 이미지로 바꾼 뒤
    코드 폴더에 남은 옛 PATCH_VERSION이 이기지 않게). 둘 다 SemVer 꼴이 아니면 env PIPELINE_VERSION → 'unknown'.
    publish(AI.ParsingMeta.pipeline_version)·실행 보드(run_board)·parse_parallel이 같이 씀. 10-29 전에는 git 짧은 커밋을 먼저 썼다(C-62)."""
    import os

    base = Path(root) if root else _ROOT
    found = []
    for f in (base.parent / "VERSION", base / "PATCH_VERSION"):
        try:
            v = f.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if _semver(v):
            found.append(v)
    if found:
        return max(found, key=_semver)
    return os.environ.get("PIPELINE_VERSION") or "unknown"  # env 남김 — 내부 신호(5-3 H)
