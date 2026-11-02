#!/bin/bash
# Собирает ZIP-архивы скиллов для версии «в приложении Claude»: dist/<skill>.zip и dist/Jobsearch-Kit.zip
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
rm -rf "$ROOT/dist" && mkdir -p "$ROOT/dist/bundle/Jobsearch-Kit"
cd "$ROOT/skills"
for s in */; do
  s="${s%/}"
  [ -f "$s/SKILL.md" ] || continue
  zip -qrD "$ROOT/dist/$s.zip" "$s" -x '*/.DS_Store'
  cp "$ROOT/dist/$s.zip" "$ROOT/dist/bundle/Jobsearch-Kit/"
  echo "ok $s"
done
cd "$ROOT/dist/bundle" && zip -qr "$ROOT/dist/Jobsearch-Kit.zip" Jobsearch-Kit && rm -rf "$ROOT/dist/bundle"
echo "→ $ROOT/dist/"
