"""settings.yaml 옮기기 — 옛 배치 settings.yaml(최상위 common·pipeline·mcp — op-08 전, 0.1.0 서버) → 새 배치(required·역할 절·tuning,
common.config.layout). 0.1.0 → 0.2.0 서버 판 올리기에 쓴다(release-and-patch §8 — 사용자 11-02: 운영 서버는 0.1.0, settings.yaml 하나).
  · 값은 쓴 글자 그대로 옮긴다(1.10·0123·yes가 바뀌지 않게). 지운 칸(모델 REMOVED — op-08 등)은 "삭제됨",
    모델에 없는 칸은 "모름"으로 이름(옛 자리)만 알리고 새 파일에 넣지 않는다. 덮기 파일의 base·overrides는 그대로 둔다.
  · 화면 출력은 비밀 칸을 "<가림>"으로 바꾼 YAML. --out으로 파일에 쓸 때만 실제 값이 들어가고 권한은 600(있으면 --force).
  · (11-02 지움 — 사용자: 운영 서버는 0.1.0) 옛 env 파일(pipeline.env 등) → settings.yaml 옮기기와 `--compare`(옛 options.conf 카탈로그 대조).
사용: python -m common.config.migrate <옛 settings.yaml> [--out <새 파일> [--force]] [--summary]
"""

import argparse
import os
import sys
from pathlib import Path

from common.config import layout as L
from common.config import settings as S
from common.core.console import utf8_stdout

MASK = "<가림>"


def _removed(model, prefix=""):
    """지운 칸(Section.REMOVED)의 모델 경로 — 옛 파일에 남아 있으면 "삭제됨"으로 알린다."""
    out = {prefix + n for n in getattr(model, "REMOVED", ())}
    for name, f in model.model_fields.items():
        sub = S._section_type(f.annotation)
        if sub is not None:
            out |= _removed(sub, f"{prefix}{name}.")
    return out


def _raw(v):
    """YAML 값을 쓴 글자·꼴 그대로 다시 쓰게(settings._Raw) — 글자는 글자로, 숫자·켜기·날짜는 쓴 표기 그대로."""
    if isinstance(v, S.YamlScalar):
        return str(v) if isinstance(v.value, str) else S._Raw.of(v)
    if isinstance(v, dict):
        return {str(k): _raw(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_raw(x) for x in v]
    return v


def convert_yaml(path, classes, secrets=True):
    """옛 배치 settings.yaml → (새 배치 사전, 보고 {"삭제됨": [옛 자리], "모름": [옛 자리], "칸": n}). secrets=False면 비밀 값은 MASK."""
    raw = S.read_yaml(path)
    extra = {k: raw.pop(k) for k in S.OVERLAY_KEYS if k in raw}
    if raw and not L.is_old(raw):
        raise S.SettingsError(f"이미 새 배치(또는 옛 배치가 아님): {path}")
    leaves, removed = {}, set()
    for cls in classes.values():
        leaves.update({p: f for p, f, _ in S.walk(cls)})
        removed |= _removed(cls)
    doc, report = {}, {"삭제됨": [], "모름": [], "칸": 0}

    def walk(d, prefix):
        for k, v in d.items():
            p = f"{prefix}{k}"
            if p in leaves:
                if v is not None:
                    L.set_path(doc, p, v if secrets or not S.is_secret(leaves[p]) else MASK)
                    report["칸"] += 1
            elif p in removed:
                report["삭제됨"].append(p)
            elif isinstance(v, dict) and any(x.startswith(p + ".") for x in leaves):
                walk(v, p + ".")
            elif v is not None:
                report["모름"].append(p)

    walk(raw, "")
    return {**_raw(extra), **L.to_file(_raw(doc))}, report


def dump_yaml(doc, origin="옛 배치에서 새 배치(op-08 ②)로 바꿈"):
    import yaml

    head = f"# settings.yaml — common.config.migrate가 {origin}. 칸 설명은 저장소 settings.sample.yaml\n"
    return head + yaml.dump(doc, Dumper=S._raw_dumper(), allow_unicode=True, sort_keys=False, default_flow_style=False)


def run_yaml(a, classes):
    if not {"pipeline", "mcp"} <= set(classes):  # 이미지 하나엔 다른 앱 모델이 없어 그 칸을 "모름"으로 버림 — 코드 폴더(두 앱 다)에서만
        print("[migrate] pipeline·mcp 설정 모델이 다 있는 코드에서 실행(저장소·코드 폴더 — 이미지 하나 안에서는 안 됨)", file=sys.stderr)
        return 2
    try:
        doc, report = convert_yaml(a.file, classes, secrets=bool(a.out))
    except S.SettingsError as e:
        print(f"[migrate] {e}", file=sys.stderr)
        return 2
    print(f"[migrate] 옛 배치 → 새 배치(op-08 ②): 옮긴 칸 {report['칸']}개", file=sys.stderr)
    for kind in ("삭제됨", "모름"):
        if report[kind]:
            print(f"  {kind} {len(report[kind])}(새 파일에 넣지 않음): {' '.join(report[kind])}", file=sys.stderr)
    if a.out:
        write_private(a.out, dump_yaml(doc), a.force)
        print(f"[migrate] 씀: {a.out} (권한 600)", file=sys.stderr)
    elif not a.summary:
        print(dump_yaml(doc), end="")
    return 0


def write_private(path, text, force=False):
    """권한 600으로 새로 씀(있으면 force일 때만 — 덮기 전 지움)."""
    p = Path(path)
    if p.exists():
        if not force:
            raise FileExistsError(f"{p} 있음 — 덮으려면 --force")
        p.unlink()
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    if os.name != "nt":
        os.chmod(p, 0o600)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("file", help="옛 배치 settings.yaml")
    ap.add_argument("--out")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--summary", action="store_true", help="YAML은 찍지 않고 수만")
    a = ap.parse_args(argv)
    if not a.file.endswith((".yaml", ".yml")):
        print(
            "[migrate] 옛 배치 settings.yaml(.yaml·.yml)만 받음 — env 파일 옮기기는 11-02에 지움(0.1.0 서버는 settings.yaml)",
            file=sys.stderr,
        )
        return 2
    return run_yaml(a, S.app_classes())


if __name__ == "__main__":
    utf8_stdout(errors=None)
    raise SystemExit(main())
