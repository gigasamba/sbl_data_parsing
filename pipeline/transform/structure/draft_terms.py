"""SI43④ — 문서에서 새 회사(고객·CDMO) 이름 후보를 찾아 용어집 draft로 넘길 목록을 만든다(구조화 쪽, 프레임워크
의존 없음 — 추출 로직은 여기, 쓰기·검색 쪽 소비는 common/terms.py write_draft_terms·expand_query가 맡는다, 설계
노트: docs/backlog/server.md SI43④ "'문서에서 새 이름을 찾는' 단계는 구조화·파싱 쪽이라 terms.py 안에서
끝나는 작업이 아님").

ponytail: 정규식 휴리스틱(법인 접미사 뒤 한글·영문 이름만) — 실제 NER이 아님, 접미사 목록 밖의 이름(순수 고유명사만,
접미사 없음)은 못 찾음. 업그레이드 경로: 접미사 목록을 글로서리 category=org_suffix 같은 데이터로 옮기거나 LLM 음역
후보(서버 쪼개서, 선택 — 백로그 ④ 노트)로."""

import re

_SUFFIX_KO = ("바이오로직스", "테라퓨틱스", "헬스케어", "바이오", "제약", "파마")
_ORG_RE_KO = re.compile(r"[가-힣]{2,12}(?:" + "|".join(_SUFFIX_KO) + r")(?:\(주\))?")
_ORG_RE_EN = re.compile(
    r"\b[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+){0,3}\s"
    r"(?:Inc\.|Corp\.|Co\.,?\s*Ltd\.?|Ltd\.|Pharma|Pharmaceuticals?|Biologics|Therapeutics)(?![A-Za-z0-9])"
)
# ↑ 끝은 \b가 아니라 lookahead — "Inc."처럼 마지막 글자가 '.'(비 단어 문자)로 끝나면 바로 뒤가 공백(역시 비
# 단어 문자)일 때 \b가 성립하지 않아(단어·비단어 경계가 없음), 탐욕 수량자가 "Biologics Inc."의 "Inc."까지
# 못 먹고 "Biologics"(접미어 목록에 있는 업종어라 그 자체로 매칭 성립)에서 멈춰버리는 조기 종료가 있었다
# (실측 selftest: "Northfield Biologics Inc." → "Northfield Biologics"로 잘림).


def extract_candidate_orgs(text):
    """text에서 후보 회사 이름을 찾는다(한글 법인 접미사·영문 법인 접미사/업종어, 결정적 순서 — 처음 나온 순).
    중복(같은 이름 여러 번 언급)은 한 번만."""
    if not text:
        return []
    seen, out = set(), []
    for m in list(_ORG_RE_KO.finditer(text)) + list(_ORG_RE_EN.finditer(text)):
        name = m.group(0).strip()
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def collect_candidate_org_names(docs, known_norm, norm):
    """docs(build_bundle.py main()의 doc dict 목록, full_text 키) 전체에서 candidate 회사 이름 → known_norm(이미 아는
    이름의 norm() 집합, 명부·용어집 전 카테고리) 밖인 것만, 등장 횟수 많은 순 · 동률은 이름순(결정적)."""
    counts = {}
    for d in docs:
        for name in extract_candidate_orgs(d.get("full_text") or ""):
            if norm(name) in known_norm:
                continue
            counts[name] = counts.get(name, 0) + 1
    return [name for name, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
