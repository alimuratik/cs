# CS2 Demo Analytics Platform — Руководство по проекту для ИИ (AGENTS.md)

> **AI-агент:** перед началом работы прочти `PROJECT_STATE.md` в корне проекта.
> Он содержит актуальный слепок состояния: бизнес-правила, ограничения, технический долг.
> **Модульные спецификации:** подробные технические регламенты по каждому направлению вынесены в папку `instruction/`.

## 📌 Описание проекта
Автономная соревновательная аналитическая платформа для глубокого разбора матчей Counter-Strike 2 (CS2), расчета всестороннего All-Time MMR, отслеживания прогресса игроков, синхронизации с официальным FACEIT API и публикации веб-портала (Jamstack) на GitHub Pages или обычном хостинге.

## 🛠 Технологический стек
- **Язык**: Python 3.12+
- **Парсинг демок**: `awpy` >= 2.0 (`awpy.Demo`), `Polars`, `Pandas`
- **Шаблонизатор**: `Jinja2` (потоковый рендеринг через `template.stream().dump()`)
- **Фронтенд**: Чистый HTML5, Vanilla CSS3 (Glassmorphic Dark Cyber Theme Emerald & Gold), Chart.js
- **Внешние интеграции**: Официальный FACEIT API v4, Google Gemini 2.5 Flash / OpenAI
- **CI/CD Деплой**: GitHub Actions (`.github/workflows/deploy.yml`) ➔ GitHub Pages

## 📚 Модульные регламенты и спецификации (`instruction/`)
При выполнении задач в соответствующих областях обязательно руководствуйтесь модульными инструкциями:
1. **[01_parsing.md](file:///c:/agent/csdemo/instruction/01_parsing.md)** — Спецификация парсинга демок, awpy v2, схемы событий, parquet тики, дедупликация Steam ID.
2. **[02_analytics_ratings.md](file:///c:/agent/csdemo/instruction/02_analytics_ratings.md)** — Математика рейтингов 1-10, Zero-Sum MMR, калибровка, 2D матрица архетипов, H2H дуэли.
3. **[03_ai_coach.md](file:///c:/agent/csdemo/instruction/03_ai_coach.md)** — Протокол ИИ-комментатора (9 обязательных пунктов разбора раундов) и тренерский аудит матча.
4. **[04_faceit.md](file:///c:/agent/csdemo/instruction/04_faceit.md)** — Интеграция с FACEIT API v4, 24ч TTL кэш, обработка 404, векторные SVG бейджи уровней 1-10.
5. **[05_design_system.md](file:///c:/agent/csdemo/instruction/05_design_system.md)** — Токены Emerald & Gold, Glassmorphism, типографика Rajdhani/Inter, интерактивные фильтры.
6. **[06_validation.md](file:///c:/agent/csdemo/instruction/06_validation.md)** — Регламент валидации данных и ссылок, запуск `scripts/verify_integrity.py`.
7. **[07_deployment_github.md](file:///c:/agent/csdemo/instruction/07_deployment_github.md)** — Архитектура GitHub Actions CI/CD и руководство по FTP/SFTP деплою.

## 📁 Структура каталогов
```text
C:\agent\csdemo\
├── .github/workflows/deploy.yml # Автоматический деплой на GitHub Pages
├── demos/                    # Входные .dem файлы (группировка по папкам DDMMYYYY)
├── data/                     # Обработанные данные
│   ├── matches/              # Выжимки матчей (.json)
│   ├── players/              # Профили игроков (.json)
│   ├── faceit/               # Локальный кэш FACEIT API (.json)
│   ├── ticks/                # Данные тиков (.parquet)
│   ├── registry.json         # Реестр распарсенных демок
│   └── players_db.json       # Глобальная история игроков
├── docs/                     # Документация и руководства
│   └── github_pages_guide.md # Руководство по публикации на GitHub Pages
├── instruction/              # Модульные спецификации и регламенты (01-07)
├── rules/                    # База знаний и правил
│   └── recommendations.json  # Правила выдачи советов
├── scripts/                  # Python скрипты
│   ├── config.py             # Настройки, пути, маппинги карт, FACEIT_API_KEY
│   ├── parse_demos.py        # Извлечение данных из демок через awpy
│   ├── analyze.py            # Расчет рейтингов 1-10, SWOT, стабильности
│   ├── ai_analysis.py        # ИИ-комментатор раундов и матчей
│   ├── fetch_faceit.py       # Синхронизация профилей с официальным FACEIT API
│   ├── faceit_icons.py       # Генератор точных векторных SVG бейджей Faceit 1-10
│   ├── generate_site.py      # Генерация HTML страниц (streaming dump)
│   └── verify_integrity.py   # Проверка целостности данных и артефактов
├── templates/                # Jinja2 шаблоны (base, index, match, player, session, compare, matchmaker)
├── site/                     # Сгенерированный автономный веб-сайт (Jamstack)
├── GEMINI.md                 # Путеводитель для модели Gemini
└── run.py                    # Единый CLI запуск (python run.py [--stage ...] [--force])
```

## ⚖️ Система рейтингов (1.0 — 10.0) и соревновательный MMR
- 10 параметров линейной нормализации: Aim, Positioning, Utility, Game Sense, Entry, Trading, Clutch, Discipline, Economy, Overall Impact.
- Цветовая схема Emerald & Gold:
  - `8.0-10.0`: 👑 Элитный (`rating-gold`, `#fbbf24`)
  - `7.0-7.9`: 🟢 Высокий (`rating-green`, `#10b981`)
  - `5.0-6.9`: 🟡 Средний (`rating-yellow`, `#f59e0b`)
  - `1.0-4.9`: 🔴 Зона риска (`rating-red`, `#ef4444`)
- All-Time Zero-Sum MMR: старт 1000 MMR (Level 6), базовые ±15 за победу/поражение, личный импакт HLTV 2.0 (±8 MMR), множитель калибровки ×1.5 для первых 5 матчей.

## 🎮 FACEIT API и Персонализация («Кто ты?»)
- **Интеграция**: `scripts/fetch_faceit.py` запрашивает официальный API FACEIT (профиль, Elo, уровень 1-10, винстрик, история 5 матчей) и кэширует данные в `data/faceit/` на 24 часа (404 на 7 дней).
- **Безопасность**: `FACEIT_API_KEY` считывается из `.env` или GitHub Secrets. При отсутствии ключа система безопасно пропускает запросы.
- **Персонализация**: В шапке сайта доступен селектор «👤 Кто ты?» с сохранением в `localStorage` и подсветкой строки игрока (`⭐ ВЫ`, `.my-profile-highlight`).
- **Интерактивные фильтры**: Мгновенная клиентская фильтрация без перезагрузки страниц (поиск игроков, тиры, карты, победы/поражения).

## 🚀 Команды для запуска
```powershell
# Стандартный полный запуск (парсинг -> анализ -> faceit -> генерация сайта -> проверка)
python run.py

# Модульный запуск конкретного этапа (--stage [parse|calc|ai|faceit|site|verify])
python run.py --stage site      # Мгновенная перегенерация HTML страниц без повторного парсинга (< 1.5 сек)
python run.py --stage verify    # Проверка целостности данных и артефактов
python run.py --stage faceit    # Синхронизация статистики с FACEIT API
python run.py --stage calc      # Пересчет рейтингов 1-10 и MMR

# Полная очистка и пересборка всей базы и сайта
python run.py --force
```
