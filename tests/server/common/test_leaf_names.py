"""op-05 — settings.sample.yaml의 칸(잎) 이름은 파일 전체에서 하나뿐이다(절 경로 없이 이름만 보고도 어느 칸인지 안다).
표 한 줄 = 견줄 묶음 하나. 외부 접속 없음."""

from collections import Counter

import yaml

from common.config import layout, sample


def _leaves(node):
    for k, v in node.items():
        yield from _leaves(v) if isinstance(v, dict) and k != "library_env" else (k,)


def _model_leaves():
    return [layout.to_yaml(m).rpartition(".")[2] for m in sample.NOTES]


CASES = (
    ("생성한 sample의 잎 이름", lambda: list(_leaves(yaml.safe_load(sample.build())))),
    ("모델 칸의 파일 자리 잎 이름(NOTES 전체)", _model_leaves),
)


def test_leaf_names_unique():
    for what, get in CASES:
        names = get()
        dups = sorted(k for k, n in Counter(names).items() if n > 1)
        assert names and not dups, f"{what}: 같은 이름 {dups}"
