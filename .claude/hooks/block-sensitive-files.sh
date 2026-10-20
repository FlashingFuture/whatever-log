#!/bin/bash
# PreToolUse (Edit|Write): block edits to .env / secrets.* files. exit 2 = blocked.

f=$(jq -r '.tool_input.file_path // empty')

case "$(basename -- "$f")" in
  .env|.env.*|secrets.*|secrets)
    exit 2
    ;;
esac
