"""공용·파이프라인 코드와 평가 도구가 함께 쓰는 경로 기준 상수와 원자적 파일 쓰기.
각 파일이 `Path(__file__).resolve().parents[N]`을 따로 계산하지 않고 여기 상수를 쓴다 — 배치가 바뀌면 이 파일만 고친다.
단, 패키지를 처음 sys.path에 넣는 bootstrap 줄(이 파일을 아직 import할 수 없는 자리)은 parents[N]을 직접 쓴다.

PKG_ROOT = 공용 패키지 루트(DEPLOY_ROOT/common) — 하위 프로세스 cwd·표시 기준(데이터 파일은 RES_ROOT).
DEPLOY_ROOT = 패키지들이 import되는 자리 — 하위 프로세스 PYTHONPATH로만 쓴다(아래 child_env) — `-m pipeline.x`·
`-m validation.e2e.x` 형태로 불러야 하므로 PKG_ROOT 자신이 아니라 그 부모가 필요하다.
APP_ROOT = 런타임 루트(output/·assets/가 있는 곳) = PROJ_ROOT: PC는 저장소 루트, 이미지는 `/app`
(컨테이너 안 트리가 저장소와 같은 깊이).

원자적 쓰기 — 임시 파일에 다 쓰고 os.replace로 이름을 바꿔 중간에 끊겨도 0바이트·반쪽 결과가 남지 않게 한다.
Windows에서 다른 프로세스가 대상 파일을 열고 있으면 os.replace가 잠깐 PermissionError를 내므로 _replace가 그 오류만
짧게 재시도한다. 더 긴 재시도가 필요한 호출자는 자기 루프 안에서 부른다.
"""

import os
import time
from pathlib import Path

# common/core/paths.py: parents[0]=core/, parents[1]=common/, parents[2]=deploy/(이미지) 또는 저장소 루트(PC), parents[3]=이미지 루트.
# LOCAL_RUN(로컬 배치) — PC 저장소는 패키지가 저장소 바로 아래(deploy/ 단 없음)라 parents[2]가 루트.
# RUN_ENV=local이고 코드가 이미지 배치(/app/deploy/<패키지>)가 아닐 때만 참 — PC 시험 Docker 컨테이너(RUN_ENV=local)는
# 이미지 배치라 서버와 같게 본다. RUN_ENV는 settings.resolve_run_env로 읽는다(못 읽거나 모르는 값이면 로컬 아님).
# mcp_server retriever도 이 값을 쓴다.
# 판정 한계: 이미지 배치는 폴더 이름(parents[2] == "deploy")으로만 가른다 — PC에서 저장소 폴더 이름이 deploy면 로컬 배치가 꺼진다.
_HERE = Path(__file__).resolve()


def _run_env():
    from common.config.settings import SettingsError, resolve_run_env

    try:
        return resolve_run_env()
    except SettingsError:
        return None


LOCAL_RUN = _HERE.parents[2].name != "deploy" and _run_env() == "local"
PROJ_ROOT = _HERE.parents[2 if LOCAL_RUN else 3]

DEPLOY_ROOT = Path(__file__).resolve().parents[2]  # deploy/ — 모든 패키지가 import되는 자리(하위 프로세스 PYTHONPATH)
PKG_ROOT = DEPLOY_ROOT / "common"  # 공용 패키지 루트 — 하위 프로세스 cwd·표시 기준(데이터 파일은 RES_ROOT)
# 모듈 패키지 루트 — 이미지마다 들어 있는 패키지가 달라 없는 폴더일 수 있다.
PARSING_ROOT = (
    DEPLOY_ROOT / "pipeline" / "transform" / "parse"
)  # 엔진 폴더(engines/)의 부모 — parse_engines.engine_code_fp가 이 기준 상대 경로('engines/…')로 해시(바꾸면 엔진 지문이 바뀜)
# 코드가 읽는 데이터(지시서·설정 기본값·원천 표·어휘) — 패키지들과 같은 자리(PC=저장소 루트/resources,
# 이미지=/app/deploy/resources), 모든 이미지에 폴더째 들어간다.
RES_ROOT = DEPLOY_ROOT / "resources"
CRITERIA_FILE = RES_ROOT / "config" / "criteria.json"  # 판정 문턱값 정본
STACK_FILE = RES_ROOT / "config" / "pipeline_stack.json"  # 엔진 구성(DB 표의 시드·PC 대체)
GLOSSARY_ROOT = RES_ROOT / "vocab" / "glossary"  # 용어집·명부 예시·고객 seed(코드 기본값·selftest용)
APP_ROOT = PROJ_ROOT  # 런타임 루트(output/·assets/가 있는 곳) — PC=저장소 루트, 이미지=/app
LOG_DIR = APP_ROOT / "output" / "logs"  # 파일 로그 한 곳 — PC JSON 로그·DB 실패 예비 기록의 기본 폴더
LOCAL_EDW_SEED = PROJ_ROOT / "valid_env" / "edw" / "edw.sqlite"  # PC 가짜 EDW 원본(git — 쓰지 않음)
LOCAL_EDW_COPY = PROJ_ROOT / "valid_env" / "edw" / "edw_copy.sqlite"  # local 가짜 EDW 기본 — 없으면 원본을 복사(common.store.mssql, op-14)
SPEND_DIR = APP_ROOT / "output" / "_llm_spend"  # 하루 지출 장부 기본 폴더(spend_file 비었을 때 — common.ai.guard.ledger_file)


def child_env(extra=None):
    """하위 프로세스(python -m common.x.y·pipeline.x·validation.e2e.x 등 또는 스크립트 실행)가 파이프라인 패키지를 import하게 할
    env — PYTHONPATH를 세팅하는 유일한 자리(다른 곳은 여기를 거친다). os.environ을 베이스로 PKG_ROOT.parent
    (deploy/, 패키지들이 import되는 자리)를 PYTHONPATH 맨 앞에 붙임(이미 있으면 중복 안
    함) — 자식도 현재 프로세스와 같은 common·pipeline·mcp_server·validation을 보게."""
    env = dict(os.environ)  # env 남김 — 하위 프로세스
    existing = env.get("PYTHONPATH", "")
    parts = [str(PKG_ROOT.parent)] + ([existing] if existing else [])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    if extra:
        env.update(extra)
    return env


def doc_dir(required=True):
    """원본 문서 폴더 — 설정 ops.paths.source_docs_dir, 코드 기본값 없음. required=True(기본)면
    비었을 때 SystemExit(사람이 보는 안내 한 줄) · required=False면 조용히 None(호출부가 '미설정'을 크래시가
    아니라 점검 결과 한 줄로만 보고할 때 — 예: common.check.checker env)."""
    from common.config.settings import cfg  # 늦게 import — 이 파일은 거의 모든 프로세스가 import

    v = cfg().paths.doc_dir
    if v:
        return Path(v)
    if not required:
        return None
    raise SystemExit("원본 문서 폴더가 없음 — settings.yaml ops.paths.source_docs_dir에 경로를 넣거나 --src로 지정")


def resolve_agent_dir(agent_id):
    """agent 지시서 패키지 폴더를 이름으로 찾는 한 곳 — agent 실행·지시서 읽기가 모두 여기를 거쳐, 새 agent_id를
    추가할 때 여기만 고치면 된다.

    검색 순서는 고정: ① resources/prompts/common ② resources/prompts/pipeline
    ③ valid_env/answer_test(PC 전용 답변 점검 agent rag_qa).
    이름 충돌이 없어 순서가 결과를 바꾸지는 않지만, 결정적이어야 캐시·로그가 재현된다. 패키지를 import하지 않고
    Path만 보므로 이미지에 없는 폴더는 `cand.is_dir()`이 False가 되어 저절로 건너뛴다.
    다 없으면 FileNotFoundError."""
    for base in (
        RES_ROOT / "prompts" / "common",
        RES_ROOT / "prompts" / "pipeline",
        PROJ_ROOT / "valid_env" / "answer_test",
    ):
        cand = base / agent_id
        # __pycache__만 남은 폴더(배포 덧씌우기 뒤 등)는 건너뛰고, 실제 파일이 하나라도 있는 폴더만 후보로
        if cand.is_dir() and any(f.name != "__pycache__" for f in cand.iterdir()):
            return cand
    raise FileNotFoundError(f"agent 패키지를 못 찾음: {agent_id!r} (resources/prompts/{{common,pipeline}}·valid_env/answer_test 다 없음)")


def tmp_path_for(dst):
    """dst 쓰기에 쓸 임시 파일 경로(같은 폴더에 여러 프로세스(--procs)가 동시에 써도 안 겹침) — 재시도가
    전부 실패했을 때 호출자가 남은 임시 파일을 지우려면 이 경로로 찾는다."""
    dst = Path(dst)
    return dst.with_name(f"{dst.name}.{os.getpid()}.tmp")


def _replace(tmp, dst, tries=5):
    """os.replace — PermissionError(Windows 잠금)만 0.1·0.2·0.4·0.8초 기다려 재시도, 다른 오류는 바로 냄."""
    for i in range(tries):
        try:
            return os.replace(tmp, dst)
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.1 * 2**i)


def atomic_write_text(dst, text, *, encoding="utf-8"):
    """dst(Path·str)에 text를 원자적으로 씀 — 임시 파일 쓰기 1회 + os.replace 1회. dst를 돌려준다."""
    dst = Path(dst)
    tmp = tmp_path_for(dst)
    tmp.write_text(text, encoding=encoding)
    _replace(tmp, dst)
    return dst


def atomic_write_bytes(dst, data):
    """dst(Path·str)에 바이트를 원자적으로 씀 — atomic_write_text의 바이트판."""
    dst = Path(dst)
    tmp = tmp_path_for(dst)
    tmp.write_bytes(data)
    _replace(tmp, dst)
    return dst
