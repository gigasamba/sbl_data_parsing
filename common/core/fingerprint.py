"""인계 지문(FINGERPRINT)·인계 형식 버전(CONTRACT)·판 표기(pipeline_version).
HANDOFF_FILES·_unclassified의 기준 폴더는 이 파일의 폴더(core/)가 아니라 공용 패키지 루트(common/) — 이름은 'core/…'.
common/__init__.py가 CONTRACT·FINGERPRINT·pipeline_version을 다시 내보낸다(`from common import CONTRACT` —
HANDOFF 파일 core/contract.py의 import 줄이 그대로여야 지문이 같다).

FINGERPRINT = HANDOFF_FILES(이 폴더의 일부 .py만) 내용의 지문 — 모듈 끝 표시(_DONE.json)에 남기고 다음 모듈이
자기 것과 비교해, 다른 커밋으로 만든 이미지끼리 규칙이 어긋나면(예: 토큰 규칙만 바뀐 구조화 이미지) 시작을
거부한다(종료 코드 3). 인계 내용과 무관한 파일을 고쳐도 서버가 멀쩡한 결과를 다시 파싱하지 않도록 HANDOFF_FILES만 본다.
새 common/**/*.py(하위 폴더 포함)를 추가하면 HANDOFF_FILES나 EXCLUDED_FILES 둘 중 하나에 넣어야 한다
(안 넣으면 import 때 바로 거부 — _unclassified()).
"""

import hashlib
from pathlib import Path

CONTRACT = 2  # 인계 파일 형식 버전 — 형식이 바뀌면 올림(지문은 코드가 바뀌면 자동으로 바뀜)

_ROOT = Path(__file__).resolve().parent.parent  # 공용 패키지 루트(common/) — HANDOFF_FILES·_unclassified·PATCH_VERSION 기준

# 선정 기준 — parse→structure·structure→load 두 경계 양쪽이 **같은 값을 각자 계산해서 맞춰야 하는** 파일만.
# 한쪽 모듈만 내부적으로 쓰거나(결과를 다른 쪽이 다시 계산해 맞출 필요가 없음) 연결·캐시·로그 같은 운영 코드는
# EXCLUDED_FILES로 뺀다 — 포함 기준을 넓게 잡을수록 이 파일들이 조금만 바뀌어도 앞 모듈을 다시 돌려야 해서
# 일부러 좁게 잡았다. 각 파일 이유는 EXCLUDED_FILES 옆 주석.
HANDOFF_FILES = (
    "core/contract.py",  # 인계 형식 자체(_rep REP_KEYS·bundle CHUNK_KEYS/DOC_KEYS 스키마, jl() 읽기) + doc_key(file_sha256)·chunk_key
    # — structure·load가 시작 전에 이걸로 거부 판정, parse·structure가 독립적으로 다시 계산해 맞춤
    "core/repfmt.py",  # (라벨,값) 쌍 추출·계약번호/고객 정규식 — parse(crosscheck→_rep meta.pairs)가 뽑고 structure(gold_bundle.py AQ.pick)가 같은 규칙으로 해석
    "core/terms.py",  # 고객 명부·별칭·모달리티 — parse(융합)·structure(사실 추출)·load(계약 연결)가 "같은 규칙"으로 명시(docstring)
    "core/text.py",  # 토큰·정규화 규칙 — structure(색인 본문 chunk_term)·search(질의 토큰)이 반드시 같아야 함(docs/architecture.md §2)
)

# 나머지 common/**/*.py — 핸드오프(=parse→structure의 _rep·structure→load의 bundle) 내용·해석과 무관(연결·캐시·로그·
# 운영 설정), 또는 두 모듈 중 한쪽만 내부적으로 써서 이미지 사이에 맞출 값이 없음. 새 파일을 추가하면 이유를
# 적어 이 목록이나 HANDOFF_FILES에 넣는다(_check_classified가 둘 다에 없으면 거부).
EXCLUDED_FILES = (
    "__init__.py",  # 패키지 입구(fingerprint를 다시 내보내고 settings.pin_env를 부름)
    "ai/__init__.py",  # 하위 패키지 입구(빈 파일 — _unclassified가 하위 폴더까지 봄)
    "check/__init__.py",  # 하위 패키지 입구(빈 파일)
    "config/__init__.py",  # 하위 패키지 입구(빈 파일)
    "core/__init__.py",  # 하위 패키지 입구(빈 파일)
    "store/__init__.py",  # 하위 패키지 입구(빈 파일)
    "check/check_modules.py",  # 모듈 경계 점검 — 개발·반입 점검 도구, 인계 내용과 무관
    "check/checker.py",  # 점검기(env·services·ping) — 운영 도구
    "core/exitclean.py",  # 종료 정리(임시 파일 지우기·자식 회수) — 프로세스 관리, 인계 내용과 무관
    "core/console.py",  # CLI 표준 출력을 UTF-8로(utf8_stdout) — 화면 출력만, 인계 내용과 무관
    "core/parse_limit.py",  # parse_document 파일 크기 상한 — 서비스 입구만, 인계 내용과 무관
    "core/fingerprint.py",  # 이 파일 자신 — CONTRACT는 따로 버전으로 확인, pipeline_version()은 인계 내용과 무관
    "config/boot.py",  # 컨테이너 시작 설정(entrypoint의 RUN_ENV 관문·셸 칸·라이브러리 env) — 운영 도구
    "config/overrides.py",  # 덮기 파일 만들기(PC 한 번 실행) — 운영 도구
    "config/setarg.py",  # 명령 인자 --set 이름=값(한 번 실행 덮기, 서버 포함) — 운영 설정, 인계 내용과 무관
    "config/layout.py",  # settings.yaml 칸 자리 ↔ 모델 경로 — 운영 설정, 인계 내용과 무관
    "config/keyscan.py",  # 설정 키 모으기 — 개발 점검 도구, 인계 내용과 무관
    "config/settings.py",  # settings.yaml 읽기·common 절 모델 — 운영 설정, 인계 내용과 무관
    "config/export.py",  # 설정 절 → KEY=VALUE(셸·compose 다리) — 운영 도구
    "config/sample.py",  # settings.sample.yaml 만들기·대조 — 개발 도구
    "config/show.py",  # 앱 설정 확인 명령 — 운영 도구
    "ai/agent_prompts.py",  # 지시문 글자는 프롬프트 지문이 따로 추적(여기서 또 볼 필요 없음)
    "core/artifacts.py",  # 실험 저장소 계약(code_fp·캐시 정리) — 파싱 이식 도구 전용, parse↔structure↔load 런타임 핸드오프 밖
    "core/docmeta.py",  # structure(gold_bundle.py)↔search(retriever.py) 전용(날짜·구판 판정) — parse·load는 안 씀, 이 FINGERPRINT가 보는 두 경계(parse→structure·structure→load) 밖
    "ai/embed.py",  # 임베딩 계산은 structure(쓰기)·search(질의)가 맞아야 하지만 search는 이 FINGERPRINT 경계 밖(MARK에 없음)이라 넣어도 그 위험을 못 막고,
    # 질의 캐시 코드가 내용과 무관하게 자주 바뀌어 넣으면 그 캐시 수정마다 재파싱을 유발. structure 쪽 재사용 판정은 code_fp("s")가 이미 embed.py를 따로 잡음
    "ai/guard.py",  # 내부망 확인(허용/거부) — 통과하면 호출 내용을 바꾸지 않음, _rep/bundle 바이트·해석과 무관
    "ai/llm.py",  # LLM 클라이언트(재시도·캐시·예산) — 호출 메커니즘 + 모델 프로필(주소·이름) 조회
    "core/meaning.py",  # 유의미 토큰 — parse 내부(대표 선정·QA)·structure 내부(쪽 번호 제거) 각자 전용, 서로 맞출 공유 값이 없음(text.py와 tokens() 이름이 겹치지만 규칙이 다름)
    "store/mssql.py",  # 회사 DB(SQL Server) SQLAlchemy 연결 — 연결 방법만
    "store/objectstore.py",  # Object Storage(S3) 연결 설정
    "store/parsing_meta_db.py",  # EDW AI.ParsingMeta 메타 저장 — 운영 기록, 핸드오프 내용 아님
    "core/paths.py",  # cli 평가 도구 경로 기본값 + 원자적 파일 쓰기 헬퍼(쓰는 방식만·내용은 안 바꿈)
    "store/pg.py",  # PostgreSQL 연결 설정
    "store/edw_chain.py",  # EDW 조인 사슬 파일 읽기·검사(적재 edw_meta·검색 거르기 이름) — 인계 형식과 무관
    "store/pg_standin.py",  # pg.py의 연결 정보 없을 때 스탠드인(sqlite) — 연결 방법만, 핸드오프 내용과 무관(pg.py가 shared라 같이 있음)
    "store/master.py",  # 마스터 표(용어집·고객 명부) 읽기·채우기 — DB 연결·표 내용, 인계 형식과 무관(terms.py가 읽은 값으로 판별)
    "core/resources.py",  # 실행 자원(CPU·메모리) 판단 — 병렬 수 결정만
    "core/jsonlog.py",  # JSON 사건 기록·상관 ID — 인계 내용과 무관
    "store/logsink.py",  # 비동기 DB 기록 — 인계 내용과 무관
    "core/span.py",  # 파이프라인 성능 span — 인계 내용과 무관
    "core/runlog.py",  # 로그 글자 비밀 가림(jsonlog·settings) — 인계 내용과 무관
    "store/db/",  # pgvector 표 정의·행 모양·Alembic 판·migrate 명령(폴더째 — "/"로 끝나면 그 아래 전부). DB 표 모양만,
    # _rep/bundle 내용과 무관 · 판을 더할 때마다 이 파일을 고치지 않게(이 파일은 모든 층의 공용 의존 — code_fp)
)


def _unclassified(root=None, handoff=HANDOFF_FILES, excluded=EXCLUDED_FILES):
    """root(기본 공용 패키지 루트 common/) 아래 .py 파일(하위 폴더 포함, __pycache__ 제외) 중 handoff·excluded
    어느 쪽에도 없는 이름 목록(root 기준 상대 경로 'core/x.py', 정렬) — 비어야 함. "/"로 끝나는 항목은 그 폴더 아래 전부."""
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


def fingerprint(root=None, handoff=HANDOFF_FILES):
    """HANDOFF_FILES(기본)만 — 줄 끝(CRLF/LF) 차이는 무시(Windows 사본과 Linux 사본이 같은 지문). 해시에 넣는 이름은
    common/ 기준 상대 경로."""
    folder = Path(root) if root else _ROOT
    h = hashlib.sha256()
    for name in sorted(handoff):
        h.update(name.encode())
        h.update((folder / name).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


FINGERPRINT = fingerprint()


def _semver(text):
    """'MAJOR.MINOR.PATCH' → 비교용 튜플, 그 꼴이 아니면 None."""
    parts = text.split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return tuple(int(p) for p in parts)
    return None


def pipeline_version(root=None):
    """버전 표기(한 곳) — 두 이미지 공통 SemVer. 후보는 저장소 루트 VERSION(이미지 /app/deploy/VERSION)과
    common/PATCH_VERSION(make_patch 오버레이 패치 묶음 — 이미지 위에 올린 코드의 버전) 둘이고, 더 높은 버전을 쓴다(새 이미지로 바꾼 뒤
    코드 폴더에 남은 옛 PATCH_VERSION이 이기지 않게). 둘 다 SemVer 꼴이 아니면 env PIPELINE_VERSION → 'unknown'.
    publish(AI.ParsingMeta.pipeline_version)·실행 보드(run_board)·parse_parallel이 같이 씀."""
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
    return os.environ.get("PIPELINE_VERSION") or "unknown"  # env 남김 — 내부 신호
