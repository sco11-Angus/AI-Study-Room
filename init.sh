#!/usr/bin/env sh
set -eu

required_files="AGENTS.md PRD.md progress.md feature_list.json init.sh"

for file in $required_files; do
  if [ ! -f "$file" ]; then
    echo "Missing required file: $file" >&2
    exit 1
  fi
done

md_count=$(find . -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')
if [ "$md_count" -lt 3 ]; then
  echo "Expected at least 3 markdown files, found $md_count" >&2
  exit 1
fi

echo "Smoke test passed: required files present; markdown docs found."
