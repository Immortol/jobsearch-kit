#!/bin/bash
# Jobsearch-Kit · ночной прогон сканера. Запускается launchd (см. install.sh), можно и вручную:
#   bash ~/<папка поиска>/scanner/run-scan.sh
# Настройки берутся из папки scanner/ при каждом запуске — Claude правит их там.
KIT="$(cd "$(dirname "$0")" && pwd)"
CO="$(dirname "$KIT")/career-ops"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$CO" || { echo "career-ops не найден: $CO"; exit 1; }
mkdir -p data
cp "$KIT/portals.yml" portals.yml
cp "$KIT/presieve.mjs" kit-presieve.mjs
cp "$KIT/presieve.json" kit-presieve.json
{
  echo "=== $(date '+%Y-%m-%d %H:%M') ==="
  node scan.mjs --quiet
  if grep -q "^interamt_searches:" portals.yml; then node scan-interamt.mjs; fi
  node kit-presieve.mjs --apply
  echo "=== done $(date '+%H:%M') ==="
} >> data/scan.log 2>&1
