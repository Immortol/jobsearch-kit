#!/bin/bash
# Jobsearch-Kit · установка сканера вакансий (macOS). Запускается один раз:
#   bash ~/<папка поиска>/scanner/install.sh
# Что делает: проверяет Node.js и git, скачивает career-ops (зафиксированная версия),
# ставит зависимости, делает пробный прогон и включает ночной запуск.
# Повторный запуск безопасен: обновит настройки и расписание, ничего не удалит.
set -euo pipefail

TAG="career-ops-v1.32.0"                       # проверенная версия career-ops
HOUR="${SCAN_HOUR:-3}"                         # час ночного запуска (по умолчанию 03:00)
KIT="$(cd "$(dirname "$0")" && pwd)"           # .../<папка поиска>/scanner
BASE="$(dirname "$KIT")"                       # .../<папка поиска>
CO="$BASE/career-ops"
LABEL="io.jobsearch-kit.scan"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

say() { printf "\n\033[1m%s\033[0m\n" "$1"; }

say "1/5 Проверяю Node.js и git"
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js не найден. Скачай установщик LTS-версии с https://nodejs.org, установи и запусти эту команду ещё раз."
  exit 1
fi
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "Нужен Node.js 18 или новее (сейчас $(node -v)). Обнови с https://nodejs.org и запусти ещё раз."
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo "git не найден. Выполни: xcode-select --install — согласись на установку и запусти эту команду ещё раз."
  exit 1
fi
echo "Node.js $(node -v), git — ок."

say "2/5 Скачиваю career-ops ($TAG)"
if [ ! -d "$CO/.git" ]; then
  git clone --quiet --depth 1 --branch "$TAG" https://github.com/career-ops-hq/career-ops.git "$CO"
else
  echo "Уже скачан — пропускаю."
fi

say "3/5 Ставлю зависимости (1–3 минуты)"
(cd "$CO" && npm install --no-audit --no-fund --loglevel=error)

say "4/5 Пробный прогон (ничего не записывает)"
cp "$KIT/portals.yml" "$CO/portals.yml"
cp "$KIT/presieve.mjs" "$CO/kit-presieve.mjs"
cp "$KIT/presieve.json" "$CO/kit-presieve.json"
(cd "$CO" && node scan.mjs --dry-run --quiet 2>&1 | tail -25) || echo "⚠️ Пробный прогон завершился с ошибкой — пришли этот вывод в чат с Claude."

say "5/5 Включаю ночной запуск в $(printf %02d "$HOUR"):00"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$KIT/run-scan.sh</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/tmp/jobsearch-scan.out</string>
  <key>StandardErrorPath</key><string>/tmp/jobsearch-scan.err</string>
</dict>
</plist>
PLISTEOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Ночной запуск включён."

say "Готово"
echo "Чтобы Mac просыпался ночью для сканера (рекомендуем), выполни ещё одну команду — она попросит пароль от Mac:"
WAKE_MIN=$(( HOUR * 60 - 5 )); [ "$WAKE_MIN" -lt 0 ] && WAKE_MIN=$(( WAKE_MIN + 1440 ))
printf "  sudo pmset repeat wakeorpoweron MTWRFSU %02d:%02d:00\n" $(( WAKE_MIN / 60 )) $(( WAKE_MIN % 60 ))
echo "Mac при этом должен быть подключён к питанию. Напиши в чат с Claude «сканер установлен»."
