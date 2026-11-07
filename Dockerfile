# Dev container, not a production build. Pins the toolchain (Node + pnpm via
# corepack, Python via uv) so it's identical across every device/OS this repo
# gets opened on. Mount the repo at /workspace and run commands interactively
# inside it. Build/run verified via docker-compose.yml.
#
# Note: apps/recorder reads the Windows foreground window (ctypes.windll),
# so it only runs on a real Windows desktop session — not inside this
# (Linux) container. The container is still useful there for linting/tests.
# The `server` service in docker-compose.yml also runs the Cloudflare side (Worker + local
# D1 via `wrangler dev`) here, so the sync agent can be tested without deploying.
FROM node:24.22.1-bookworm-slim

# workerd(`wrangler dev`가 쓰는 Workers 런타임)는 시작할 때 시스템 CA 인증서를 읽는데, slim 이미지에는 없어서
# "No CA certificates were loaded from the system"으로 죽는다. docker-compose.yml의 `server` 서비스가 필요로 한다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN uv python install 3.14.8

WORKDIR /workspace

CMD ["bash"]
