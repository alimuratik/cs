# Руководство по развертыванию на GitHub Pages и хостинг (07_deployment_github.md)

## 📌 Обзор архитектуры развертывания
Платформа сгенерирована по принципу **Jamstack** (автономный статический сайт). Все вычисления производятся локально или в CI/CD, а результат компилируется в самодостаточную директорию `site/`, готовую для публикации на GitHub Pages или любом обычном веб-хостинге (по FTP/SFTP) без базы данных на сервере.

---

## 🚀 Вариант 1: Автоматический деплой на GitHub Pages (Рекомендуемый)

### 1. Настройка репозитория GitHub
1. Перейдите в **Settings** ➔ **Pages**.
2. В секции **Build and deployment**:
   - Выберите **Source**: `GitHub Actions`.
3. (Опционально) В **Settings** ➔ **Secrets and variables** ➔ **Actions** добавьте секреты:
   - `FACEIT_API_KEY` — ключ API FACEIT.
   - `GEMINI_API_KEY` — ключ Google Gemini (если требуется генерация ИИ-комментариев в облаке).

### 2. Структура GitHub Actions Workflow (`.github/workflows/deploy.yml`)
Workflow запускается автоматически при каждом `git push` в ветку `main` или вручную через кнопку **Run workflow**:

```yaml
name: Deploy CS2 Analytics to GitHub Pages

on:
  push:
    branches:
      - main
      - master
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  build-and-deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install lightweight site generator dependencies
        run: |
          python -m pip install --upgrade pip
          pip install jinja2

      - name: Build static site
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
          path: './site'

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

---

## 🌐 Вариант 2: Размещение на обычном хостинге (FTP / SFTP)

Если вы используете классический виртуальный хостинг (Beget, TimeWeb, Reg.ru, cPanel и т.д.):
1. Выполните локальную сборку сайта:
   ```powershell
   python run.py --stage site
   ```
2. Откройте ваш FTP-клиент (FileZilla, WinSCP) или веб-файловый менеджер панели хостинга.
3. Загрузите всё содержимое папки `C:\agent\csdemo\site\` в корневой каталог сайта на хостинге (обычно `public_html` или `httpdocs`).
4. Сайт станет моментально доступен без необходимости установки Python или баз данных на сервере.

---

## 🔗 Относительные пути
Все ссылки в шаблонах платформы используют относительные пути (`./`, `../`), поэтому сайт работает без правок как в корне домена (`https://cs2.mydomain.com/`), так и в подкаталогах репозитория (`https://username.github.io/csdemo/`).
