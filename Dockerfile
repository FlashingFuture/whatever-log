# Dev container, not a production build. No app code exists yet, so this
# only pins the toolchain (Node + pnpm via corepack) so it's identical across
# every device/OS this repo gets opened on. Mount the repo at /workspace and
# run commands (pnpm install, pnpm lint, ...) interactively inside it.
#
# NOT build-tested yet — this laptop has no Docker. Verify on a Docker-capable
# machine before relying on it.
FROM node:24.20.0-bookworm-slim

RUN corepack enable

WORKDIR /workspace

CMD ["bash"]
