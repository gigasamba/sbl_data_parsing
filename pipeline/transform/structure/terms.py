"""고객 명부(roster) — 구조화 전용. name_hits(이름 등장 횟수, 경계·한글 조사 인식)·seed_roster(기본 명부 seed,
10-14 다중 고객 라벨). 공용 로더(read_roster)·공용 조사 규칙(PARTICLES)은 common.core.terms에서 그대로 가져다
쓴다(캐시·로더는 공용 한 곳 — 복제 금지)."""

import functools
import re
from pathlib import Path

from common.core.paths import GLOSSARY_ROOT
from common.core.terms import PARTICLES, read_roster

SEED_ROSTER_PATH = GLOSSARY_ROOT / "client_roster_seed.json"  # 10-14 다중 고객 라벨 — 바이오·제약 주요사 공개 이름 seed


@functools.cache
def _hit_pat(name):
    """name_hits() 전용 경계 정규식 — common.core.terms._name_pat과 같은 철학(한글 조사 PARTICLES·단어 경계)이지만
    두 가지를 고친다(독립 검토 10-14): ① 경계를 `\\b` 대신 `(?<![...])`·`(?![...])`(_DEF_BOUND과 같은 스타일)로 —
    `\\b`는 양쪽이 "단어/비단어"로 달라야만 성립해서, 이름이 비한글·비영숫자로 끝나면(예 '미르하제약(주)') 그 뒤도
    비단어 문자일 때 경계 자체가 안 생겨 매칭이 실패한다(실측: `\\b미르하제약\\(주\\)\\b`가 '…미르하제약(주) /
    mrh…'에서 0건). 같은 경계 방식이 "MSD"가 "MSDS" 안에서 걸리는 것도 막는다(경계 없는 raw substring count
    였던 옛 버그의 공용 수정). ② 한글 조사는 이름이 한글로 끝날 때만이 아니라 **항상** 허용 — 'Celltrion과'처럼
    외래어·영문 로마자 뒤에도 조사가 공백 없이 바로 붙는 한국어 표기가 흔하다(match_clients의 영문 경로가
    경계 없는 substring으로 이 경우를 흡수하던 것의 보다 정확한 대체). 이름 안 공백은 `\\s*`로(OCR 공백 차이
    허용 — 'Contoso Pharma'·'ContosoPharma' 둘 다). `_name_pat`(match_clients·expand_query가 씀, 전부
    영숫자로 끝나는 이름이라 이 차이가 안 드러남)은 그대로 두고 건드리지 않는다 — 새 함수로 여기만."""
    esc = re.escape(name).replace(r"\ ", r"\s*")
    alt = "|".join(sorted(PARTICLES, key=len, reverse=True))
    pat = rf"(?<![a-z0-9가-힣]){esc}(?:{alt})?(?![a-z0-9가-힣])"
    return re.compile(pat, re.I)


def name_hits(name, text):
    """이름(별칭 등)이 글 안에 **몇 번** 나오는지 — _hit_pat(단어 경계·한글 조사, _name_pat과 같은 철학이지만
    경계·조사 처리를 고친 전용 버전) 기준. name·text는 원문 그대로 넘긴다(공백 유지 — _hit_pat이 이름 안
    공백만 `\\s*`로 허용하고 나머지 경계는 그대로 판정, 대소문자는 re.I). 빈 이름은 0."""
    return len(_hit_pat(name).findall(text)) if name else 0


def seed_roster(path=None):
    """구조화 기본 고객 명부 seed(10-14) — 사람이 아는 주요 바이오·제약사 공개 한/영 표기만(지어낸 이름 없음),
    CLIENT_ROSTER(서버 SFDC 내보내기)·GLOSSARY_DIR org_client가 비어 있어도 build_bundle.py infer_clients()가 바닥값으로
    씀(common.core.terms._aliases()는 그대로 — BM25 질의 확장·expand_query 쪽 기존 시험·동작은 안 바뀜, 문서
    라벨링에만 더함). read_roster()와 같은 형식(JSON {이름: [별칭…]}) 재사용. 파일 없으면 빈 사전(동작 그대로)."""
    p = Path(path) if path else SEED_ROSTER_PATH
    if not p.exists():
        return {}
    return read_roster(p)
