"""OpenViking 공용 REST 토막(urllib만 — openviking_sdk는 이미지에 없음, 10-07 서버 이미지 경계).
cli/ov_export.py(읽기 — L0·L1 요약 내려받기)와 load/ov_ingest.py(쓰기 — OV1, 대표 결과 올리기)가 같이 쓴다.
모듈 경계(cli/·load/ 서로 import 금지, check_modules.py ①)상 공용 토막은 common/에만 — list_docs를 두 곳에
따로 베끼면 이름 대조 규칙이 갈릴 위험이 있어 여기 한 곳으로.
"""

import json
import urllib.parse
import urllib.request

from common.config import settings as C
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)


def _ov_headers(extra=None):
    """trusted 모드 인증 헤더 — OV_API_KEY·OV_ACCOUNT(기본 default)·OV_USER(기본 default)."""
    h = {}
    key = C.reveal(pc.cfg().connections.openviking.api_key)  # S7c — 설정 객체(SecretStr)
    if key:
        h["X-API-Key"] = key
    h["X-OpenViking-Account"] = pc.cfg().connections.openviking.account
    h["X-OpenViking-User"] = pc.cfg().connections.openviking.user
    if extra:
        h.update(extra)
    return h


def call(base, path, timeout=120, **params):
    """GET 호출 → {"result": ...}의 result(또는 /download면 원본 바이트)."""
    req = urllib.request.Request(f"{base}{path}?{urllib.parse.urlencode(params)}", headers=_ov_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return body if path.endswith("/download") else json.loads(body)["result"]


def list_docs(base, root):
    """OV 루트(viking://resources/<root>) 바로 아래 문서 폴더 {이름: uri}."""
    return {d["uri"].rstrip("/").rsplit("/", 1)[-1]: d["uri"] for d in call(base, "/api/v1/fs/ls", uri=root.rstrip("/")) if d["isDir"]}
