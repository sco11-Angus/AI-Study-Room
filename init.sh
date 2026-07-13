#!/usr/bin/env sh
set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

required_files="AGENTS.md README.md feature_list.json init.sh init.ps1 init.cmd PRD.md openspec/progress/progress.md openspec/progress/claude-progress.md"

for file in $required_files; do
  if [ ! -f "$file" ]; then
    echo "Missing required file: $file" >&2
    exit 1
  fi
done

if [ ! -x "node_modules/.bin/openspec" ]; then
  echo "OpenSpec is not installed. Run 'npm install' from the repository root." >&2
  exit 1
fi

node_modules/.bin/openspec validate --all --strict

md_count=$(find openspec docs -type f -name '*.md' | wc -l | tr -d ' ')
if [ "$md_count" -lt 8 ]; then
  echo "Expected at least 8 project markdown docs, found $md_count" >&2
  exit 1
fi

echo "Smoke test passed: OpenSpec validation and required project files passed."
