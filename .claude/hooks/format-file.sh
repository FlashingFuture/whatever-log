#!/bin/bash
# PostToolUse (Edit|Write): auto-format the touched file with Biome.
# Call the local binary directly — pnpm/corepack may not be on PATH here.
# Swallow failures (e.g. before `pnpm install` has run) — always exit 0.

f=$(jq -r '.tool_response.filePath // .tool_input.file_path // empty')
biome="${CLAUDE_PROJECT_DIR}/node_modules/.bin/biome"

[ -n "$f" ] && [ -x "$biome" ] && "$biome" check --write --no-errors-on-unmatched "$f" 2>/dev/null
true
