"""호스트 칸 표(deploy/host/scripts/host_settings.tsv) 만들기 — 호스트 python은 PyYAML만 있어 설정 모델을 못 읽으므로 모델에서
표(모델 경로·옛 env 이름·종류)를 만들어 두고 deploy/host/scripts/settings_to_env.py(load_settings.sh load_settings가 부름)가 그 표로 셸 env 줄을 낸다.
common 밖(deploy/release)에 둔다 — common.config.export는 층의 공용 의존이라 고치면 code_fp가 바뀌고, common의 새 파일은 지문 분류(fingerprint.py)가 필요해서.
사용: PYTHONPATH=. python deploy/release/gen_host_keys.py [--check]   — 설정 모델의 호스트 칸을 고쳤으면 다시 만든다(--check는 같은지만 — 시험·커밋 전).
"""

import sys

from common.config import settings as S
from common.core.console import utf8_stdout
from common.core.paths import DEPLOY_ROOT

# 호스트 셸이 읽는 절 — RUN_ENV(host_ctl.sh가 고르는 compose 파일)·호스트 칸(컨테이너 명령·원본 문서 폴더·이미지 정리·새벽 배치 시각)
HOST_SECTIONS = (
    "common.run_env",
    "common.host",
    "pipeline.host",
)
HOST_SKIP = (
    "pipeline.host.run_pipeline",
    "pipeline.host.run_pipeline_dir",
    "common.host.pg_container",  # 위 셋: run_pipeline.py가 settings.yaml에서 직접 읽음(셸 env로 안 냄)
    *(f"common.host.devbox.{k}" for k in ("git_user_name", "git_user_email")),  # 컨테이너 git_cred.py만 읽음
)
IMAGE_CONSTS = ("code_root", "docs_mount", "output_root")  # run_pipeline.py가 쓰는 약속 경로
HOST_TABLE = DEPLOY_ROOT / "deploy" / "host" / "scripts" / "host_settings.tsv"


def _kind(f):
    k = S.field_kind(f.annotation)
    if k == "list":
        return "words" if S.list_sep(f) == " " else "list"
    if k == "other":
        return "bool" if bool in S._args(f.annotation) else "num"
    return k


def _under(path, heads):
    return any(path == h or path.startswith(h + ".") for h in heads)


def host_table():
    """host_settings.tsv 글자 — 줄마다 `모델 경로<TAB>옛 env 이름<TAB>종류`(text·num·bool·list·words·json), 이미지 약속 경로는 `…<TAB>const<TAB>값`. 비밀 칸은 넣지 않는다."""
    rows, seen = [], set()
    for cls in S.app_classes().values():
        for path, f, _ in S.walk(cls):
            e = S.env_name(f)
            if not e or e in seen or S.is_secret(f) or not _under(path, HOST_SECTIONS) or _under(path, HOST_SKIP):
                continue
            seen.add(e)
            rows.append(f"{path}\t{e}\t{_kind(f)}")
    # 컨테이너 안 약속 경로(settings.IMAGE_PATHS 한 곳): 고정값 줄 `image.<이름><TAB>APP_<이름><TAB>const<TAB>값` — run_pipeline.py가 읽는다.
    rows += [f"image.{k}\tAPP_{k.upper()}\tconst\t{S.IMAGE_PATHS[k]}" for k in IMAGE_CONSTS]
    return "# 자동 생성 — PYTHONPATH=. python deploy/release/gen_host_keys.py(고치지 말 것)\n" + "\n".join(rows) + "\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    want = host_table()
    if argv == ["--check"]:
        same = HOST_TABLE.is_file() and HOST_TABLE.read_text(encoding="utf-8") == want
        print("[gen_host_keys] host_settings.tsv " + ("같음" if same else "다름 — PYTHONPATH=. python deploy/release/gen_host_keys.py"))
        return 0 if same else 1
    HOST_TABLE.write_text(want, encoding="utf-8", newline="\n")
    print(f"[gen_host_keys] 씀: {HOST_TABLE}")
    return 0


if __name__ == "__main__":
    utf8_stdout()
    raise SystemExit(main())
