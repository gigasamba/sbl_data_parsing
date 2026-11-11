# 서버 이미지 4개 — 빌드 컨텍스트 = 저장소 루트(.dockerignore 허용 목록). 저장소 루트에서:
#   docker build -f deploy/docker/Dockerfile --target <타깃> -t <이미지>:<버전> .   (보통 deploy/release/build_ship.sh)
#   pipeline-runtime → data-pipeline-runtime · mcp-runtime → mcp-server-runtime   코드 없음 — 코드 폴더를 /app에 붙여 띄움(개발 서버)
#   pipeline → data-pipeline · mcp → mcp-server                                   코드 포함(PC 시험·비상용 — 운영은 Dockerfile.bake)
# 이미지 안 자리: 코드 /app(PYTHONPATH) · 이미지 부품 /opt/sbl/{docker,assets}. 결과·홈·설정은 compose가 붙인다(VOLUME 없음).
# 비밀값·원본 문서·결과는 넣지 않는다. 바꿀 값은 settings.yaml — ENV에는 이미지 바탕·라이브러리 값만(image_env.txt에 적어 둠).
# pipeline 단계 heredoc은 BuildKit 문법 — Docker 23 미만은 BUILDKIT_SYNTAX 빌드 인자가 필요(build_ship.sh가 붙임).
# 폐쇄망: BASE(기반 이미지)·APT=0·deploy/docker/wheels/ 휠로 인터넷 없이.
ARG BASE=python:3.12-slim-bookworm

# 복사 원본 — 타깃마다 필요한 폴더만 COPY --from=src. /src/appdocker = /opt/sbl/docker 내용(entrypoint·반입 판정·자산 설치)
#   /src/opencode = opencode 실행 파일(/usr/local/bin으로 — /opt/sbl/assets에 두 벌 들지 않게 assets/ 밖으로 옮김)
FROM ${BASE} AS src
COPY . /src
# assets/(git 밖)가 없는 체크아웃에서도 COPY가 멈추지 않게 빈 폴더를 만든다
RUN mkdir -p /src/appdocker /src/assets/opencode && cp /src/deploy/docker/entrypoint.sh \
      /src/deploy/release/selftest_gate.sh /src/deploy/release/known_fail.txt /src/deploy/release/assets.py /src/appdocker/ \
    && mv /src/assets/opencode /src/opencode && chmod -R 755 /src/opencode

FROM ${BASE} AS base

# APT=1: 시스템 패키지를 apt로(인터넷·사내 미러 필요). 폐쇄망이면 이미 넣어 둔 기반 이미지를 BASE로 주고 APT=0.
#   libgl1·libglib2.0-0 = OpenCV(RapidOCR·PaddleOCR)가 불러오는 공유 라이브러리 — 없으면 import 단계에서 실패
ARG APT=1
RUN if [ "$APT" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 tzdata ca-certificates \
      && rm -rf /var/lib/apt/lists/*; fi
RUN useradd -u 10001 -m -s /bin/bash rag

# 휠: deploy/docker/wheels/에 미리 받아 두면 인터넷 없이(--no-index). 비어 있으면 PyPI(인터넷 되는 곳에서만).
#   ponytail: 휠 복사 층이 이미지에 남음 — 줄이려면 BuildKit `RUN --mount=type=bind,source=deploy/docker/wheels`
ARG PIP_OFFLINE=auto
COPY deploy/docker/wheels/ /tmp/wheels/
COPY deploy/docker/requirements-core.txt deploy/docker/requirements-image.txt /tmp/
RUN set -e; n=$(ls /tmp/wheels | grep -c '\.whl$' || true); \
    if [ "$PIP_OFFLINE" = "1" ] || { [ "$PIP_OFFLINE" = "auto" ] && [ "$n" -gt 0 ]; }; then echo "--no-index --find-links /tmp/wheels" > /tmp/pipopt; else : > /tmp/pipopt; fi; \
    pip install --no-cache-dir $(cat /tmp/pipopt) -r /tmp/requirements-core.txt

# 개발 도구(네 이미지 모두 — SSH 작업 공간 devbox·컨테이너 안 점검용, 앱은 부르지 않음). APT=0이면 tini·openssh-server가 BASE에 있어야 함.
#   pip 판은 requirements-dev.txt(DEPS_HASH에는 안 듦) + uv. opencode는 선택(내부망 모델만 — devbox/opencode.json).
RUN if [ "$APT" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        openssh-server openssh-client telnet git curl wget iputils-ping dnsutils netcat-openbsd net-tools procps lsof \
        vim nano zip unzip tree file ripgrep sqlite3 tini tmux sudo \
      && rm -rf /var/lib/apt/lists/*; fi \
    && mkdir -p /run/sshd && chmod 755 /run/sshd
ARG UV_VERSION=0.11.26
COPY requirements-dev.txt /tmp/
RUN pip install --no-cache-dir $(cat /tmp/pipopt) uv==${UV_VERSION} -r /tmp/requirements-dev.txt
COPY --from=src /src/opencode/ /usr/local/bin/
COPY deploy/docker/devbox/ /etc/devbox/
RUN sed -i 's/\r$//' /etc/devbox/* && chmod 755 /etc/devbox/dev_entry.sh && ln -s /etc/devbox/profile.sh /etc/profile.d/zz-devbox.sh
# Image root password (user exception): BuildKit secret `--secret id=root_pw,src=<file outside git>` — first line.
#   Not in the repo or `docker history`; the hash stays in /etc/shadow. Optional — servers give it at start instead: settings.yaml option.devbox.root_password → compose secret /run/secrets/root_pw (dev_entry.sh), which wins.
RUN --mount=type=secret,id=root_pw,required=false \
    if [ -s /run/secrets/root_pw ]; then head -n1 /run/secrets/root_pw | tr -d '\r' | sed 's/^/root:/' | chpasswd; fi
ENV OPENCODE_DISABLE_MODELS_FETCH=1 OPENCODE_DISABLE_AUTOUPDATE=1

# 파싱 엔진·OCR 의존성(무거움) — 코드 바뀌어도 다시 설치 안 되게 코드 복사 전에
FROM base AS parse-deps
RUN pip install --no-cache-dir $(cat /tmp/pipopt) -r /tmp/requirements-image.txt
# LibreOffice(pptx_render.py — 슬라이드 → PDF → 쪽 이미지): writer·impress·calc(WMF/EMF가 docx·xlsx에도 나옴) + 한글 글꼴
#   fonts-noto-cjk(없으면 한글이 네모로 렌더돼 VLM이 못 읽음). 파이프라인 이미지에만.
ARG APT=1
RUN if [ "$APT" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-core libreoffice-writer libreoffice-impress libreoffice-calc fonts-noto-cjk \
      && rm -rf /var/lib/apt/lists/*; fi

# ── 검색 MCP 실행 이미지(mcp-server-runtime — 코드 없음, op-06) ──
FROM base AS mcp-runtime
WORKDIR /app
# runtime_entry.sh가 코드 폴더·의존성 지문(deps_hash ↔ 코드 deploy/docker/DEPS_HASH)을 보고 코드의 entrypoint로 넘김.
#   코드가 든 타깃(mcp·pipeline)은 이 단계 + 코드 COPY라 바탕·의존성이 어긋나지 않는다.
COPY deploy/docker/runtime_entry.sh /opt/sbl/docker/runtime_entry.sh
RUN sed -i 's/\r$//' /opt/sbl/docker/runtime_entry.sh && chmod +x /opt/sbl/docker/runtime_entry.sh \
    && cat /tmp/requirements-core.txt /tmp/requirements-image.txt | tr -d '\r' | sha256sum | cut -c1-16 > /opt/sbl/docker/deps_hash
ENV TZ=Asia/Seoul LANG=C.UTF-8 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 DO_NOT_TRACK=1 SCARF_NO_ANALYTICS=true \
    RAG_MODULE=mcp
RUN env > /opt/sbl/docker/image_env.txt   # 이미지 ENV 기록 — entrypoint가 사용자 env와 가름(비밀 없음)
ARG APP_VERSION=
ARG VCS_REF=
RUN echo "mcp-server-runtime ${APP_VERSION:-?} ${VCS_REF:-?}" > /opt/sbl/docker/image_ref   # 실행 기록에 남길 이미지 판
LABEL org.opencontainers.image.version=$APP_VERSION org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.title=mcp-server-runtime
USER rag
# VOLUME 없음 — 결과는 /app/output(코드 폴더/output), root 홈은 /root — 무엇을 붙일지는 compose가 정한다
# dev_entry.sh: `devbox`면 SSH 작업 공간, 그 밖은 APP_ENTRY로 그대로. tini -s — --init 없이도 고아 프로세스를 거둠
ENV APP_ENTRY=/opt/sbl/docker/runtime_entry.sh
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/etc/devbox/dev_entry.sh"]
CMD ["help"]

# ── 검색 MCP(mcp-server) — mcp_server + common(+ 명령용 pipeline/cli.py) ──
FROM mcp-runtime AS mcp
USER root
WORKDIR /app
COPY --from=src /src/common /app/common
COPY --from=src /src/mcp_server /app/mcp_server
COPY --from=src /src/pipeline/__init__.py /src/pipeline/cli.py /src/pipeline/config.py /app/pipeline/
COPY --from=src /src/resources /app/resources
COPY --from=src /src/VERSION /app/VERSION
COPY --from=src /src/edw_chain.yaml /src/opencode.jsonc /app/
COPY --from=src /src/appdocker /opt/sbl/docker
COPY --from=src /src/tests/__init__.py /src/tests/runner.py /app/tests/
COPY --from=src /src/tests/server/__init__.py /app/tests/server/
COPY --from=src /src/tests/server/common /app/tests/server/common
COPY --from=src /src/tests/server/mcp /app/tests/server/mcp
RUN sed -i 's/\r$//' /opt/sbl/docker/entrypoint.sh && chmod +x /opt/sbl/docker/entrypoint.sh   # Windows 사본의 CRLF 줄 끝 제거
# 넘긴 APP_VERSION이 이미지 안 VERSION과 다르면 빌드를 멈춘다(태그와 버전 표기가 어긋나지 않게)
ARG APP_VERSION=
ARG VCS_REF=
RUN [ -z "$APP_VERSION" ] || [ "$APP_VERSION" = "$(tr -d ' \r\n' < /app/VERSION)" ] \
    || { echo "APP_VERSION($APP_VERSION) ≠ VERSION 파일" >&2; exit 1; }
LABEL org.opencontainers.image.version=$APP_VERSION org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.title=mcp-server
USER rag
ENV APP_ENTRY=/opt/sbl/docker/entrypoint.sh
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/etc/devbox/dev_entry.sh"]
CMD ["help"]

# ── 파이프라인 실행 이미지(data-pipeline-runtime — 코드 없음, op-06) — RapidOCR 모델·LibreOffice는 이 단계에 ──
FROM parse-deps AS pipeline-runtime
WORKDIR /app
COPY --from=src /src/assets/ /opt/sbl/assets/
RUN python - <<'EOF'
import glob, os, shutil, rapidocr
dst = os.path.join(os.path.dirname(rapidocr.__file__), "models")
os.makedirs(dst, exist_ok=True)
fs = glob.glob("/opt/sbl/assets/rapidocr/*.onnx")
for f in fs:
    shutil.copy(f, dst)
print(f"rapidocr 모델 {len(fs)}개 복사" + ("" if fs else " — assets/rapidocr 없음: 첫 실행에 모델을 받음(인터넷 필요 — 폐쇄망은 assets 반입)"))
os.system(f"chown -R rag {dst}")                      # 실행 사용자(rag)가 모델을 받아 둘 수 있게(없으면 PermissionError로 회전 보정 실패)
EOF
COPY deploy/docker/runtime_entry.sh /opt/sbl/docker/runtime_entry.sh
RUN sed -i 's/\r$//' /opt/sbl/docker/runtime_entry.sh && chmod +x /opt/sbl/docker/runtime_entry.sh \
    && cat /tmp/requirements-core.txt /tmp/requirements-image.txt | tr -d '\r' | sha256sum | cut -c1-16 > /opt/sbl/docker/deps_hash
# 시간대는 새벽 마감 계산에 쓰임(UTC면 9시간 어긋남 — 바꾸려면 settings.yaml ops.runtime.lib_env).
# HOME=/tmp: fontconfig 캐시 등이 $HOME을 봄 — 읽기 전용 루트로 떠도 쓸 수 있게(SSH 작업 공간은 dev_entry.sh가 passwd 홈으로 바꿈).
ENV TZ=Asia/Seoul LANG=C.UTF-8 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 DO_NOT_TRACK=1 SCARF_NO_ANALYTICS=true \
    RAG_MODULE=pipeline HOME=/tmp
RUN env > /opt/sbl/docker/image_env.txt   # 이미지 ENV 기록 — entrypoint가 사용자 env와 가름(비밀 없음)
ARG APP_VERSION=
ARG VCS_REF=
RUN echo "data-pipeline-runtime ${APP_VERSION:-?} ${VCS_REF:-?}" > /opt/sbl/docker/image_ref   # 실행 기록에 남길 이미지 판
LABEL org.opencontainers.image.version=$APP_VERSION org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.title=data-pipeline-runtime
USER rag
# VOLUME 없음 — 결과는 /app/output(코드 폴더/output), root 홈은 /root — 무엇을 붙일지는 compose가 정한다
# dev_entry.sh: `devbox`면 SSH 작업 공간, 그 밖은 APP_ENTRY로 그대로. tini -s — --init 없이도 고아 프로세스를 거둠
ENV APP_ENTRY=/opt/sbl/docker/runtime_entry.sh
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/etc/devbox/dev_entry.sh"]
CMD ["help"]

# ── 파이프라인(data-pipeline) — pipeline 전체(파싱·구조화·적재·게시) + common ──
FROM pipeline-runtime AS pipeline
USER root
WORKDIR /app
COPY --from=src /src/common /app/common
COPY --from=src /src/pipeline /app/pipeline
COPY --from=src /src/mcp_server/__init__.py /src/mcp_server/config.py /app/mcp_server/
COPY --from=src /src/resources /app/resources
COPY --from=src /src/VERSION /app/VERSION
COPY --from=src /src/edw_chain.yaml /src/opencode.jsonc /app/
COPY --from=src /src/appdocker /opt/sbl/docker
COPY --from=src /src/tests/__init__.py /src/tests/runner.py /app/tests/
COPY --from=src /src/tests/server/__init__.py /app/tests/server/
COPY --from=src /src/tests/server/common /app/tests/server/common
COPY --from=src /src/tests/server/pipeline /app/tests/server/pipeline
RUN sed -i 's/\r$//' /opt/sbl/docker/entrypoint.sh && chmod +x /opt/sbl/docker/entrypoint.sh   # Windows 사본의 CRLF 줄 끝 제거
# 넘긴 APP_VERSION이 이미지 안 VERSION과 다르면 빌드를 멈춘다(태그와 버전 표기가 어긋나지 않게)
ARG APP_VERSION=
ARG VCS_REF=
RUN [ -z "$APP_VERSION" ] || [ "$APP_VERSION" = "$(tr -d ' \r\n' < /app/VERSION)" ] \
    || { echo "APP_VERSION($APP_VERSION) ≠ VERSION 파일" >&2; exit 1; }
LABEL org.opencontainers.image.version=$APP_VERSION org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.title=data-pipeline
USER rag
ENV APP_ENTRY=/opt/sbl/docker/entrypoint.sh
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/etc/devbox/dev_entry.sh"]
CMD ["help"]
