# Dev container, not a production build. Pins the toolchain (Node + pnpm via
# corepack, Python via uv) so it's identical across every device/OS this repo
# gets opened on. Mount the repo at /workspace and run commands interactively
# inside it. Build/run verified via docker-compose.yml.
#
# Note: apps/recorder reads the Windows foreground window (ctypes.windll),
# so it only runs on a real Windows desktop session — not inside this
# (Linux) container. The container is still useful there for linting/tests.
FROM node:24.22.1-bookworm-slim

RUN corepack enable

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN uv python install 3.14.8

WORKDIR /workspace

CMD ["bash"]
