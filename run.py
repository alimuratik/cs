import sys
import os
import argparse
import logging

sys.stdout.reconfigure(encoding='utf-8')

from scripts.config import *

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def main():
    parser = argparse.ArgumentParser(description="CS2 Demo Analytics Platform Entrypoint")
    parser.add_argument("--stage", choices=["all", "parse", "calc", "ai", "faceit", "site", "verify"], default="all",
                        help="Запустить конкретный этап пайплайна (all, parse, calc, ai, faceit, site, verify)")
    parser.add_argument("--force", action="store_true", help="Перепарсить все демки с нуля / принудительно обновить кэш")
    parser.add_argument("--ai", action="store_true", help="Запустить AI-анализ через Gemini API")
    args = parser.parse_args()

    print("==================================================")
    print("🚀 CS2 DEMO ANALYTICS PLATFORM")
    print(f"📌 Выбранный этап: {args.stage.upper()}")
    print("==================================================")

    if args.force and args.stage in ["all", "parse"]:
        registry_path = DATA_DIR / "registry.json"
        players_db_path = DATA_DIR / "players_db.json"
        players_dir = DATA_DIR / "players"
        matches_dir = DATA_DIR / "matches"
        if registry_path.exists():
            try: os.remove(registry_path)
            except Exception: pass
        if players_db_path.exists():
            try: os.remove(players_db_path)
            except Exception: pass
        if players_dir.exists():
            for f in os.listdir(players_dir):
                try: os.remove(players_dir / f)
                except Exception: pass
        if matches_dir.exists():
            for f in os.listdir(matches_dir):
                try: os.remove(matches_dir / f)
                except Exception: pass
        print("Реестр и устаревший кэш демок очищены.")

    # Этап 1: Парсинг демок
    if args.stage in ["all", "parse"]:
        print("\n--- [1/5] Поиск и парсинг демок (awpy) ---")
        from scripts.parse_demos import parse_all_new
        parse_all_new()

    # Этап 2: Анализ и расчет рейтингов
    if args.stage in ["all", "calc", "ai"]:
        print("\n--- [2/5] Расчет аналитики и рейтингов ---")
        from scripts.analyze import run_analysis
        run_analysis(force_ai=(args.ai or args.stage == "ai"))

    # Этап 3: Синхронизация официальной статистики FACEIT API
    if args.stage in ["all", "faceit"]:
        print("\n--- [3/5] Синхронизация FACEIT API ---")
        try:
            from scripts.fetch_faceit import fetch_all_faceit
            fetch_all_faceit(force=args.force)
        except Exception as e:
            logging.warning(f"Ошибка на этапе FACEIT API: {e}. Продолжаем выполнение.")

    # Этап 4: Генерация сайта
    if args.stage in ["all", "site"]:
        print("\n--- [4/5] Генерация HTML сайта ---")
        from scripts.generate_site import generate_site
        generate_site()

    # Этап 5: Проверка целостности данных
    if args.stage in ["all", "verify"]:
        print("\n--- [5/5] Верификация целостности данных и артефактов ---")
        from scripts.verify_integrity import verify_all
        verify_all()

    print("\n==================================================")
    print("✅ ЭТАПЫ ЗАВЕРШЕНЫ УСПЕШНО!")
    print(f"🌐 Откройте сайт: file:///{SITE_DIR / 'index.html'}")
    print("==================================================")

if __name__ == "__main__":
    main()

