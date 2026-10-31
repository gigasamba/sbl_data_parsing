"""AD20(남은 것, 10-08) — pptx_edges.candidate_slides()가 고른 슬라이드(연결선 없는 도형 배치·SmartArt)만
LibreOffice headless로 PDF 변환 → 그 쪽만 이미지 렌더 → 기존 쪽 VLM 경로(vlm_page.vlm_page, 같은 캐시·상한·가드)로 옮긴다.
candidate_slides() 자체는 어디서도 안 불리던 상태(바이트 영향 0)였는데 이 모듈이 그 유일한 호출자다.

설정 soffice_bin(SOFFICE_BIN) → PATH의 soffice/soffice.exe 순으로 찾고(op-09 — 설치 경로 추측 없음), 다 없으면 조용히
건너뜀(이전 동작과 바이트 동일) — 못 찾으면 이 프로세스에서 1번만 stderr 경고(독립 검토 10-13, 매 문서 반복 아님).
PARSE_PPTX_RENDER_MAX(env, 기본 10) — 문서당 실제 렌더·VLM 호출할 슬라이드 상한(candidate_slides 자체 상한 20+20과 별개 안전판
— LibreOffice 변환은 슬라이드 수와 무관하게 문서 1번이지만 VLM 호출은 쪽마다라 비용이 큼).
PARSE_PPTX_CONVERT_SEC(env, 기본 60초) — soffice 변환 시간 상한, 넘으면 그 자식 프로세스만 종료(이름 단위 taskkill 금지)하고 빈 결과.
임시 PDF는 raw_root()/tmp/pptx_render/ 아래(output/ 밖에 안 씀) — TemporaryDirectory가 끝나면 자동 삭제(고아 없음).

AD20 후속(10-11) — target_slides()가 '실제로 쪽 VLM이 호출될 슬라이드' 집합을 한 곳에서 계산해 pptx_slide_vlm()이
그대로 쓰고, post/figures.py가 그 슬라이드의 삽입 그림(shape_type==13)을 건너뛰어 같은 내용이 그림 VLM·쪽 VLM
둘로 겹쳐 기록되지 않게 한다(우선순위: 쪽 VLM이 슬라이드 전체 — 그림 VLM은 생략).

AD14(10-13) — docx·xlsx의 도형 도식(텍스트 상자·연결선·SmartArt, 삽입 이미지 없음)은 pptx처럼 슬라이드 단위가
아니라 soffice가 전체 문서를 한 번에 여러 쪽 PDF로 바꾸므로 shape_render_pages()를 **따로** 둔다(pptx 쪽
render_slides·target_slides·pptx_slide_vlm은 그대로 — 바이트 영향 0). shape_detect.py의 cheap 문턱(soffice
호출 전 문서/drawing 단위 bool)을 지나면 문서 전체를 한 번 변환해 열고, 쪽마다 '벡터 그려진 것이 있고 래스터
이미지가 없음'(get_drawings() 있음 + get_images() 없음 — 백로그가 제시한 바로 그 규칙)인 쪽만 그림 후보로
돌려준다(늘 켬 — 끄기 스위치는 op-08에 지움). PARSE_PPTX_RENDER_MAX·PARSE_PPTX_CONVERT_SEC
재사용(새 env 없음) — postprocess.figures._office_shape_figures()가 이 목록을 그림 레코드로 바꿔 보통 그림과
같은 VLM·캡 경로를 탄다."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # dev/
from pipeline import config as pc  # noqa: E402 — pipeline 칸 설정 객체(S7c)
from pipeline.shared.postprocess import raw_root  # noqa: E402
from pipeline.transform.figures import shape_detect  # noqa: E402 — AD14
from pipeline.transform.figures.pptx_edges import candidate_slides  # noqa: E402
from pipeline.transform.figures.vlm_page import DPI, sha, vlm_page  # noqa: E402


def _cap(name, default):
    return int(
        pc.by_env(name, default)
    )  # S7c — 설정 객체(옛 int(get(name, default)), ValueError면 int(default) — 객체는 ''·형식 틀림 = 칸 기본값)


_conversion_ok: dict = {}  # 독립 검토 반영(10-11, AD31/AD20 BLOCK) — ponytail: 프로세스 수명 동안의 dict(경로 문자열 키,
# 영속화 안 함) — pptx_slide_vlm()이 실제 soffice 변환 성공/실패를 기록해 target_slides()가 예측(후보+soffice 유무)
# 대신 실제 결과를 반영하게 한다. 한 배치 프로세스는 같은 경로를 보통 한 번만 처리하므로 경로 키만으로 충분 —
# 같은 경로가 다른 내용으로 재사용되는 시나리오가 생기면 (경로, sha256) 키로 올림.

_soffice_warned = [False]  # 독립 검토(10-13) — soffice_bin()이 끝까지 못 찾으면 이 프로세스에서 1번만 stderr 경고
# (이전엔 pptx_slide_vlm()이 호출마다 — 문서마다 — 찍어 배치에서 같은 줄이 반복됐고, target_slides()·render_slides()
# 호출부는 아예 안 찍어 조용히 꺼진 채 티가 안 났다. 한 곳(soffice_bin 자신)에서만 찍으면 모든 호출부가 같은
# 경고를 공유(중복 구현 없음).


def soffice_bin():
    """설정 soffice_bin(파일로 존재해야 유효) → PATH의 soffice·soffice.exe — 다 없으면 None, 이 프로세스에서 처음 한 번만
    stderr 경고(_soffice_warned — 조용한 건너뜀이 배치 로그에서 안 보이던 문제, 매 문서 반복 대신 1회). op-09 — 흔한 설치
    경로(Program Files·/usr/lib·/opt) 추측은 지움: PATH에 없으면 settings.yaml soffice_bin을 채운다(이미지는 /usr/bin/soffice 기본값)."""
    v = pc.cfg().paths.soffice_bin  # S7c — 설정 객체
    if v:
        return v if Path(v).exists() else None
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    if not _soffice_warned[0]:
        _soffice_warned[0] = True
        print(
            "[pptx_render] soffice를 못 찾음(설정 soffice_bin·PATH 다 없음) — pptx 슬라이드 렌더 기능 전부 건너뜀"
            "(이 프로세스 동안 이 경고는 1번만)",
            file=sys.stderr,
        )
    return None


def _convert_to_pdf(pptx_path, out_dir, timeout):
    """soffice --headless --convert-to pdf <pptx> --outdir <out_dir> → 변환된 pdf 경로, 실패·타임아웃이면 None.
    타임아웃이면 이 자식 프로세스만 종료(kill — 이름 단위 taskkill 금지, 고아 방지는 wait()로 회수까지 확인)."""
    binp = soffice_bin()
    if binp is None:
        return None
    # 변환마다 독립 프로필(engine-qa 10-08) — 이미 떠 있는 LibreOffice·다른 워커와 프로필 잠금·위임 없이 이 프로세스가 직접 변환
    profile = (Path(out_dir) / "lo_profile").resolve().as_uri()
    proc = subprocess.Popen(
        [binp, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(pptx_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return None
    if proc.returncode != 0:
        return None
    out = Path(out_dir) / (Path(pptx_path).stem + ".pdf")
    return out if out.exists() else None


def target_slides(doc_path):
    """AD20 후속(10-11) — 이 문서에서 **실제로** 쪽 VLM이 호출될 슬라이드 번호 집합(candidate_slides를
    PARSE_PPTX_RENDER_MAX 상한·soffice 유무까지 적용해 거른 것) — pptx_slide_vlm()이 렌더할 목록을 고르는
    바로 그 계산이자, `figures.py`가 '이 슬라이드는 쪽 VLM이 이미 전체를 다루니 삽입 그림을 또 기록하지
    않는다'는 중복 방지 판단에 쓰는 한 곳(한 계산을 두 곳이 같이 봄 — 따로 추정 안 함). pptx 아님·
    후보 0건·soffice 없음이면 빈 집합(그 경우 쪽 VLM도 안 돌아 figures()가 평소처럼 그림을 기록해야 함).
    독립 검토 반영(10-11, AD31/AD20 BLOCK) — soffice가 PATH에 있다고 변환이 꼭 성공하는 건 아니다(타임아웃·
    0이 아닌 종료 코드·깨진 파일). pptx_slide_vlm()이 이 문서에 대해 이미(이 프로세스에서) 변환을 시도해
    실패를 기록해 두었으면(_conversion_ok) 예측 대신 그 실제 결과로 빈 집합을 돌려준다 — 변환이 실패하면
    쪽 VLM도 비어서([]) 그 슬라이드의 삽입 그림을 figures()가 건너뛰면 안 되기 때문(원래 버그: 예측만 보고
    실제 변환 결과를 몰랐음)."""
    from pipeline.shared.postprocess import (
        active_features,
    )  # 재검토(10-11): PARSE_POST에 vlm_page가 없으면 쪽 VLM이 안 도니 그림도 건너뛰면 안 됨(page_targets와 같은 규칙)

    if "vlm_page" not in active_features():
        return set()
    p = Path(doc_path)
    if p.suffix.lower() != ".pptx" or soffice_bin() is None:
        return set()
    cands = candidate_slides(p)
    if not cands:
        return set()
    if _conversion_ok.get(str(p.resolve())) is False:
        return set()
    cap = _cap("PARSE_PPTX_RENDER_MAX", 10)
    return set(sorted(cands)[:cap])


def render_office_pages(doc_path, page_nums, timeout=None):
    """F12 — 임의 오피스 문서(pptx·docx·xlsx 등, 확장자 제약 없음)를 soffice로 PDF 변환해 쪽 번호만 렌더 →
    {쪽 번호: PNG bytes}(soffice 변환 1번만, 재사용) — render_slides()의 몸통(pptx 제약만 뺌). F12 겹침 묶음
    크롭(figures.py _docx_overlay_records 등)이 이 함수를 직접 쓴다 — docx·xlsx는 원본 좌표계(XML anchor)와
    soffice 렌더 쪽이 1:1 대응한다는 보장이 없어(레이아웃 엔진이 다름) 호출부가 쪽 1만 가정하는 등 범위를
    좁혀 쓴다(모듈 docstring 참고). soffice 없음·쪽 번호 없음이면 빈 묶음(조용히 건너뜀)."""
    p = Path(doc_path)
    if not page_nums or soffice_bin() is None:
        return {}
    timeout = timeout or _cap("PARSE_PPTX_CONVERT_SEC", 60)
    tmp_root = raw_root() / "tmp" / "pptx_render"
    tmp_root.mkdir(parents=True, exist_ok=True)
    out = {}
    with tempfile.TemporaryDirectory(dir=tmp_root) as td:
        pdf = _convert_to_pdf(p, Path(td), timeout)
        if pdf is None:
            return {}
        import fitz

        doc = fitz.open(pdf)
        try:
            for i in page_nums:
                if 1 <= i <= len(doc):
                    out[i] = doc[i - 1].get_pixmap(dpi=DPI).tobytes("png")
        finally:
            doc.close()
    return out


def render_slides(doc_path, slide_nums, timeout=None):
    """F7 — 임의 슬라이드 번호 목록 → {슬라이드 번호: PNG bytes}(soffice 변환 1번만, 재사용). target_slides()와
    달리 '쪽 VLM 후보(candidate_slides)'인지 안 가린다 — figures.py가 그림(picture shape)이 전혀 없는 도형
    슬라이드(qc_workflow.pptx 2쪽류)를 첨부용 그림 1장으로 렌더할 때 이 함수를 그대로 쓴다. SOFFICE_BIN·PATH에
    soffice 없음·변환 실패·pptx 아님·슬라이드 번호 없음이면 빈 묶음(조용히 건너뜀 — 이전 동작과 바이트 동일,
    stderr 진단은 soffice_bin()이 None일 때만 호출부가 남긴다). render_office_pages(F12)의 pptx 전용 가드만
    더한 얇은 래퍼(몸통은 공유 — 동작 바이트 동일)."""
    p = Path(doc_path)
    if p.suffix.lower() != ".pptx" or not slide_nums or soffice_bin() is None:
        return {}
    return render_office_pages(p, slide_nums, timeout)


def _is_table_like(pg):
    """독립 검토 반영(10-13) — shape_render_pages()가 "그려진 것 있음 + 이미지 없음"만 보면 표 테두리·밑줄만
    있는 쪽(축 정렬 선·윤곽선 사각형만, 채움 없음)도 후보로 잡힌다. 쪽에 pymupdf가 실제로 표를 찾으면(내장
    find_tables() 재사용) 바로 표로 본다. 그 외엔 간단한 규칙 하나: **채워진 도형(fill 있음)·곡선·대각선
    (연결선)이 하나도 없으면** 표/밑줄로 본다 — 우리 도형 도식(상자는 solidFill, 화살표머리는 작은 채운
    다각형, 연결선은 대각선이거나 적어도 화살표로 채워짐)은 이 중 하나를 반드시 가진다. ponytail: 표 셀이
    드물게 배경색(채움)을 쓰면 놓칠 수 있음(미탐 쪽으로 보수적) — vector.vector_regions의 더 정교한 신호로
    승급할 자리를 비워 둔다."""
    try:
        if pg.find_tables().tables:
            return True
    except Exception:  # find_tables 실패 1건이 쪽 판정을 막지 않게(아래 규칙으로 계속)
        pass
    for d in pg.get_drawings():
        if d.get("fill") is not None:
            return False
        for item in d.get("items", []):
            if item[0] == "c":  # 곡선
                return False
            if item[0] == "l" and abs(item[1].x - item[2].x) > 1.5 and abs(item[1].y - item[2].y) > 1.5:
                return False  # 대각선(연결선 방향 — 표 밑줄은 항상 축 정렬)
    return True


def shape_render_pages(doc_path, timeout=None):
    """AD14 — docx·xlsx의 도형 도식(텍스트 상자·연결선·SmartArt, 삽입 이미지 없음) → {쪽 번호(soffice가 만든
    PDF 쪽, 1부터): PNG bytes}. docx·xlsx 아님·shape_detect 문턱 미달(soffice를
    아예 안 부름)·soffice 없음·변환 실패면 빈 묶음(조용히 건너뜀, soffice 없을 때만 stderr 진단 1줄).
    문서 전체를 soffice로 한 번만 PDF 변환(render_slides와 같은 _convert_to_pdf 재사용) 후 쪽마다 '벡터로
    그려진 것이 있고 래스터 이미지가 없음'(get_drawings() 있음 + get_images() 없음 — 백로그가 제시한 규칙,
    vector.py의 차트 전용 문턱 대신 이 cheap 쪽)인데 표 테두리·밑줄만 있는 쪽은 아님(_is_table_like) 후보로
    돌려준다. PARSE_PPTX_RENDER_MAX(기본 10)로 쪽 수를 자름(렌더링은 문서당 soffice 변환 1번이라 싸지만
    VLM 호출은 쪽마다라 비용이 큼 — render_slides·pptx_slide_vlm과 같은 안전판 재사용, 새 env 없음)."""
    p = Path(doc_path)
    ext = p.suffix.lower()
    if ext not in (".docx", ".xlsx"):
        return {}
    has_shapes = shape_detect.docx_has_shapes(p) if ext == ".docx" else shape_detect.xlsx_has_shapes(p)
    if not has_shapes:
        return {}
    if soffice_bin() is None:
        print(f"[pptx_render] SOFFICE_BIN·PATH에 soffice 없음 — 도형 도식 렌더 건너뜀: {p.name}", file=sys.stderr)
        return {}
    timeout = timeout or _cap("PARSE_PPTX_CONVERT_SEC", 60)
    tmp_root = raw_root() / "tmp" / "pptx_render"
    tmp_root.mkdir(parents=True, exist_ok=True)
    out = {}
    with tempfile.TemporaryDirectory(dir=tmp_root) as td:
        pdf = _convert_to_pdf(p, Path(td), timeout)
        if pdf is None:
            return {}
        import fitz

        doc = fitz.open(pdf)
        try:
            cap = _cap("PARSE_PPTX_RENDER_MAX", 10)
            for i, pg in enumerate(doc, 1):
                if len(out) >= cap:
                    break
                if pg.get_drawings() and not pg.get_images(full=True) and not _is_table_like(pg):
                    out[i] = pg.get_pixmap(dpi=DPI).tobytes("png")
        finally:
            doc.close()
    return out


def pptx_slide_vlm(doc_path):
    """후보 슬라이드(candidate_slides)만 렌더해 쪽 VLM — [(슬라이드 번호, 글, provenance{..., "reason"})].
    pptx 아님·후보 0건·soffice 없음·변환 실패면 []( 바이트 영향 0,
    soffice 없을 때만 stderr 진단 1줄)."""
    p = Path(doc_path)
    if p.suffix.lower() != ".pptx":
        return []
    cands = candidate_slides(p)
    if not cands:
        return []
    if soffice_bin() is None:  # 독립 검토(10-13) — 경고는 soffice_bin() 한 곳에서(1회), 여기서 또 찍지 않음(중복 제거)
        return []
    idxs = sorted(target_slides(doc_path))  # AD20 후속 — figures.py 중복 방지와 같은 집합(한 곳에서 계산)
    timeout = _cap("PARSE_PPTX_CONVERT_SEC", 60)
    src_sha = sha(p.read_bytes())
    tmp_root = raw_root() / "tmp" / "pptx_render"
    tmp_root.mkdir(parents=True, exist_ok=True)
    out = []
    with tempfile.TemporaryDirectory(dir=tmp_root) as td:
        pdf = _convert_to_pdf(p, Path(td), timeout)
        if pdf is None:
            _conversion_ok[str(p.resolve())] = False  # 독립 검토 반영 — target_slides()가 이 결과를 보고 빈 집합으로
            return []
        _conversion_ok[str(p.resolve())] = True
        import fitz

        doc = fitz.open(pdf)
        try:
            for i in idxs:
                if i < 1 or i > len(doc):
                    continue
                img = doc[i - 1].get_pixmap(dpi=DPI).tobytes("png")
                det = {"source_sha256": src_sha, "page": i, "rotation_deg": 0, "is_pdf": True}
                text, prov = vlm_page(img, det)
                out.append((i, text, {**prov, "reason": cands[i]}))
        finally:
            doc.close()
    return out
