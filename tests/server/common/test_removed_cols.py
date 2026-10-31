"""0.1.0 지문 배치(pl-21·pl-31)·op-08 — 지운 설정 칸(Section.REMOVED)이 남은 settings.yaml도 시작은 된다(경고만, 한 판 동안).
서버(run_env: dev)는 모르는 칸이면 시작 거부(STRICT)라, REMOVED 이름에 오타가 있으면 여기서 실패한다. 옛 배치(op-08 전) 파일은
migrate가 새 배치로 바꾸며 지운 칸을 "삭제됨"으로 알리고 빼는지도 본다. 외부 접속 없음, 임시 폴더만."""

import tempfile
from pathlib import Path

from common.config.settings import CommonAppSettings, SettingsError, app_classes, load

COMMON_NEW = """required:
  env: {run_env: dev}
common:
  models:
    llm: {max_concurrency: 8}
    vlm: {model_alt: m}
    ocrvlm: {base_url: http://x/v1, model: m}
  store: {registry_retry_max: 7}
ops:
  paths: {korean_font: /f.ttf, eval_sets_dir: /x}
  runtime: {exp_max_workers: 4, exp_proc_gb_answer: 1, exp_proc_gb_build: 1, exp_proc_gb_run: 1, exp_reserve_gb: 4}
  nightly: {enabled: true}
dev:
  exp_store: /s
  llm_est_in_tokens: 1
  llm_est_out_tokens: 2
  min_gold_coverage: 0.9
  eval: {diagram_raster_vlm: false}
transform:
  structure: {wiki_domain_phrase: x}
  figures: {ocrvlm_prompt: p}
"""
OLD = """common:
  run_env: dev
  paths: {korean_font: /f.ttf}
  connections:
    pg: {host: h}
pipeline:
  extract:
    cache: {parse_tmp_max_gb: 1}
    disk_free_warn_gb: 3
  host:
    nightly: {enabled: true}
mcp:
  search:
    agg: {llm_min: 0.5}
"""


def test_old_removed_settings_only_warn():
    with tempfile.TemporaryDirectory() as d:
        y = Path(d) / "removed.yaml"
        y.write_text(COMMON_NEW, encoding="utf-8")
        assert load(CommonAppSettings, file=y, environ={}).common.run_env == "dev"
        pipe = app_classes(("pipeline",)).get("pipeline")
        if pipe is not None:  # mcp 이미지에는 pipeline 앱이 없음
            load(pipe, file=y, environ={})


def test_old_layout_rejected_and_migrated():
    from common.config import migrate

    with tempfile.TemporaryDirectory() as d:
        y = Path(d) / "old.yaml"
        y.write_text(OLD, encoding="utf-8")
        try:
            load(CommonAppSettings, file=y, environ={})
            raise AssertionError("옛 배치가 거부되지 않음")
        except SettingsError as e:
            assert "common.config.migrate" in str(e), e
        classes = app_classes()
        doc, report = migrate.convert_yaml(y, classes)
        assert doc["required"]["env"]["run_env"] == "dev" and doc["required"]["pg"]["host"] == "h", doc
        gone = {"common.paths.korean_font", "pipeline.host.nightly.enabled"}
        if "pipeline" in classes:
            gone |= {"pipeline.extract.cache.parse_tmp_max_gb", "pipeline.extract.disk_free_warn_gb"}
        if "mcp" in classes:
            gone.add("mcp.search.agg")  # mc-04(11-01) — 절째 지움(옛 llm_min 칸 대신 절 이름으로 보고)
        assert gone <= set(report["삭제됨"]), report
