# 문서 파이프라인 이미지 (저장소 루트를 빌드 컨텍스트로, .dockerignore 허용 목록 — 구조 개편 v4 단계5, 10-13.
# 옛 dev/ 빌드 컨텍스트 때는 agent_platform이 dev/ 밖이라 --build-context platform=... 이 필요했으나,
# deploy/agent_platform이 이제 같은 컨텍스트 안이라 그 단계·인자가 없어짐). 모듈별(docs/common/modules.md) —
# 이미지에는 자기 모듈 폴더 + common/ 만 들어감.
# I3(10-26, V2-R1) — sbl_mcp 저장소 배치(`deploy/` 단 없음 — 저장소 루트 = 이미지 /app/deploy 내용 + docker/)에 맞춰
#   COPY 원본 경로에서 `deploy/`를 뺐다. 이미지 안 경로(/app/deploy/<폴더>·/app/docker)는 그대로.
#   assets/(rapidocr 모델, git 밖)는 parse 타깃만 쓰며 저장소 루트에 둔다.
# I5(10-26, D-013) — agent_platform/ 삭제(사용자 결정)로 세 타깃의 agent_platform COPY를 뺐다. 그래서 이미지 안
#   LLM·VLM·임베딩 호출은 I6(10-26)부터 common/ai/adk.py·llm.py의 임시 대체 구현으로 env 설정(LLM_·VLM_·
#   EMBED_ + _BASE_URL·_MODEL·_API_KEY, OpenAI 호환) 모델을 부른다(TODO 주석은 그대로). 정식 자리는 리팩토링 때 정한다(D-013).
#   code_fp a·p1·r·s가 바뀌는 새 이미지 판이라 서버 반입은 검토 등급 A 뒤 사용자가 정한다.
# S2(10-26, refactor_plan 4-1·D-011) — 코드가 읽는 데이터(지시서·채점 기준·보고서 틀·엔진 구성·원천 표·어휘·용어집)가
#   패키지 폴더에서 저장소 루트 resources/로 옮겨, 세 타깃 모두 resources/를 폴더째 /app/deploy/resources로 COPY한다
#   (코드는 paths.RES_ROOT = /app/deploy/resources로 찾음 — 앱별로 나누지 않음: 작고, 지시서 시험을 모든 이미지 selftest가 씀).
# S3(10-26, refactor_plan 9-1·D-014) — 공용 코드가 common_tools/에서 common/{core,ai,store,check}로 옮겨, 세 타깃 모두
#   common/을 /app/deploy/common으로 COPY한다. 단계 3 밖 파일(cli/·evaluation/·옛 options.conf·prompts/triple_extract)은 S4~S7까지
#   common_tools/에 남아 그 COPY도 그대로 둔다. ENV PYTHONPATH(/app/deploy)는 그대로 — import 기준이 저장소 루트와 같음.
# S4(10-26, refactor_plan 9-1) — data_etl/ → pipeline/(+ 단계 4 도구 common_tools/cli·evaluation → pipeline/). parse·structure는
#   pipeline/을 폴더째 /app/deploy/pipeline으로, retrieval은 entrypoint의 selftest·smoke·show-stack·set-stack이
#   부르는 pipeline/cli.py(+ __init__.py)만 넣는다(코디네이터 답 Q1 a — cli.py는 pipeline 단계 코드를 함수 안에서만 import ·
#   S5(T-15)부터 ask·test-stack은 mcp_server/cli/ask.py). 이미지 합침은 S6.
# S6a(10-26, refactor_plan 9-1) — common_tools/가 없어져 세 타깃 모두 그 COPY를 뺀다(남은 파일: options.conf·.env*.example → common/config/ — S7e2에 지움,
#   assets.py → docker/, 평가 도구 stack_matrix·model_matrix·triple_extract → validation/e2e/ — PC 전용이라 이미지에 넣지 않음).
# S6b(10-27, D-020·T-11) — 저장소 배치가 deploy/{docker,release,host}로 바뀌어 빌드 원본이 deploy/docker/(Dockerfile·requirements·
#   wheels·entrypoint.sh)와 deploy/release/(selftest_gate.sh·known_fail.txt·assets.py)로 나뉘었다. 이미지 안 경로는 그대로 —
#   /app/deploy/<폴더>(PYTHONPATH=/app/deploy)·/app/docker(= 이미지 안에서 쓰는 entrypoint.sh·selftest_gate.sh·known_fail.txt·assets.py만,
#   compose·systemd·호스트 스크립트는 deploy/host/에 두고 이미지에 넣지 않음).
#   **파이프라인 이미지를 하나로 합쳤다**(사용자 10-26 D-020) — 옛 parse(파싱 엔진·LibreOffice·OCR 자산)+structure(구조화·적재)를
#   타깃 pipeline 하나로, 검색 MCP는 타깃 mcp. 서버 이미지 2개(이름 — 사용자 10-27):
#   파이프라인(data-pipeline)  --target pipeline   docker build -f deploy/docker/Dockerfile --target pipeline  -t data-pipeline:<버전> .   ← 수집 서버(파싱·구조화·적재·게시, 엔진+LibreOffice+OCR 모델)
#   검색 MCP(mcp-server)       --target mcp        docker build -f deploy/docker/Dockerfile --target mcp       -t mcp-server:<버전> .     ← 수집 서버 상주(search만, 옛 data-retrieval)
#   --target은 항상 명시(pipeline·mcp 중 하나 — 옛 parse·structure·retrieval 타깃은 없음). (모두 저장소 루트에서 실행 — 빌드 컨텍스트가 `.`)
# 아래 pipeline 단계의 `RUN python - <<'EOF'`(heredoc)는 BuildKit dockerfile 1.4+ 문법 — Docker 23 미만(예: 20.10)은
#   DOCKER_BUILDKIT=1 + `--build-arg BUILDKIT_SYNTAX=docker/dockerfile:1.7`이 있어야 파일을 읽는다(타깃과 무관 —
#   파일 전체를 먼저 읽음, 이 인자는 docker/dockerfile 이미지를 받으므로 인터넷 필요). deploy/release/build_ship.sh가 자동으로 붙인다.
#   (10-16 3분할 이름 동결 data-parsing·data-structure·data-retrieval과 옛 core·all 타깃 폐지 이력은 git log·docs/history/release_history.md)
# 원칙: 비밀값·원본 문서·결과는 이미지에 넣지 않는다(실행 시 설정 파일 마운트·볼륨) · 바꿀 값은 모두 settings.yaml(settings.sample.yaml — S7e1·S7e2,
#   옛 --env-file pipeline.env 대신). S7e2(VS7e1 B-2, 사용자 10-28) — 설정 칸이 있는 값(PIPE_EMBED·PIPE_PROCS·DOC_DIR·DOC_DIR_PREPARED·SOFFICE_BIN)은
#   이미지 ENV로 굽지 않고 이미지 안 설정 모델 기본값으로(settings.yaml이 늘 이김 — 옛 ENV는 settings.yaml이 못 덮었음). ENV에는 이미지 바탕·
#   라이브러리 값만 남기고, 그 값을 /app/docker/image_env.txt에 적어 entrypoint가 settings.yaml ops.runtime.lib_env로 덮을 수 있게 한다.
# 폐쇄망: 기반 이미지(BASE)·시스템 패키지·휠을 미리 준비 — docs/specs/docker-collect.md 「빌드」.
# requirements 분할은 안 함(10-16 코디네이터 결정) — 두 이미지가 같은 base 층(requirements-core.txt)을 공유해 캐시로 한 번만 설치된다.
ARG BASE=python:3.12-slim-bookworm

# 소스(복사 원본, .dockerignore 허용 목록이라 코드 폴더 3개 + resources/ + deploy/{docker,release} + assets/ + requirements-dev.txt 뿐 — 이미지마다 필요한 폴더만 골라 COPY --from=src)
# /src/appdocker = 이미지 /app/docker 내용(이미지 안에서 쓰는 것만 — entrypoint·반입 판정·자산 설치, S6b)
# /src/opencode = assets/opencode/(opencode 실행 파일 — base가 /usr/local/bin에 넣음). /app/assets에 두 벌 들지 않게 assets/ 밖으로 옮긴다.
FROM ${BASE} AS src
COPY . /src
# assets/(git 밖 반입 자산)가 없는 체크아웃에서도 COPY가 멈추지 않게 빈 폴더를 만든다(없으면 build_ship.sh가 ALLOW_NO_ASSETS=1을 요구 — S6b).
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
#   ponytail: 휠 복사 층이 이미지에 남음(예전과 같음) — 줄이려면 BuildKit `RUN --mount=type=bind,source=deploy/docker/wheels`
ARG PIP_OFFLINE=auto
COPY deploy/docker/wheels/ /tmp/wheels/
COPY deploy/docker/requirements-core.txt deploy/docker/requirements-image.txt /tmp/
RUN set -e; n=$(ls /tmp/wheels | grep -c '\.whl$' || true); \
    if [ "$PIP_OFFLINE" = "1" ] || { [ "$PIP_OFFLINE" = "auto" ] && [ "$n" -gt 0 ]; }; then echo "--no-index --find-links /tmp/wheels" > /tmp/pipopt; else : > /tmp/pipopt; fi; \
    pip install --no-cache-dir $(cat /tmp/pipopt) -r /tmp/requirements-core.txt

# 개발 도구(네 이미지 모두 — 개발 서버 SSH 작업 공간 `devbox`와 컨테이너 안 점검용). 앱은 이 도구를 부르지 않는다.
#   APT=0(사내 기반 이미지)이면 아래 패키지(특히 tini·openssh-server)가 BASE에 이미 있어야 한다 — ENTRYPOINT가 tini를 부름.
#   pip 판은 requirements-dev.txt(PC 개발 도구와 같은 파일 — 의존성 지문 DEPS_HASH에는 안 듦) + uv. 오프라인(휠) 빌드면 wheels/에 이 휠도 둔다.
#   opencode(선택 — assets/opencode/opencode, 없으면 빼고 빌드): 내부망 모델만(외부 모델 목록 받기·자동 업데이트 끔 — devbox/opencode.json).
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
#   Not in the repo or `docker history`; the hash stays in /etc/shadow. A non-empty <SBL_ROOT>/root_pw still overrides it at start.
RUN --mount=type=secret,id=root_pw,required=false \
    if [ -s /run/secrets/root_pw ]; then head -n1 /run/secrets/root_pw | tr -d '\r' | sed 's/^/root:/' | chpasswd; fi
ENV OPENCODE_DISABLE_MODELS_FETCH=1 OPENCODE_DISABLE_AUTOUPDATE=1

# 파싱 엔진·OCR 의존성(무거움) — 코드 바뀌어도 다시 설치 안 되게 코드 복사 전에
FROM base AS parse-deps
RUN pip install --no-cache-dir $(cat /tmp/pipopt) -r /tmp/requirements-image.txt
# AD20(10-13, 사용자 결정) — pptx 슬라이드 렌더(LibreOffice headless → PDF → 쪽 이미지, pipeline/transform/figures/pptx_render.py)용.
# libreoffice-core(의존성)+writer+impress+calc(WMF/EMF가 docx·xlsx에도 나올 수 있어 최소 3모듈, --no-install-recommends로 추천 패키지는 뺌)
# + fonts-noto-cjk(한글 글꼴 — SETUP.md의 RHEL google-noto-sans-cjk-ttc-fonts와 같은 선택, 없으면 한글 슬라이드가 렌더 시 네모(tofu)로 나와 VLM이 못 읽음).
# 폐쇄망: 이 RUN은 PC(인터넷 있음)에서만 돌고 build_ship.sh가 결과 이미지를 서버로 반입 — 런타임 다운로드 없음.
# 새 이미지 판 필요(이 RUN이 바뀌면 덧씌우기로는 안 됨 — image-patch-process.md C2) — 파이프라인 이미지에만(mcp-server는 안 씀, soffice 안 씀 — grep 확인).
ARG APT=1
RUN if [ "$APT" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-core libreoffice-writer libreoffice-impress libreoffice-calc fonts-noto-cjk \
      && rm -rf /var/lib/apt/lists/*; fi

# ── 검색 MCP 실행 이미지(mcp-server-runtime — op-06, 코드 없음) ──
FROM base AS mcp-runtime
WORKDIR /app
# op-06(10-30, 사용자) — 실행 이미지(*-runtime): 코드 없음. 서버 코드 폴더(저장소 트리 그대로)를 /app/deploy에 읽기 전용으로 붙여 띄운다.
# 시작 스크립트 runtime_entry.sh가 코드 폴더·의존성 지문(deps_hash ↔ 코드 deploy/docker/DEPS_HASH)을 보고 코드의 entrypoint로 넘김.
# 코드가 든 이미지(아래 mcp·pipeline 타깃)는 이 단계 + 코드 COPY라 두 갈래의 바탕·의존성이 어긋나지 않는다.
COPY deploy/docker/runtime_entry.sh /app/docker/runtime_entry.sh
RUN mkdir -p /app/output /app/assets /app/deploy /data/docs && chown -R rag /app/output /data \
    && sed -i 's/\r$//' /app/docker/runtime_entry.sh && chmod +x /app/docker/runtime_entry.sh \
    && cat /tmp/requirements-core.txt /tmp/requirements-image.txt | tr -d '\r' | sha256sum | cut -c1-16 > /app/docker/deps_hash
ENV TZ=Asia/Seoul LANG=C.UTF-8 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/deploy \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 DO_NOT_TRACK=1 SCARF_NO_ANALYTICS=true \
    RAG_MODULE=mcp
RUN env > /app/docker/image_env.txt   # S7e2 — 이미지 ENV 기록(entrypoint가 lib_env와 견줘 사용자 env와 가름 — 비밀 없음)
ARG APP_VERSION=
ARG VCS_REF=
RUN echo "mcp-server-runtime ${APP_VERSION:-?} ${VCS_REF:-?}" > /app/docker/image_ref   # op-06 — 실행 기록에 남길 이미지 판
LABEL org.opencontainers.image.version=$APP_VERSION org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.title=mcp-server-runtime
USER rag
VOLUME ["/app/output"]
# dev_entry.sh: `devbox`면 SSH 작업 공간, 그 밖은 APP_ENTRY(이 이미지의 시작 스크립트)로 그대로. tini -s — --init 없이 띄워도 고아 프로세스를 거둠
ENV APP_ENTRY=/app/docker/runtime_entry.sh
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/etc/devbox/dev_entry.sh"]
CMD ["help"]

# ── 검색 MCP(mcp-server, S6b — 옛 data-retrieval·타깃 retrieval) — mcp_server + common만(파싱·구조화·적재 없음 — 명령용 pipeline/cli.py만, S4) ──
FROM mcp-runtime AS mcp
USER root
WORKDIR /app
COPY --from=src /src/common /app/deploy/common
COPY --from=src /src/mcp_server /app/deploy/mcp_server
COPY --from=src /src/pipeline/__init__.py /src/pipeline/cli.py /src/pipeline/config.py /app/deploy/pipeline/
COPY --from=src /src/resources /app/deploy/resources
COPY --from=src /src/VERSION /app/deploy/VERSION
COPY --from=src /src/edw_chain.yaml /app/deploy/edw_chain.yaml
COPY --from=src /src/appdocker /app/docker
COPY --from=src /src/tests/__init__.py /src/tests/runner.py /app/deploy/tests/
COPY --from=src /src/tests/server/__init__.py /app/deploy/tests/server/
COPY --from=src /src/tests/server/common /app/deploy/tests/server/common
COPY --from=src /src/tests/server/mcp /app/deploy/tests/server/mcp
RUN sed -i 's/\r$//' /app/docker/entrypoint.sh && chmod +x /app/docker/entrypoint.sh   # Windows 사본의 CRLF 줄 끝 제거
# 버전 라벨(D-036) — 넘긴 APP_VERSION이 이미지에 넣은 VERSION과 다르면 빌드를 멈춘다(태그와 이미지 안 버전 표기가 어긋나지 않게).
ARG APP_VERSION=
ARG VCS_REF=
RUN [ -z "$APP_VERSION" ] || [ "$APP_VERSION" = "$(tr -d ' \r\n' < /app/deploy/VERSION)" ] \
    || { echo "APP_VERSION($APP_VERSION) ≠ VERSION 파일" >&2; exit 1; }
LABEL org.opencontainers.image.version=$APP_VERSION org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.title=mcp-server
USER rag
ENV APP_ENTRY=/app/docker/entrypoint.sh
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/etc/devbox/dev_entry.sh"]
CMD ["help"]

# ── 파이프라인 실행 이미지(data-pipeline-runtime — op-06, 코드 없음) — RapidOCR 모델·LibreOffice는 이 단계에 ──
FROM parse-deps AS pipeline-runtime
WORKDIR /app
# op-06(10-30, 사용자) — 실행 이미지(*-runtime): 코드 없음. 서버 코드 폴더(저장소 트리 그대로)를 /app/deploy에 읽기 전용으로 붙여 띄운다.
# 시작 스크립트 runtime_entry.sh가 코드 폴더·의존성 지문(deps_hash ↔ 코드 deploy/docker/DEPS_HASH)을 보고 코드의 entrypoint로 넘김.
# 코드가 든 이미지(아래 mcp·pipeline 타깃)는 이 단계 + 코드 COPY라 두 갈래의 바탕·의존성이 어긋나지 않는다.
COPY --from=src /src/assets/ /app/assets/
RUN python - <<'EOF'
import glob, os, shutil, rapidocr
dst = os.path.join(os.path.dirname(rapidocr.__file__), "models")
os.makedirs(dst, exist_ok=True)
fs = glob.glob("/app/assets/rapidocr/*.onnx")
for f in fs:
    shutil.copy(f, dst)
print(f"rapidocr 모델 {len(fs)}개 복사" + ("" if fs else " — assets/rapidocr 없음: 첫 실행에 모델을 받음(인터넷 필요 — 폐쇄망은 assets 반입)"))
os.system(f"chown -R rag {dst}")                      # 실행 사용자(rag)가 모델을 받아 둘 수 있게(없으면 PermissionError로 회전 보정 실패)
EOF
COPY deploy/docker/runtime_entry.sh /app/docker/runtime_entry.sh
RUN mkdir -p /app/output /app/assets /app/deploy /data/docs && chown -R rag /app/output /data \
    && sed -i 's/\r$//' /app/docker/runtime_entry.sh && chmod +x /app/docker/runtime_entry.sh \
    && cat /tmp/requirements-core.txt /tmp/requirements-image.txt | tr -d '\r' | sha256sum | cut -c1-16 > /app/docker/deps_hash
# 실행 환경 기본값 — 시간대는 새벽 마감(NIGHT_DEADLINE) 계산에 쓰임(UTC면 9시간 어긋남). 바꾸려면 settings.yaml ops.runtime.lib_env(S7e2 — 옛 --env-file)
# SOFFICE_BIN(/usr/bin/soffice — soffice_bin()이 PATH보다 먼저 보는 명시 경로, AD20)·DOC_DIR·DOC_DIR_PREPARED·PIPE_EMBED·PIPE_PROCS는 S7e2부터
# 이미지 안 설정 모델 기본값(common.config.settings._IMAGE_DEFAULTS — B-2).
# HOME=/tmp: LibreOffice 자체 UserInstallation은 pptx_render.py가 output/ 아래 임시 폴더로 따로 주지만(프로필 잠금 분리),
# fontconfig 캐시 등 일부는 여전히 $HOME을 봄 — 비루트(rag) 기본 HOME(/home/rag)이 읽기 전용 루트에서 못 쓰일 때를 대비해
# 쓰기 가능한 /tmp로(컨테이너가 읽기 전용 루트+tmpfs /tmp로 뜰 때도 동작).
ENV TZ=Asia/Seoul LANG=C.UTF-8 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/deploy \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 DO_NOT_TRACK=1 SCARF_NO_ANALYTICS=true \
    RAG_MODULE=pipeline HOME=/tmp
RUN env > /app/docker/image_env.txt   # S7e2 — 이미지 ENV 기록(entrypoint가 lib_env와 견줘 사용자 env와 가름 — 비밀 없음)
ARG APP_VERSION=
ARG VCS_REF=
RUN echo "data-pipeline-runtime ${APP_VERSION:-?} ${VCS_REF:-?}" > /app/docker/image_ref   # op-06 — 실행 기록에 남길 이미지 판
LABEL org.opencontainers.image.version=$APP_VERSION org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.title=data-pipeline-runtime
USER rag
VOLUME ["/app/output"]
# dev_entry.sh: `devbox`면 SSH 작업 공간, 그 밖은 APP_ENTRY(이 이미지의 시작 스크립트)로 그대로. tini -s — --init 없이 띄워도 고아 프로세스를 거둠
ENV APP_ENTRY=/app/docker/runtime_entry.sh
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/etc/devbox/dev_entry.sh"]
CMD ["help"]

# ── 파이프라인(data-pipeline, S6b D-020 — 옛 data-parsing+data-structure) — pipeline 전체(엔진·검토 루프·구조화·적재·게시) + common ──
# 옛 structure 이미지는 이 이미지에서 파싱 엔진 패키지·LibreOffice만 빠진 것이었다(코드 폴더는 I2부터 같음) — 합쳐도 구조화·적재 명령은 그대로 돈다.
FROM pipeline-runtime AS pipeline
USER root
WORKDIR /app
COPY --from=src /src/common /app/deploy/common
COPY --from=src /src/pipeline /app/deploy/pipeline
COPY --from=src /src/mcp_server/__init__.py /src/mcp_server/config.py /app/deploy/mcp_server/
COPY --from=src /src/resources /app/deploy/resources
COPY --from=src /src/VERSION /app/deploy/VERSION
COPY --from=src /src/edw_chain.yaml /app/deploy/edw_chain.yaml
COPY --from=src /src/appdocker /app/docker
COPY --from=src /src/tests/__init__.py /src/tests/runner.py /app/deploy/tests/
COPY --from=src /src/tests/server/__init__.py /app/deploy/tests/server/
COPY --from=src /src/tests/server/common /app/deploy/tests/server/common
COPY --from=src /src/tests/server/pipeline /app/deploy/tests/server/pipeline
RUN sed -i 's/\r$//' /app/docker/entrypoint.sh && chmod +x /app/docker/entrypoint.sh   # Windows 사본의 CRLF 줄 끝 제거
# 버전 라벨(D-036) — 넘긴 APP_VERSION이 이미지에 넣은 VERSION과 다르면 빌드를 멈춘다(태그와 이미지 안 버전 표기가 어긋나지 않게).
ARG APP_VERSION=
ARG VCS_REF=
RUN [ -z "$APP_VERSION" ] || [ "$APP_VERSION" = "$(tr -d ' \r\n' < /app/deploy/VERSION)" ] \
    || { echo "APP_VERSION($APP_VERSION) ≠ VERSION 파일" >&2; exit 1; }
LABEL org.opencontainers.image.version=$APP_VERSION org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.title=data-pipeline
USER rag
ENV APP_ENTRY=/app/docker/entrypoint.sh
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/etc/devbox/dev_entry.sh"]
CMD ["help"]
