# Как собрать настройки сканера из правил человека

Сканер — проект с открытым кодом **career-ops** (MIT), зафиксированная версия `career-ops-v1.32.0`. Он обходит источники без затрат токенов и пишет новые вакансии в `career-ops/data/pipeline.md` строками:
`- [ ] <ссылка> | <компания> | <роль> | <место> | posted: <дата>`.

Настройки лежат в папке поиска человека: `scanner/portals.yml` (что искать и где) и `scanner/presieve.json` (что отсеивать до оценки). Перед каждым ночным прогоном `run-scan.sh` копирует их в career-ops — поэтому правь только файлы в `scanner/`.

Главный принцип: **сканер ищет широко, сужает только то, что человек явно сказал**. Лишнее отсеется дёшево (предотсев и оценка), а пропущенную вакансию никто не увидит.

## portals.yml — четыре блока

Полный справочник полей — `career-ops/templates/portals.example.yml` (после установки). Ниже — что из правил куда.

### 1. `title_filter` — названия ролей
```yaml
title_filter:
  positive:            # совпадение подстроки, без учёта регистра; "A + B" — обе подстроки
    - "Product Designer"
    - "UX/UI"
    - "Дизайнер + интерфейс"
    - "Project Manager"
  negative:            # "word:X" — целое слово
    - "word:Intern"
    - "Стажёр"
```
- `positive` — роли «да» из `03_Strategy` **на всех языках рынков поиска** (англ., местный, русский для русскоязычных компаний) плюс синонимы и смежные роли, которые человек принял. Мало названий — мало вакансий: лучше 30–60 строк, чем 5.
- `negative` — только то, что человек назвал «нет» (уровень, стажировки, продажи и т. п.). Не добавляй «на всякий случай».

### 2. `location_filter` — география
```yaml
location_filter:
  block_hard: ["United States", "India"]   # отказ всегда
  always_allow: ["Remote", "Serbia", "Belgrade"]
  block: []                                  # отказ, если нет always_allow
```
Логика сверху вниз: `block_hard` → `always_allow` → `block` → всё остальное проходит. Строки без места проходят — это нормально.
- `always_allow` — города/страны поиска, «Remote», «Europe»/«EMEA»/«Worldwide» (если человек открыт к удалёнке), страны возможного переезда.
- `block_hard` — только регионы, где человек точно не может работать (визы, часовые пояса, его прямое «нет»). Если сомневаешься — не блокируй.

### 3. `job_boards` — порталы и доски
Стартовые наборы по рынкам (проверь, что у человека этот рынок в `03_Strategy`):

| Рынок | Источники в сканере | Что остаётся почте |
|---|---|---|
| `DE` | `arbeitsagentur` (ключевые слова = роли «да» по-немецки и по-английски), `arbeitnow`; госсектор — блок `interamt_searches` | StepStone, LinkedIn, XING, Indeed — рассылки |
| `IL` | доски компаний (см. блок 4): `comeet`, `greenhouse`, `lever`, `ashby` | LinkedIn, AllJobs, JobMaster — рассылки |
| `RU` | — (открытый API поиска hh.ru для частных лиц закрыт с апреля 2026) | hh.ru (автопоиск → письма), Хабр Карьера — рассылки |
| `REMOTE` | `remotive`, `remoteok`, `weworkremotely`, `himalayas`, `workingnomads`, `jobicy` | LinkedIn (фильтр Remote) — рассылки |

Пример:
```yaml
job_boards:
  - name: Arbeitsagentur
    provider: arbeitsagentur
    arbeitsagentur:
      keywords: ["Projektmanager IT", "IT Project Manager"]
    enabled: true
  - name: Remotive
    provider: remotive
    enabled: true
```

### 4. `tracked_companies` — конкретные компании
Компании, где человек особенно хочет работать, компании со знакомыми, крупные работодатели его рынка и роли.
```yaml
tracked_companies:
  - name: Example GmbH
    careers_url: https://example.jobs.personio.de
    enabled: true
  - name: Example IL
    api: https://www.comeet.co/careers-api/2.0/company/<uid>/positions?token=<token>
    enabled: true
```
- Как найти доску компании: `node discover-ats.mjs` в папке career-ops — принимает список компаний и подбирает доски, которые сканер умеет читать; по умолчанию только показывает, ничего не пишет. Или открой страницу вакансий компании и посмотри, куда ведут ссылки (personio, greenhouse, lever, ashby, workday, comeet, smartrecruiters, recruitee…).
- Comeet (частый в Израиле): нужна полная ссылка API с `uid` и `token` — её видно в коде страницы вакансий компании.
- Глобальные доски крупных компаний (Workday и т. п.) показывают вакансии со всего мира — для них в `presieve.json` есть `global_companies` + `allowed_locations`.

## presieve.json — предотсев

Пример — `assets/presieve.example.json`. Поля:
- `max_age_days` — старше этого не оцениваем (обычно 21).
- `exclude_title` — `[{reason, pattern}]`, регулярные выражения по названию: только роли и уровни «нет» из `03_Strategy`.
- `exclude_company` — отрасли и компании «нет».
- `protect_company` — компании, которые никогда не отсеиваются (приоритетные, со знакомыми).
- `global_companies` + `allowed_locations` — для глобальных досок: оставить только вакансии в географии поиска.
Дубли (та же компания и роль) отсеиваются всегда.

## После правок
- Пробный прогон через связь с компьютером невозможен (сеть там ограничена) — попроси человека выполнить `bash <папка>/scanner/run-scan.sh` в Терминале или дождись ночи и проверь `career-ops/data/scan.log`.
- Каждое изменение — строка в `Rules/CHANGELOG.md`.
