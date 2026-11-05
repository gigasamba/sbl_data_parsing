"""settings.yaml ops.nightly.nightly_start_time·nightly_stop_time(모델 pipeline.host.nightly — NIGHTLY_TIME·NIGHTLY_DEADLINE, pl-32·사용자 11-02): 비움·공백만 = 새벽 배치 없음(None),
HH:MM만 받음, 틀린 꼴은 서버(STRICT)가 설정 읽기에서 거부. max_docs(NIGHTLY_MAX_DOCS)는 1 이상 정수.
PR #44 리뷰 — `start_time: ""`가 꼴 검사에 걸려 서버 시작이 막히던 것. 외부 접속 없음, 임시 폴더만."""

import tempfile
from pathlib import Path

from common.config import layout
from common.config.settings import SettingsError, app_classes, load

CASES = [  # (YAML 값, 기대 — None = 없음, 글자 = 그 시각, SettingsError = 거부)
    ('""', None),
    ('"  "', None),
    ("", None),  # 값 없는 칸(`start_time:`)
    ('"08:09"', "08:09"),
    ('"23:59"', "23:59"),
    ('"25:00"', SettingsError),
    ('"1:30"', SettingsError),
    ('"01:30:00"', SettingsError),
]


def test_nightly_time():
    pipe = app_classes(("pipeline",)).get("pipeline")
    if pipe is None:  # mcp 이미지에는 pipeline 앱이 없음
        return
    with tempfile.TemporaryDirectory() as d:
        y = Path(d) / "settings.yaml"
        cases = [(k, raw, want) for k in ("time", "deadline") for raw, want in CASES] + [  # 모델 칸 이름 — 파일 자리는 layout.to_yaml
            ("max_docs", "", None),
            ("max_docs", "50", 50),
            ("max_docs", "0", SettingsError),
        ]
        for k, raw, want in cases:
            leaf = layout.to_yaml(f"pipeline.host.nightly.{k}").rsplit(".", 1)[1]
            y.write_text(f"required:\n  env: {{run_env: dev}}\nops:\n  nightly:\n    {leaf}: {raw}\n", encoding="utf-8")
            if want is SettingsError:
                try:
                    load(pipe, file=y, environ={})
                    raise AssertionError(f"{k}: {raw} — 거부 안 됨")
                except SettingsError:
                    continue
            assert getattr(load(pipe, file=y, environ={}).pipeline.host.nightly, k) == want, (k, raw)
