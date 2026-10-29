"""settings.sample.yaml 만들기·대조 — 앱 설정 모델(common + pipeline + mcp 절)에서 절·칸 구조와 설명만 뽑는다(값은 비움, S7a · D-015).
칸마다 주석: 설명 · 옛 env 이름 · 형식 · 기본값(비밀은 적지 않음) · 지문 고정. 칸을 더하거나 바꾸면 다시 만든다.
사용: python -m common.config.sample            # 저장소 루트 settings.sample.yaml에 씀
      python -m common.config.sample --check    # 파일이 모델과 같은지(다르면 rc 1)
"""

import sys

from common.config import settings as S
from common.core.console import utf8_stdout

OUT = S.REPO_ROOT / "settings.sample.yaml"
HEAD = """\
# settings.sample.yaml — 설정 파일 구조와 설명(값 없음). 생성: python -m common.config.sample (손으로 고치지 않음)
# 실제 파일은 이 파일을 복사해 값을 채운다 — PC: 저장소 루트 settings.yaml(RUN_ENV=local, 권한 600) · 서버: SETTINGS_FILE이 가리키는 자리
# ($SERVER_ENV_DIR/settings.yaml — 주인 UID 10001·권한 640, 컨테이너 사용자가 읽게: docs/operations/release-and-patch.md §5-4 · refactor.md C-09).
# 비운 칸(값 없음)·빈 글자 ''은 코드 기본값을 쓴다(기본값이 없는 글자 칸·[빈 글자 유지] 칸만 ''이 빈 글자 — 옛 env `X=`과 같게). 글자 칸에 쓴 yes·no·1·0은 쓴 글자 그대로.
# 켜기 칸은 true·false. 판정 꼴 표시([켬: 1만]·[끔: 0만]·[끔: ''·0·none·false])가 있는 칸은 YAML에 true·false·0·1만 — yes·on 등은
# 검증 오류(덮기 파일 overrides로 줄 때만 옛 env 판정 꼴 그대로). [auto = 비움] 칸은 auto가 "계산"(코드 기본).
# 각 앱은 common + 자기 절(pipeline 또는 mcp)만 읽는다. 비밀 칸은 출력·로그·오류 메시지에 나오지 않는다.
# 주석: 설명 · env=옛 환경변수 이름(덮기 파일 overrides·migrate가 씀 — S7e2부터 env로 준 값은 읽지 않음) · 형식 · 기본값 · [엔진 지문]/[인계 지문] =
#       그 칸을 읽는 파일이 지문에 들어가 env로도 계속 내준다(영구 다리) · [호스트] = compose·systemd·셸이 `python -m common.config.export`로 꺼내 씀.
# 덮기 파일(S7e2): 최상위 base(원본 설정 파일 경로)·overrides({옛 env 이름: 글자})만 든 yaml — 한 번 실행에 몇 칸만 바꿀 때(python -m common.config.overrides).
# 분류표: docs/refactoring/refactor_plan.md 부록 D
# [서버 옛 값: …] = 옛 옵션 카탈로그(options.conf — S7e2에 지움)·옛 서버 compose environment 기본값이 서버 컨테이너에 주던 값 — 코드 기본값과 결과가
#       다른 칸(C-39·C-45, 사용자 10-27·10-28). 서버(·PC) 설정 파일로 옮길 때 지금 동작을 지키려면 이 값을 적는다(run_mode: prod는 모든 환경 — C-43 · 빠뜨리면 PG 연결 실패 때 문서 대장·정형 저장소가 SQLite로 조용히 대체됨 — C-54).
#       ''는 빈 글자로 적어야 결과가 같은 칸(빈 글자 유지 칸·이미지 기본값이 있는 칸 — VS7e1 R-4). 옮긴 뒤 `python -m common.config.migrate --compare`로 확인.
"""
# C-39(사용자 10-27 S7e1 Q6 a) — options.conf(옛 카탈로그 — S7e2에 지움)가 env에 채우던 값 중 설정 모델 기본값과 결과가 다른 칸(값에 비밀 없음).
# output/orca/S7e1/base_calc.py로 뽑음(예외 줄 빼고 · 표기만 다른 5.0/5 빼고 · 모델 칸 없는 env 이름 빼고). sample 주석으로만 낸다(모델 기본값은 코드 기본값 그대로).
CATALOG_VALUES = {
    "AGG_TODAY": "",
    "CHUNK_TABLE": "",
    "DATA_CATALOG": "",
    "DOC_DIR": "",
    "DOC_DIR_PREPARED": "output/prepared",
    "EDW_CONN_FILE": "",
    "EDW_PATH_PREFIX": "",
    "EDW_QUERY_CONN_FILE": "",
    "EDW_QUERY_MAX_ROWS": "1000",
    "EDW_QUERY_SQLITE": "",
    "EDW_QUERY_TABLES": "",
    "EMBED_MODEL": "",
    "EMBED_QUERY_CACHE": "",
    "EMBED_QUERY_PREFIX": "",
    "INDEX_CONF": "",
    "LLM_EST_OUT_TOKENS": "1200",
    "LLM_MODEL": "",
    "LLM_SPEND_FILE": "",
    "MCP_BUNDLE": "",
    "MCP_STORE": "",
    "OV_PROCESSING_MODE": "",
    "OV_ROOT": "",
    "PADDLE_PYTHON": "",
    "PARSE_ENGINE_SCOPE": "all",
    "PARSE_POST": "all",
    "PIPE_EMBED": "",
    "RUNLOG_FILE": "",
    "RUN_MODE": "prod",
    "SECURE_DOC_PASSWORDS_FILE": "",
    "SOFFICE_BIN": "",
    "SOURCE_MANIFEST": "",
    "SOURCE_URI_PREFIX": "",
    "STRUCT_DB": "",
    "VLM_MODEL": "",
    # S7e2(사용자 10-28) — 옛 서버 compose environment 기본값(이제 settings.yaml 칸 — compose가 env로 덮지 않음). MCP_STORE는 compose가 pg로 덮었음
    "CHAIN_STRUCTURE_URL": "http://127.0.0.1:8771",
}
CATALOG_VALUES["MCP_STORE"] = "pg"
# S7e2(VS7e1 B-2) — 옛 이미지 ENV로 굽던 칸(DOC_DIR·DOC_DIR_PREPARED·PIPE_EMBED·SOFFICE_BIN)은 컨테이너에서 options.conf 값이 걸린 적이 없음(이미지 ENV가
# 먼저 있어 카탈로그 setdefault가 건너뜀) — 지금은 이미지 안 모델 기본값이 같은 값이라 표에서 뺀다(env 파일에 적은 값은 migrate가 옮김).
for _k in ("DOC_DIR", "DOC_DIR_PREPARED", "PIPE_EMBED", "SOFFICE_BIN"):
    CATALOG_VALUES.pop(_k)


def blank_matters(field):
    """빈 글자 ''를 적어야 결과가 같은 칸인가(VS7e1 R-4) — 빈 글자 유지 칸(keep)이거나, 이미지 기본값이 있어 비우면 그 기본값이 걸리는 칸(DOC_DIR 등 —
    B-2). 그 밖 칸의 ''는 비운 칸과 같은 결과라 sample 표시·migrate --compare에서 같게 본다."""
    return S.keeps_blank(field) or S.env_name(field) in {k for d in S._IMAGE_DEFAULTS.values() for k in d}


def _fmt_default(f):
    d = f.default
    if S.is_secret(f) or d is None:
        return ""
    if isinstance(d, bool):
        d = "true" if d else "false"
    elif isinstance(d, list):
        d = S.render(d, sep=S.list_sep(f)) if d else "(빈 목록)"
    return f" · 기본 {d}"


def build(classes=None):
    classes = classes or S.app_classes()
    lines = [HEAD]
    tops = {"common": None, "pipeline": None, "mcp": None}
    for cls in classes.values():
        for top in tops:
            if top in cls.model_fields and tops[top] is None:
                tops[top] = S._section_type(cls.model_fields[top].annotation)
    for top, model in tops.items():
        if model is None:
            continue
        lines.append(f"\n{top}:")
        _emit(model, 1, top, lines)
    return "\n".join(lines) + "\n"


def _emit(model, depth, path, lines):
    pad = "  " * depth
    leaves = [(n, f) for n, f in model.model_fields.items() if S._section_type(f.annotation) is None]
    subs = [(n, f) for n, f in model.model_fields.items() if S._section_type(f.annotation) is not None]
    for name, f in leaves:
        p = f"{path}.{name}"
        tags = []
        extra = f.json_schema_extra or {}
        if extra.get("pinned"):
            tags.append("[엔진 지문]" if extra["pinned"] == "engine" else "[인계 지문]")
        if S.is_host(p):
            tags.append("[호스트]")
        if S.is_secret(f):
            tags.append("[비밀]")
        if S.keeps_blank(f):
            tags.append("[빈 글자 유지]")
        truth = extra.get("truth")
        if truth:
            words = "·".join(repr(x) if x == "" else x for x in (truth["on"] or truth["off"]))
            tags.append(f"[{'켬' if truth['on'] else '끔'}: {words}{'' if len(truth['on'] or truth['off']) > 1 else '만'}]")
        if extra.get("unset") == ["auto"]:
            tags.append("[auto = 비움]")
        elif extra.get("unset") == "nondigit":
            tags.append("[숫자 아니면 비움]")
        env = S.env_name(f)
        if env in CATALOG_VALUES and (CATALOG_VALUES[env] or blank_matters(f)):
            v = CATALOG_VALUES[env]
            tags.append(f"[서버 옛 값: {v if v else repr('')}]")
        note = f"{' '.join((f.description or '').split())} · env={env} · {S.type_label(f.annotation)}{_fmt_default(f)}"
        lines.append(f"{pad}{name}:  # {note}{(' ' + ' '.join(tags)) if tags else ''}")
    for name, f in subs:
        lines.append(f"{pad}{name}:")
        _emit(S._section_type(f.annotation), depth + 1, f"{path}.{name}", lines)


def main(argv):
    utf8_stdout()
    text = build()
    if "--check" in argv:
        cur = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        ok = cur == text
        print(
            "settings.sample.yaml: 모델과 같음" if ok else "settings.sample.yaml: 모델과 다름 — python -m common.config.sample로 다시 만듦"
        )
        return 0 if ok else 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"씀: {OUT.relative_to(S.REPO_ROOT)} ({text.count(chr(10))}줄)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
