# CS2 Demo Analytics Platform — Руководство для Gemini (GEMINI.md)

> **Для модели Gemini:** Этот файл определяет архитектурный контекст, критические правила кодогенерации и карту проекта.

---

## 📌 О проекте
Платформа анализа демок Counter-Strike 2. Преобразует бинарные файлы `.dem` в профессиональный соревновательный портал со сквозным All-Time MMR, 10-параметрическими рейтингами, очными дуэлями (Head-to-Head), интеграцией с официальным FACEIT API v4 и автоматическим развертыванием на GitHub Pages.

---

## 📚 Навигатор по модульным спецификациям (`instruction/`)
При решении профильных задач обращайтесь к соответствующим файлам:
- [01_parsing.md](file:///c:/agent/csdemo/instruction/01_parsing.md) — awpy v2, Polars, parquet тики, дедупликация Steam ID (`clean_steamid`).
- [02_analytics_ratings.md](file:///c:/agent/csdemo/instruction/02_analytics_ratings.md) — Рейтинги 1-10, Zero-Sum MMR (база ±15, импакт ±8, калибровка ×1.5), 2D матрица архетипов.
- [03_ai_coach.md](file:///c:/agent/csdemo/instruction/03_ai_coach.md) — 9-пунктовый протокол разбора раундов и тренерский аудит матча.
- [04_faceit.md](file:///c:/agent/csdemo/instruction/04_faceit.md) — FACEIT API v4, 24ч TTL кэш, векторные SVG бейджи уровней 1-10.
- [05_design_system.md](file:///c:/agent/csdemo/instruction/05_design_system.md) — Дизайн-токены Emerald & Gold, Glassmorphism, типографика Rajdhani/Inter.
- [06_validation.md](file:///c:/agent/csdemo/instruction/06_validation.md) — Проверки целостности (`verify_integrity.py`), относительные ссылки.
- [07_deployment_github.md](file:///c:/agent/csdemo/instruction/07_deployment_github.md) — CI/CD на GitHub Pages (`.github/workflows/deploy.yml`) и FTP.

---

## ⚠️ Критические технические инварианты для Gemini
1. **Потоковая запись Jinja2 шаблонов**:
   НИКОГДА не используйте `f.write(template.render(...))` для больших HTML страниц — это вызывает `MemoryError` на Windows.
   ВСЕГДА используйте потоковый дамп:
   ```python
   template.stream(context).dump(str(output_path), encoding='utf-8')
   ```
2. **Ленивый импорт тяжелых библиотек**:
   Библиотеки `awpy` и `polars` должны импортироваться только внутри функций парсинга, либо защищены условием `if args.stage in ("all", "parse"):`. Это гарантирует мгновенный запуск `site`, `verify` и `faceit` этапов.
3. **Строго относительные ссылки в HTML**:
   Все ссылки на страницы, стили (`css/style.css`), скрипты и иконки должны использовать `root_path` (`./` или `../`). Никогда не используйте абсолютные слэши (`/site/css/style.css`), иначе сайт сломается на GitHub Pages (`https://username.github.io/reponame/`).
4. **Безопасность API-ключей**:
   Ключи `FACEIT_API_KEY` и `GEMINI_API_KEY` считываются исключительно из переменных окружения (`.env` или GitHub Secrets) через безопасные функции без падений скрипта при их отсутствии.

---

## 🚀 Основные команды запуска
```powershell
python run.py                # Полный цикл
python run.py --stage site   # Быстрая пересборка страниц (< 1.5 сек)
python run.py --stage verify # Проверка целостности
python run.py --stage faceit # Синхронизация Faceit статистики
```
