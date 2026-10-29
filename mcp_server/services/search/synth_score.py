"""합성 평가셋 정답 키워드 채점(answer_keywords·forbid_keywords — 리스트=AND, 'a|b'=OR, 'A~B'=20자 안, 'A~~B'=같은 줄) ·
표 칸 채점 · 키워드 포함 판정(kw_in). qa.json의 "scoring": "_synth_images_qa.score"가 가리키는 규칙의 정본.

10-14 — dev_tools/synthetic_data_gen/_synth_images_qa.py에서 채점 부분만 이리로 옮김: evaluation/mcp_eval.py·cli/eval_research.py가
모듈 맨 위에서 tools/를 sys.path에 넣어 import했는데 이미지에는 deploy/만 들어가 import 단계에서 실패(운영자 selftest의 mcp_eval
포함). 문항 만들기 쪽(build_qa·strengthen_keywords·selfcheck)은 생성기 전용이라 tools/에 남고 이 모듈을 다시 내보낸다."""

import re
import unicodedata

# W6 — 위·아래첨자 정규화는 공용 helper(common/text.py supsub_mark)로 통일(score_gold.canon()·parse_qa.norm()과 같은 규칙).
from common.core.text import supsub_mark

# 마크다운 굵게·기울임 제거(BR27a) — 답이 "**16**"처럼 감싸도 키워드 "16"에 걸리게. **/__ 먼저(겹치면 먼저 없어져야
# 단독 */_ 패턴이 남은 글자를 다시 감싸는 걸로 오인하지 않음), 그다음 단독 */_ — 양쪽 다 글자(\w, 한글 포함) 바로 옆이면
# 안 건드린다(engine-qa CONCERN① — "C_SOL_2021"처럼 ID 안의 '_'가 "csol2021"로 깨지던 결함, 공백·구두점일 때만 강조 표시로 봄).
_MD_EMPH_RE = [
    re.compile(r"\*\*(.+?)\*\*"),
    re.compile(r"__(.+?)__"),
    re.compile(r"(?<![\w*])\*([^*\s][^*\n]*?)\*(?![\w*])"),
    re.compile(r"(?<![\w_])_([^_\s][^_\n]*?)_(?![\w_])"),
]
_DIGIT_END_RE = re.compile(r"\d$")
# [구판]·구판·이전 판·superseded가 적힌 "줄" 안에서도 forbid 값 글자 자체만 지운다(BR21, engine-qa 2차 BLOCK —
# 부정·대조어 차단 목록은 "구판 기준으로 보면 60,000원"·"구판 수치 그대로 60,000원"·"최종 단가: 60,000원(구판
# 참조)"·"60,000원(구판)이 현재 계약가"·"Per the superseded sheet, the price is 60,000"처럼 부정어 없이도
# 구판 값을 결론으로 쓰면 우회됐다 — 부정어 목록을 버리고 "정답 값이 같은 줄에 같이 있다"는 양성 신호로 바꾼다:
# answer_keywords(정답) 중 하나라도 그 줄에 없으면 지우지 않는다(forbid가 그대로 걸림) — answer_keywords가 없는
# 문항은 아예 안 지운다(보수적, score()에서 처리).
_DISCLOSURE_RE = re.compile(r"구판|이전\s*판|superseded", re.IGNORECASE)

# coordinator 10-12 되돌림 — 'CO2'(마커 없는 평문 키워드)가 'CO₂'(유니코드 아래첨자) 원문과 안 맞는 회귀가 났음
# (supsub_mark가 양쪽에 똑같이 안 걸리면 'co2' vs 'co_2'로 갈라짐). 평문 키워드는 옛(BR27c) 동작과 바이트
# 동일하게(위첨자만 마커, 아래첨자·태그는 그대로 둬 NFKC가 바로 접게) · 마커가 있는 키워드('10^5'·'CO_2'·
# '10<sup>5'처럼 ^·_·<sup>·<sub>·유니코드 위/아래첨자를 직접 쓴 쪽)만 새(W6) supsub_mark 규칙 — 어느 쪽을 쓸지는
# **키워드**(text 아님)가 정한다. "|" 대안 안에서도 각 대안이 따로 고름(kw_in이 _has_marker(kw) 한 번만 봄 —
# "A~~B" 안의 A·B는 같은 모드를 같이 씀, 실 데이터("CL-03~~10^5|CL-03~~10<sup>5")가 대안 전체 단위라 충분).
_MARKER_RE = re.compile(r"[\^_]|<\s*sup\s*>|<\s*sub\s*>|[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻₀₁₂₃₄₅₆₇₈₉₊₋]", re.I)
_OLD_SUP_MAP = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "⁻": "-"}
_OLD_SUP_RE = re.compile("[" + "".join(_OLD_SUP_MAP) + "]+")


def _has_marker(kw):
    return bool(_MARKER_RE.search(kw))


def _norm_legacy(t):
    """평문 키워드 경로 — main의 옛(BR27c) _norm과 바이트 동일: 마크다운 굵게 제거 → 위첨자만 '^n'로(아래첨자·
    태그는 안 건드려 NFKC가 바로 접게, 'CO₂'→'co2') → NFKC·소문자·쉼표 제거."""
    s = str(t)
    for pat in _MD_EMPH_RE:
        s = pat.sub(r"\1", s)
    s = _OLD_SUP_RE.sub(lambda m: "^" + "".join(_OLD_SUP_MAP[c] for c in m.group(0)), s)
    return unicodedata.normalize("NFKC", s).lower().replace(",", "")


def _norm(t):
    """마커 있는 키워드 경로 — 마크다운 굵게 제거 → 위/아래첨자를 '^n'/'_n'로(supsub_mark, <sup>·<sub> 태그까지
    — W6) → NFKC·소문자·쉼표 제거(이 순서라야 '**10⁵**'·'CO_2'도 맞게 된다)."""
    s = str(t)
    for pat in _MD_EMPH_RE:
        s = pat.sub(r"\1", s)
    s = supsub_mark(s)
    return unicodedata.normalize("NFKC", s).lower().replace(",", "")


def _pick_norm(kw):
    """kw(비교할 키워드 쪽)가 첨자 마커를 직접 쓰면 새 규칙(_norm), 평문이면 옛 규칙(_norm_legacy) — coordinator 10-12."""
    return _norm if _has_marker(kw) else _norm_legacy


def kw_in(kw, text):
    """kw가 text 안에 있나(둘 다 이 함수 안에서 정규화, 정규화 방식은 kw 자체가 마커를 쓰는지로 고름 — 위) —
    'A~B' = A 뒤 20자 안에 B(라벨과 값이 짝으로, 막대 라벨·값 엇갈림 실측) · 'A~~B' = 같은 줄(표 한 행, 160자
    안) · 그 외 그대로 포함. B(또는 단독 kw)가 숫자로 끝나면 바로 뒤에 숫자가 오지 않을 때만 일치로 센다
    (BR27b — '배치 수 16'이 '배치 수 160' 안에 안 걸리게)."""
    norm = _pick_norm(kw)
    t = norm(text)
    if "~~" in kw:
        x, y = (norm(p) for p in kw.split("~~", 1))
        pat = re.escape(x) + r"[^\n]{0,160}?" + re.escape(y) + (r"(?!\d)" if _DIGIT_END_RE.search(y) else "")
        return re.search(pat, t) is not None
    if "~" in kw:
        x, y = (norm(p) for p in kw.split("~", 1))
        pat = re.escape(x) + r".{0,20}?" + re.escape(y) + (r"(?!\d)" if _DIGIT_END_RE.search(y) else "")
        return re.search(pat, t, re.S) is not None
    k = norm(kw)
    if _DIGIT_END_RE.search(k):
        return re.search(re.escape(k) + r"(?!\d)", t) is not None
    return k in t


def _mask_disclosed_value(norm_text, norm_value, correct_forms):
    """norm_value(이미 _norm()된 forbid 값)가 [구판]·구판·이전 판·superseded 라벨이 있는 줄에 있고, 그 줄에
    correct_forms(정답 answer_keywords를 '|'로 펼쳐 이미 _norm()한 목록) 중 하나라도 같이 있을 때만 그 값
    글자를 지운다(BR21 2차 — 양성 신호: '구판 고지' 줄에 최신 값도 같이 적혀 있어야 진짜 고지로 본다). 줄은
    보통 kw_in의 '~~'(같은 줄 160자) 범위보다 짧다. correct_forms가 비면(answer_keywords 없음) 아예 안 지운다
    (score()에서 호출 전에 걸러짐)."""
    if not norm_value or not correct_forms:
        return norm_text
    out = list(norm_text)
    for m in re.finditer(r"[^\n]*", norm_text):
        line, base = m.group(0), m.start()
        if not line or not _DISCLOSURE_RE.search(line) or not any(cf and cf in line for cf in correct_forms):
            continue
        for vm in re.finditer(re.escape(norm_value), line):
            for i in range(base + vm.start(), base + vm.end()):
                out[i] = " "
    return "".join(out)


def score(item, answer, attachments=()):
    """qa.json 채점 규칙 그대로 — 답 문자열(+ 첨부 image_id 목록) → True/False. correct_forms·forbid 비교도
    kw_in과 같은 규칙(각 대안·forbid 키워드 자신이 마커를 쓰는지로 정규화 방식을 고름 — coordinator 10-12)."""
    ok = all(any(kw_in(alt, answer) for alt in kw.split("|")) for kw in item["answer_keywords"])
    correct_forms = [_pick_norm(alt)(alt) for kw in (item.get("answer_keywords") or []) for alt in kw.split("|")]
    for f in item.get("forbid_keywords", []):
        norm_f = _pick_norm(f)
        if kw_in(f, _mask_disclosed_value(norm_f(answer), norm_f(f), correct_forms)):
            ok = False
            break
    if item.get("expected_attachments"):
        ok = ok and bool(set(attachments) & set(item["expected_attachments"]))
    return ok


def score_table(gold_table, answer):
    """synth-4clients table_aggregate 문항 채점(BR20) — gold_table의 행마다 (그룹 키, 값) 쌍과 totals 값이
    답 안에 모두 있어야 정답. 표('| 키 | 값 |' 한 줄)·문장('키: 값') 둘 다 kw_in의 '~~'(같은 줄 160자 안)로
    인정. 고객명 한/영 별칭은 _synth4c_content._NAME_ALIAS(기존 글로서리, compare_meta가 쓰는 것과 같은 표)로
    그룹 키 쪽만 넓힌다(QA111 — 답이 '화이자'라고 써도 'Pfizer Inc.' 행과 맞게). totals는 라벨과 안 묶고 값만
    어디든 있으면 인정(열 이름이 번역·재배열돼도 맞게 — 라벨까지 묶으면 QA005류 영문 열 이름이 깨짐)."""
    from _synth4c_content import _NAME_ALIAS

    for row in gold_table.get("rows") or []:
        if not row:
            continue
        key = str(row[0])
        forms = [key] + list(_NAME_ALIAS.get(key, []))
        for val in row[1:]:
            if not any(kw_in(f"{form}~~{val}", answer) for form in forms):
                return False
    for val in (gold_table.get("totals") or {}).values():
        if not kw_in(str(val), answer):
            return False
    return True
