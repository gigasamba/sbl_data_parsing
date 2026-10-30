"""0.1.0 지문 배치(pl-21) — 지운 설정 칸이 남은 옛 서버 settings.yaml도 시작은 된다(Section.REMOVED — 경고만, 한 판 동안).
서버(run_env: dev)는 모르는 칸이면 시작 거부(STRICT)라, REMOVED 이름에 오타가 있으면 여기서 실패한다. 외부 접속 없음, 임시 폴더만."""

import tempfile
from pathlib import Path

from common.config.settings import CommonAppSettings, app_classes, load

COMMON_OLD = """common:
  run_env: dev
  paths: {korean_font: /f.ttf, eval_sets_dir: /x}
  dev: {exp_store: /s, llm_est_in_tokens: 1, llm_est_out_tokens: 2, min_gold_coverage: 0.9}
  runtime: {exp_max_workers: 4, exp_proc_gb_answer: 1, exp_proc_gb_build: 1, exp_proc_gb_run: 1, exp_reserve_gb: 4}
  models:
    llm: {max_concurrency: 8}
"""
PIPELINE_OLD = """pipeline:
  transform:
    structure: {wiki_domain_phrase: x}
  eval: {diagram_raster_vlm: false}
"""


def test_old_removed_settings_only_warn():
    with tempfile.TemporaryDirectory() as d:
        y = Path(d) / "old.yaml"
        y.write_text(COMMON_OLD, encoding="utf-8")
        st = load(CommonAppSettings, file=y, environ={})
        assert st.common.run_env == "dev"
        pipe = app_classes(("pipeline",)).get("pipeline")
        if pipe is not None:  # mcp 이미지에는 pipeline 앱이 없음
            y.write_text(COMMON_OLD + PIPELINE_OLD, encoding="utf-8")
            load(pipe, file=y, environ={})
