# Руководство по развертыванию на GitHub Pages и настройке FACEIT API

Данное руководство описывает архитектуру платформы **CS2 Demo Analytics**, порядок настройки API ключей и пошаговый процесс публикации сайта на **GitHub Pages** (с альтернативой для классического хостинга по FTP/SFTP).

---

## 🏛 1. Архитектура платформы

Проект построен по принципу **Jamstack / Static Site Generation (SSG)**:
- **Локальный аналитический конвейер (Python 3.12)**:
  - `awpy` парсит `.dem` файлы в директории `demos/`.
  - `analyze.py` вычисляет рейтинги (1.0–10.0), MMR, форму и тренерские рекомендации.
  - `fetch_faceit.py` запрашивает официальный FACEIT API и кэширует данные в `data/faceit/{steam_id}.json`.
  - `generate_site.py` на основе шаблонов Jinja2 компилирует готовый статичный сайт в папку `site/`.
- **Фронтенд (папка `site/`)**:
  - Полностью автономен: HTML5, CSS3 (Glassmorphic Cyber Emerald & Gold), Vanilla JS, Chart.js.
  - **Все ссылки и ресурсы являются относительными** (`./`, `../`, `root_path`).
  - Сайт **не требует** базы данных (PostgreSQL/MySQL) или Node.js/PHP на стороне хостинга.
  - Персонализация («⭐ Мой профиль / Кто ты?») и подсветка игрока работают на стороне клиента через `localStorage`.

---

## 🔑 2. Где настраивать API ключи и конфигурацию

### А. Локальная разработка (.env)
Создайте в корне проекта файл `c:\agent\csdemo\.env` (или настройте системные переменные окружения):

```ini
# Официальный ключ разработчика FACEIT (https://developers.faceit.com/)
FACEIT_API_KEY=your_faceit_api_key_here

# Ключ Gemini API для тактического ИИ-комментатора
GEMINI_API_KEY=your_gemini_api_key_here

# (Опционально) Базовый URL для генерации абсолютных мета-ссылок
SITE_BASE_URL=https://<your-username>.github.io/<repo-name>
```

> **Безопасность:** Файл `.env` добавлен в `.gitignore` и **никогда не попадет в публичный репозиторий**!

### Б. GitHub Secrets (для автоматического запуска через GitHub Actions)
Если вы хотите, чтобы сборка и обновление происходили в облаке GitHub:
1. Перейдите в ваш репозиторий на GitHub: `Settings` ➔ `Secrets and variables` ➔ `Actions`.
2. Нажмите **New repository secret**.
3. Добавьте секреты:
   - Имя: `FACEIT_API_KEY`, Значение: ваш ключ Faceit.
   - Имя: `GEMINI_API_KEY`, Значение: ваш ключ Gemini.

---

## 🚀 3. Развертывание на GitHub Pages

### Способ 1: Автоматический деплой через GitHub Actions (Рекомендуемый)
Создайте файл `.github/workflows/deploy.yml` в вашем репозитории:

```yaml
name: Deploy CS2 Analytics to GitHub Pages

on:
  push:
    branches: [ main ]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: true

jobs:
  build-and-deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Setup Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Fetch FACEIT & Generate Site
        env:
          FACEIT_API_KEY: ${{ secrets.FACEIT_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          python run.py --stage site

      - name: Setup Pages
        uses: actions/configure-pages@v4

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: 'site/'

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

В настройках репозитория GitHub:
1. `Settings` ➔ `Pages`.
2. В разделе **Build and deployment** ➔ **Source** выберите **GitHub Actions**.
3. После каждого коммита в `main` сайт будет автоматически обновляться по адресу:
   `https://<username>.github.io/<repository-name>/`

---

### Способ 2: Ручной деплой сгенерированной папки `site/` (gh-pages)
Если вы генерируете сайт локально на своем компьютере:
```powershell
# 1. Сгенерировать свежий сайт
python run.py --stage all

# 2. Опубликовать папку site в ветку gh-pages через git subtree
git add -f site
git commit -m "Build: update site"
git subtree push --prefix site origin gh-pages
```
В настройках `Settings` ➔ `Pages` выберите ветку `gh-pages` и папку `/(root)`.

---

## 🌐 4. Альтернативный вариант: Обычный хостинг по FTP / SFTP

Если вы решите загрузить сайт на классический хостинг (Beget, TimeWeb, Reg.ru, cPanel):
1. Запустите сборку локально:
   ```powershell
   python run.py --stage all
   ```
2. Подключитесь к хостингу через **FileZilla** или **WinSCP** (SFTP).
3. Скопируйте **содержимое папки `site/`** (файлы `index.html`, `skills.html`, `css/`, `js/`, `players/`, `matches/`, `icons/`) в корневую веб-директорию хостинга (обычно `public_html/` или `httpdocs/`).
4. Всё готово! Сайт мгновенно доступен без настройки баз данных.

---

## ⚡ 5. Модульные команды запуска (`run.py --stage`)

Теперь конвейер разделен на независимые этапы:

```powershell
# Полный цикл (парсинг -> анализ -> faceit -> генерация сайта -> проверка)
python run.py

# Только синхронизация статистики с FACEIT API
python run.py --stage faceit

# Быстрая перегенерация сайта (без повторного парсинга демок)
python run.py --stage site

# Только запуск ИИ-комментатора через Gemini API
python run.py --stage ai

# Проверка целостности данных и шаблонов
python run.py --stage verify

# Полная очистка кэша и пересборка с нуля
python run.py --force
```

---

## 🎯 6. Возможности FACEIT и персонализации

1. **Официальные уровни 1–10**:
   - Точные векторные SVG бейджи (`site/icons/faceit/level_X.svg`) с динамической цветовой дугой прогресса.
   - Для игроков без привязки отображается аутентичный знак калибровки (`?`).
2. **Таблица лидеров (`index.html`)**:
   - Выделенная колонка **FACEIT**: отображает уровень, Elo, последнее изменение (`▲+25` / `▼-15`) и динамику формы (`▲ 3W • На подъёме` / `▼ 2L • Спад` / `● Стабильно`).
3. **Профиль игрока (`players/{id}.html`)**:
   - Официальная брендированная карточка FACEIT: K/D, винрейт, количество матчей, процент хедшотов, макс. стрик и 5 крайних матчей со ссылками.
4. **Виджет «👤 Кто ты?»**:
   - Позволяет игроку выбрать свой ник в шапке сайта.
   - Выбор сохраняется в браузере (`localStorage`).
   - Игрок подсвечивается изумрудным градиентом в таблицах и карточках с бейджем `⭐ ВЫ`.
