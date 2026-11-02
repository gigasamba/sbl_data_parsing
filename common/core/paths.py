"""공용·파이프라인 코드와 평가 도구가 공유하는 경로 기본값 — 폴더 재편(docs/architecture.md §4) 뒤
한 곳만 바꾸면 되게. 파이프라인 패키지(common·common_tools·pipeline·mcp_server)는 agent_platform·answer_agent를 import하지 않으므로(이미지 경계) 그쪽
paths.py와는 별도 상수.

구조 개편 v4(restructure-plan-v4.md 단계 4·5) — PKG_ROOT·APP_ROOT·child_env()는 파이프라인 4개 패키지 전체(및 common을
이미 올린 뒤의 dev_tools/unit_test/ 호출부)가 `Path(__file__).resolve().parents[N]`을 직접 계산하는 대신 쓰는 단일 자리.
PKG_ROOT = 공용 패키지 루트(S6a부터 deploy/common/ — 옛 deploy/common_tools/, 10-14 분리 전엔 deploy/data_pipeline/) — 하위 프로세스
cwd·표시 기준(데이터 파일은 S2부터 RES_ROOT). DEPLOY_ROOT(=deploy/, 패키지들이 import되는 자리)는 하위 프로세스
PYTHONPATH로만 쓴다(아래 child_env) — `-m pipeline.x`·`-m validation.e2e.x` 형태로 불러야 하므로 PKG_ROOT 자신이 아니라
그 부모가 필요. APP_ROOT = 런타임 루트(output/·assets/·docker/가 있는 곳) — 단계 5(10-13)부터 PROJ_ROOT와 같음:
PC는 저장소 루트, 이미지는 `/app`(컨테이너 안 트리가 저장소와 같은 깊이로 거울). 이 상수들만 고치면 이 파일을
import하는 모든 곳이 따라온다 — 그래서 각 파일에 남은 `parents[N]`을 전부 없애는 게 이번 단계의 목적(개별
파일은 더 이상 안 고쳐도 되게). 단, 이 파일을 아직 못 쓰는 자리(= 처음으로 패키지를 sys.path에 넣는 bootstrap
줄 자체, common_tools이 아직 import 가능해지기 전)는 그대로 둔다 — 거기 남은 parents[N]은 일부러 안 건드린 것.

CT1(common_tools 하위 역할 묶음) — 이 파일이 common/core/paths.py로 한 단 내려가면서 PKG_ROOT·PROJ_ROOT의
parents[N] 깊이가 하나씩 늘어났다(아래 값 참고) — atomic.py(원자적 파일 쓰기)도 "모듈 사이 계약" 성격이라 이 파일로 합침.
S3(10-26, refactor_plan 9-1·D-014) — 이 파일이 common/core/paths.py로(깊이는 같음 — parents[2]=deploy/). PKG_ROOT는
값을 그대로 둔다(옛 공용 폴더 deploy/common_tools/ — options.conf·평가 도구 설정·S6까지 prompts/triple_extract가 남음):
이 파일의 부모(common/)가 아니라 DEPLOY_ROOT 기준으로 이름을 붙여 계산(쓰는 곳 — cwd·표시 경로·DEV — 이 바뀌지 않게).
S6a(10-26, 코디네이터 답 Q3 a) — common_tools/가 없어져 PKG_ROOT = DEPLOY_ROOT/common(같은 깊이·모든 이미지에 있음 — 하위 프로세스
cwd·runlog 표시 기준·DEV 기준 상대 경로('../../valid_env/…' 등)가 옛 값과 같은 자리를 가리킴). 이 줄이 바뀌어 code_fp 5개가 바뀜.

원자적 쓰기(옛 atomic.py) — 임시 파일에 다 쓰고 os.replace로 이름을 바꿔 중간에 끊겨도 0바이트·반쪽 결과가 안
남게(10-04 실측: 끊긴 실행이 0바이트 결과 6건을 남겨 parse_qa가 죽음). RV6(10-09) — modules/parse/phase_report.py·
progress.py·run_all.py에 따로 있던 tmp+os.replace 패턴을 하나로 모음. Windows에서 다른 프로세스가 대상 파일을
열고 있으면 os.replace가 잠깐 PermissionError를 내므로 _replace가 그 오류만 짧게 재시도한다(10-14 재빌드에서
_figures/capped.jsonl 교체 실패로 P1 2건이 죽음). 더 긴 재시도가 필요한 호출자는 여전히 자기 루프 안에서 부른다.
"""

import os
import time
from pathlib import Path

# common/core/paths.py: parents[0]=core/, parents[1]=common/, parents[2]=deploy/, parents[3]=저장소 루트(CT1 common_tools/contract/와 같은 깊이 — S3).
# LOCAL_RUN(로컬 배치) — sbl_mcp 저장소는 패키지가 저장소 바로 아래(deploy/ 단 없음)라 parents[2]가 루트. 아니면 서버·이미지 그대로.
# S7b(D-028 · 코디네이터 답 1a) — 옛 env LOCAL_RUN=1 대신 RUN_ENV=local이고 코드가 이미지 배치(/app/deploy/<패키지>)가 아닐 때 —
# PC 시험 Docker 컨테이너(RUN_ENV=local)는 이미지 배치라 서버와 같게. RUN_ENV는 env 신호 > 설정 파일 common.run_env(S7e2 — 다리가 없어져
# settings.resolve_run_env로 — 못 읽거나 모르는 값이면 로컬 아님). mcp_server retriever도 이 값을 쓴다.
# 판정 한계(VS7b R-8): 이미지 배치는 폴더 이름(parents[2] == "deploy")으로만 가른다 — PC에서 저장소 폴더 이름이 deploy면 로컬 배치가 꺼진다.
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
PKG_ROOT = (
    DEPLOY_ROOT / "common"
)  # 공용 패키지 루트(S6a — 옛 deploy/common_tools/와 같은 깊이, 위 설명) — 하위 프로세스 cwd·표시 기준(데이터 파일은 S2부터 RES_ROOT)
# 10-14 이미지 단위 분리(사용자) — 모듈 패키지 루트. 각 이미지엔 자기 모듈 + common만 있으므로 없는 폴더일 수 있다.
# I2(10-23) — 파싱·구조화 두 모듈 폴더가 data_etl/ 단계 폴더(extract·transform·load…)로 합쳐짐. data-parsing·data-structure 이미지 둘 다 data_etl/ 전체를 넣는다.
# S4(10-26, refactor_plan 9-1) — data_etl/ → pipeline/. 엔진 폴더 기준 상대 경로('engines/…')는 그대로(0.2.0 PIPELINE_ROOT·RETRIEVAL_ROOT 상수 지움 — pl-46).
PARSING_ROOT = (
    DEPLOY_ROOT / "pipeline" / "extract"
)  # 엔진 폴더(engines/)의 부모 — run_all.engine_code_fp가 'parse/' + 이 기준 상대 경로로 해시(옮기기 전과 같은 'engines/…' 글자 — 엔진 지문 유지)
E2E_ROOT = DEPLOY_ROOT / "validation" / "e2e"  # S6a — PC 전용 평가 도구·triple_extract 지시서(이미지에는 없음)
# S2(10-26, refactor_plan 4-1·D-011) — 코드가 읽는 데이터(지시서·설정 기본값·원천 표·어휘)를 패키지 폴더에서 resources/로 모음.
# 패키지들과 같은 자리(PC=저장소 루트/resources, 이미지=/app/deploy/resources) — 모든 이미지에 폴더째 들어간다.
RES_ROOT = DEPLOY_ROOT / "resources"
CRITERIA_FILE = RES_ROOT / "config" / "criteria.json"  # 판정 문턱값 정본(D-022 — 서버 사본 우선은 S7)
STACK_FILE = RES_ROOT / "config" / "pipeline_stack.json"  # 엔진 구성(D-017 — S8에 DB 판 표의 시드·PC 대체)
GLOSSARY_ROOT = RES_ROOT / "vocab" / "glossary"  # 용어집·명부 예시·고객 seed(운영 사전은 env GLOSSARY_DIR — 이 값은 코드 기본·selftest용)
APP_ROOT = PROJ_ROOT  # 런타임 루트(output/·assets/·docker/가 있는 곳) — PC=저장소 루트, 이미지=/app(둘 다 PROJ_ROOT와 같음, 위 설명)


def child_env(extra=None):
    """하위 프로세스(python -m common.x.y·pipeline.x·validation.e2e.x 등 또는 스크립트 실행)가 파이프라인 패키지를 import하게 할
    env — PYTHONPATH를 세팅하는 유일한 자리(다른 곳은 여기를 거친다). os.environ을 베이스로 PKG_ROOT.parent
    (deploy/, 패키지들이 import되는 자리)를 PYTHONPATH 맨 앞에 붙임(이미 있으면 중복 안
    함) — 자식도 현재 프로세스와 같은 common·pipeline·mcp_server·validation을 보게."""
    env = dict(os.environ)  # env 남김 — 하위 프로세스·옛 코드에 넘김
    existing = env.get("PYTHONPATH", "")
    parts = [str(PKG_ROOT.parent)] + ([existing] if existing else [])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    if extra:
        env.update(extra)
    return env


def doc_dir(required=True):
    """원본 문서 폴더 — 설정 DOC_DIR(common.paths.doc_dir — S7e2부터 옛 별칭 DOC_SRC env는 안 읽음, DOC_SRC는 호스트 마운트 원본 칸), 하드코딩 기본값 없음(10-14 — 옛
    data/unstructed/SFDC_dump/ 자리표시자는 지워짐, NM16 전까지는 대체 자리표시자도 없음). required=True(기본)면
    둘 다 없을 때 SystemExit(사람이 보는 안내 한 줄) · required=False면 조용히 None(호출부가 '미설정'을 크래시가
    아니라 점검 결과 한 줄로만 보고할 때 — 예: common.check.checker env)."""
    from common.config.settings import cfg  # S7b — 설정 객체(늦게 import: 이 파일은 거의 모든 프로세스가 import)

    v = cfg().paths.doc_dir
    if v:
        return Path(v)
    if not required:
        return None
    raise SystemExit("원본 문서 폴더가 없음 — settings.yaml ops.paths.doc_dir에 경로를 넣거나 --src로 지정")


def resolve_agent_dir(agent_id):
    """단계 4(10-13) — 옛 dev/agents/<id>/는 prompts/<id>/(단일 호출 프롬프트 묶음)와 parse/agent/<id>/(여러
    턴 파싱 agent)로 나뉨. 패키지 이름으로 어느 쪽인지
    찾는 자리를 여기 한 곳으로 묶음(common/adk.py._load_pipeline·common/agent_prompts.py 둘 다 거침) — 새
    agent_id를 추가할 때 두 파일을 따로 안 고쳐도 되게.

    10-14 — 한 모듈만 쓰는 지시문 묶음은 common_tools/prompts/ 대신 그 모듈 폴더(data_etl/agent/·
    data_retrieval/prompts/)로 옮겨 이미지 용량을 줄임(여러 모듈이 쓰거나 agent_platform·answer_agent가 쓰거나
    _common 꼬리는 그대로 common_tools에 남음 — S2부터 표는 docs/architecture/prompts.md). 검색 순서는
    고정(① 공용 ② data_etl/agent — 옛 parse/agent 여러 턴 agent·파싱·구조화 prompts를 I2에서 한 폴더로 ③ 검색 prompts
    ④ 시험 고정물) — 순서 자체는 이름 충돌이 없어 결과에 영향 없지만, 결정적이어야 캐시·로그가 재현된다. pipeline 등
    실제 패키지를 import하지 않고 Path만 비교하므로(PKG_AREA import 경계·check_modules 그대로) — 이미지에 없는 모듈
    폴더(예: data-retrieval 이미지엔 pipeline/이 없음 — S4부터 cli.py만 있음)는 그 폴더 자체가 없어 `cand.is_dir()`이 조용히 False가 되어
    자연히 건너뜀(별도 try/except 불필요).
    마지막으로 dev_tools/unit_test/fixtures/도 본다 — example_agentic·example_agentic_vlm_sub(옛 dev/agents/example_agentic*)가
    여기로 옮겨졌는데, common/adk.py의 selftest()는 바로 이 run_agent("example_agentic", ...) 경로로 "실제
    모델/가드 경로를 타는" 것을 의도적으로 시험한다(dev_tools/unit_test/platform/test_pipeline_agentic.py 독스트링 참조) —
    운영 agent_id와 같은 이름 충돌은 없음(운영 쪽엔 example_* 이름이 없음).
    다 없으면 FileNotFoundError(호출부가 그대로 전파 — 기존에도 없는 폴더면 이후 파일 읽기에서 자연히
    실패했음, 메시지만 더 분명하게).
    S2(10-26, D-019) — 지시서 패키지가 resources/prompts/{common,pipeline,mcp}/로 옮겨 ①②③이 그 세 폴더가 됨
    (resources/는 모든 이미지에 폴더째 들어가 이미지별로 빠지는 폴더가 없음). 옛 common_tools/prompts/는 S6까지
    triple_extract(평가 실험 — 쓰는 도구와 함께 validation/e2e/로 갈 것)만 남아 ④로 봄.
    S6a(10-26, D-019 ③) — ④는 PC 전용 validation/e2e/(triple_extract — 이미지에는 폴더가 없어 조용히 건너뜀).
    10-29(사용자) — PC 전용 데이터는 valid_env 한 곳에: 답변 점검 agent rag_qa는 valid_env/answer_test/(⑤ — 이미지에 없음)."""
    for base in (
        RES_ROOT / "prompts" / "common",
        RES_ROOT / "prompts" / "pipeline",
        RES_ROOT / "prompts" / "mcp",
        E2E_ROOT,
        PROJ_ROOT / "valid_env" / "answer_test",
        PROJ_ROOT / "dev_tools" / "unit_test" / "fixtures",
    ):
        cand = base / agent_id
        # 10-14 — 지시문 이사 뒤 옛 자리에 __pycache__만 남은 폴더(재배치·덧씌우기 뒤 live/app 등)를 먼저 집어
        # FileNotFoundError가 나던 것(8a 보고) — 실제 파일이 하나라도 있는 폴더만 후보로
        if cand.is_dir() and any(f.name != "__pycache__" for f in cand.iterdir()):
            return cand
    raise FileNotFoundError(
        f"agent 패키지를 못 찾음: {agent_id!r} (resources/prompts/{{common,pipeline,mcp}}·validation/e2e·"
        "dev_tools/unit_test/fixtures 다 없음)"
    )


def resolve_run_dir(run_root, run_dir=None, *, new=True, label=None, rel_hint=None):
    """실행(run) 폴더 — 쓰기용(만들거나 재사용). RV6(10-09) — cli/model_matrix.py·옛 cli/stack_matrix.py에 따로 있던
    같은 이름 함수를 하나로(차이는 인자로): run_dir이 있으면 그 경로 그대로 · 없고 new=True(기본)면 run_root 아래
    오늘 시각(`%Y%m%d-%H%M%S`) 새 폴더 · 없고 new=False면 run_root 아래 가장 최근(이름 정렬 — 시각 폴더라 사전식
    정렬 = 시간 순) 폴더, 하나도 없으면 SystemExit(label·rel_hint로 기존 문구 그대로 재현). 둘 다 mkdir(parents=True,
    exist_ok=True) — 이름으로 기존 폴더만 찾는 읽기 전용 조회는 lookup_run_dir()."""
    run_root = Path(run_root)
    if run_dir:
        d = Path(run_dir)
    elif new:
        d = run_root / time.strftime("%Y%m%d-%H%M%S")
    else:
        existing = sorted(p for p in run_root.glob("*") if p.is_dir())
        if not existing:
            raise SystemExit(f"[{label or run_root.name}] {rel_hint or run_root} 아래 이전 run 없음")
        d = existing[-1]
    d.mkdir(parents=True, exist_ok=True)
    return d


def lookup_run_dir(run_root, name):
    """이름으로 기존 run 폴더 찾기(읽기 전용, mkdir 안 함) — RV6(10-09, cli/stack_report.py 선례를 공용으로).
    절대경로로 있으면 그대로 · run_root 아래 그 이름이 있으면 그것 · 그 밖엔 (상대경로로) 있으면 그대로 ·
    없으면 None."""
    if not name:
        return None
    p = Path(name)
    if p.is_absolute() and p.exists():
        return p
    cand = Path(run_root) / name
    return cand if cand.exists() else (p if p.exists() else None)


def tmp_path_for(dst):
    """dst 쓰기에 쓸 임시 파일 경로(같은 폴더에 여러 프로세스(--procs)가 동시에 써도 안 겹침) — 재시도가
    전부 실패했을 때 호출자가 남은 임시 파일을 지우려면 이 경로로 찾는다(progress.py 선례)."""
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
