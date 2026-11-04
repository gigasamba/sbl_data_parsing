"""오피스 문서를 LibreOffice(soffice) headless로 PDF 변환해 쪽 이미지로 렌더한다.
- pptx: pptx_edges.candidate_slides()가 고른 슬라이드(연결선 없는 도형 배치·SmartArt)만 렌더해 쪽 VLM(shared/vlmcall.vlm_page,
  같은 캐시·상한)으로 옮긴다. target_slides()가 그 슬라이드 집합을 한 곳에서 정하고, figure_extract는 그 슬라이드의 삽입 그림을
  건너뛴다(그림 VLM·쪽 VLM에 같은 내용이 두 번 기록되지 않게 — 쪽 VLM 우선).
- docx·xlsx 도형 도식(텍스트 상자·연결선·SmartArt, 삽입 이미지 없음): shape_detect 문턱을 넘으면 문서 전체를 한 번 변환해
  '벡터 그림 있음 + 래스터 이미지 없음'인 쪽만 돌려준다(shape_render_pages) — figure_extract가 그림 레코드로 바꾼다.

soffice는 설정 soffice_bin → PATH 순으로 찾고, 없으면 조용히 건너뛴다(프로세스당 stderr 경고 1번).
PARSE_PPTX_RENDER_MAX(기본 10) — 문서당 렌더·VLM 호출할 쪽 상한(변환은 문서당 1번이지만 VLM은 쪽마다라 비용이 큼).
PARSE_PPTX_CONVERT_SEC(기본 60초) — 변환 시간 상한, 넘으면 그 자식 프로세스만 끝내고 빈 결과.
임시 PDF는 raw_root()/tmp/pptx_render/ 아래 TemporaryDirectory(끝나면 지움)."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pipeline import config as pc
from pipeline.shared.post_config import raw_root
from pipeline.shared.vlmcall import dpi, sha, vlm_page
from pipeline.transform.figures import shape_detect
from pipeline.transform.figures.pptx_edges import candidate_slides

# 이 프로세스에서 실제 soffice 변환 성공/실패(경로 키) — target_slides()가 예측 대신 실제 결과를 따르게.
# ponytail: 경로 키만 — 같은 경로가 다른 내용으로 재사용되면 (경로, sha256) 키로 올림
_conversion_ok: dict = {}

_soffice_warned = [False]  # soffice를 못 찾았다는 stderr 경고는 프로세스당 1번(soffice_bin 한 곳에서)


def soffice_bin():
    """설정 soffice_bin(파일로 존재해야 유효) → PATH의 soffice·soffice.exe — 다 없으면 None, 프로세스에서 처음 한 번만
    stderr 경고. 설치 경로는 추측하지 않는다(PATH에 없으면 settings.yaml soffice_bin을 채운다)."""
    v = pc.cfg().paths.soffice_bin
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
    # 변환마다 독립 프로필 — 이미 떠 있는 LibreOffice·다른 워커와 프로필 잠금·위임 없이 이 프로세스가 직접 변환
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
    """이 문서에서 실제로 쪽 VLM이 호출될 슬라이드 번호 집합 — candidate_slides를 PARSE_PPTX_RENDER_MAX·soffice 유무·
    PARSE_POST(vlm_page)로 거른 것. pptx_slide_vlm()의 렌더 목록이자 figure_extract의 삽입 그림 중복 방지 기준(한 계산).
    이 프로세스에서 이미 변환이 실패했으면(_conversion_ok) 빈 집합 — 쪽 VLM이 비었는데 그림까지 건너뛰면 내용을 잃는다."""
    from pipeline.shared.post_config import active_features

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
    cap = int(pc.by_env("PARSE_PPTX_RENDER_MAX", 10))
    return set(sorted(cands)[:cap])


def render_office_pages(doc_path, page_nums, timeout=None):
    """임의 오피스 문서(pptx·docx·xlsx 등)를 soffice로 PDF 변환해 쪽 번호만 렌더 → {쪽 번호: PNG bytes}(변환 1번).
    render_slides()의 몸통. 겹침 묶음 크롭(figure_extract._docx_overlay_records 등)이 이 함수를 직접 쓴다 — docx·xlsx는 원본 좌표계(XML anchor)와
    soffice 렌더 쪽이 1:1 대응한다는 보장이 없어(레이아웃 엔진이 다름) 호출부가 쪽 1만 가정하는 등 범위를
    좁혀 쓴다. soffice 없음·쪽 번호 없음이면 빈 묶음(조용히 건너뜀)."""
    p = Path(doc_path)
    if not page_nums or soffice_bin() is None:
        return {}
    timeout = timeout or int(pc.by_env("PARSE_PPTX_CONVERT_SEC", 60))
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
                    out[i] = doc[i - 1].get_pixmap(dpi=dpi()).tobytes("png")
        finally:
            doc.close()
    return out


def render_slides(doc_path, slide_nums, timeout=None):
    """임의 슬라이드 번호 목록 → {슬라이드 번호: PNG bytes}(변환 1번) — render_office_pages에 pptx 가드만 더한 것.
    target_slides()와 달리 쪽 VLM 후보인지 안 가린다 — figure_extract가 그림 없는 도형 슬라이드를 그림 1장으로 렌더할 때 쓴다.
    soffice 없음·변환 실패·pptx 아님·슬라이드 번호 없음이면 빈 묶음."""
    p = Path(doc_path)
    if p.suffix.lower() != ".pptx" or not slide_nums or soffice_bin() is None:
        return {}
    return render_office_pages(p, slide_nums, timeout)


def _is_table_like(pg):
    """shape_render_pages()가 "그려진 것 있음 + 이미지 없음"만 보면 표 테두리·밑줄만
    있는 쪽(축 정렬 선·윤곽선 사각형만, 채움 없음)도 후보로 잡힌다. 쪽에 pymupdf가 실제로 표를 찾으면(내장
    find_tables() 재사용) 바로 표로 본다. 그 외엔 간단한 규칙 하나: **채워진 도형(fill 있음)·곡선·대각선
    (연결선)이 하나도 없으면** 표/밑줄로 본다 — 우리 도형 도식(상자는 solidFill, 화살표머리는 작은 채운
    다각형, 연결선은 대각선이거나 적어도 화살표로 채워짐)은 이 중 하나를 반드시 가진다. ponytail: 표 셀이
    드물게 배경색(채움)을 쓰면 놓칠 수 있음(미탐 쪽으로 보수적) — 필요하면 vector_regions의 신호로 올린다."""
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
    """docx·xlsx의 도형 도식(텍스트 상자·연결선·SmartArt, 삽입 이미지 없음) → {쪽 번호(soffice가 만든
    PDF 쪽, 1부터): PNG bytes}. docx·xlsx 아님·shape_detect 문턱 미달(soffice를
    아예 안 부름)·soffice 없음·변환 실패면 빈 묶음(조용히 건너뜀, soffice 없을 때만 stderr 진단 1줄).
    문서 전체를 soffice로 한 번만 PDF 변환(render_slides와 같은 _convert_to_pdf 재사용) 후 쪽마다 '벡터로
    그려진 것이 있고 래스터 이미지가 없음'(get_drawings() 있음 + get_images() 없음)인데 표 테두리·밑줄만 있는 쪽은 아님(_is_table_like) 후보로
    돌려준다. PARSE_PPTX_RENDER_MAX(기본 10)로 쪽 수를 자른다(VLM 호출은 쪽마다라 비용이 큼)."""
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
    timeout = timeout or int(pc.by_env("PARSE_PPTX_CONVERT_SEC", 60))
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
            cap = int(pc.by_env("PARSE_PPTX_RENDER_MAX", 10))
            for i, pg in enumerate(doc, 1):
                if len(out) >= cap:
                    break
                if pg.get_drawings() and not pg.get_images(full=True) and not _is_table_like(pg):
                    out[i] = pg.get_pixmap(dpi=dpi()).tobytes("png")
        finally:
            doc.close()
    return out


def pptx_slide_vlm(doc_path):
    """후보 슬라이드(candidate_slides)만 렌더해 쪽 VLM — [(슬라이드 번호, 글, provenance{..., "reason"})].
    pptx 아님·후보 0건·soffice 없음·변환 실패면 []."""
    p = Path(doc_path)
    if p.suffix.lower() != ".pptx":
        return []
    cands = candidate_slides(p)
    if not cands:
        return []
    if soffice_bin() is None:  # 경고는 soffice_bin()이 1번만
        return []
    idxs = sorted(target_slides(doc_path))  # figure_extract 중복 방지와 같은 집합
    timeout = int(pc.by_env("PARSE_PPTX_CONVERT_SEC", 60))
    src_sha = sha(p.read_bytes())
    tmp_root = raw_root() / "tmp" / "pptx_render"
    tmp_root.mkdir(parents=True, exist_ok=True)
    out = []
    with tempfile.TemporaryDirectory(dir=tmp_root) as td:
        pdf = _convert_to_pdf(p, Path(td), timeout)
        if pdf is None:
            _conversion_ok[str(p.resolve())] = False  # target_slides()가 이 결과를 보고 빈 집합으로
            return []
        _conversion_ok[str(p.resolve())] = True
        import fitz

        doc = fitz.open(pdf)
        try:
            for i in idxs:
                if i < 1 or i > len(doc):
                    continue
                img = doc[i - 1].get_pixmap(dpi=dpi()).tobytes("png")
                det = {"source_sha256": src_sha, "page": i, "rotation_deg": 0, "is_pdf": True}
                text, prov = vlm_page(img, det)
                out.append((i, text, {**prov, "reason": cands[i]}))
        finally:
            doc.close()
    return out
