# scripts/verify_integrity.py
import sys
import os
import json
import re
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

ROOT_DIR = Path(r"C:\agent\csdemo")
MATCHES_DIR = ROOT_DIR / 'data' / 'matches'
PLAYERS_DIR = ROOT_DIR / 'data' / 'players'
SITE_DIR = ROOT_DIR / 'site'

def test_matches():
    print('=== 1. Проверка файлов матчей (data/matches/) ===')
    if not MATCHES_DIR.exists():
        print('Папка data/matches не найдена!')
        return False

    matches = list(MATCHES_DIR.glob('*.json'))
    print(f'Найдено матчей: {len(matches)}')
    
    legacy_count = 0
    structured_count = 0
    economy_issues = 0
    missing_summary = 0

    for m_path in matches:
        with open(m_path, 'r', encoding='utf-8') as f:
            m = json.load(f)

        rounds = m.get('rounds', [])
        for r in rounds:
            ai_text = r.get('ai_analysis', '')
            if 'Завязка раунда началась' in ai_text:
                legacy_count += 1
            if '1. Исход и сценарий' in ai_text:
                structured_count += 1
                
            # Проверка экономики
            r_num = r.get('round_num') or r.get('number') or 1
            ct_eco = r.get('ct_economy')
            t_eco = r.get('t_economy')
            if not ct_eco or not t_eco:
                economy_issues += 1

        if not m.get('summary_analysis'):
            missing_summary += 1

    print(f'-> Раундов с 9-пунктовой структурой: {structured_count}')
    print(f'-> Раундов с устаревшей фразой Завязка раунда: {legacy_count}')
    print(f'-> Проблем с привязкой экономики CT/T: {economy_issues}')
    print(f'-> Матчей без сводного тренерского анализа: {missing_summary}')
    return legacy_count == 0 and economy_issues == 0 and missing_summary == 0

def test_players():
    print('=== 2. Проверка базы игроков (data/players/) ===')
    if not PLAYERS_DIR.exists():
        print('Папка data/players не найдена!')
        return False
    players = list(PLAYERS_DIR.glob('*.json'))
    print(f'Найдено игроков: {len(players)}')
    
    invalid_sids = 0
    for p_path in players:
        sid = p_path.stem
        if not sid.isdigit() or len(sid) < 10:
            invalid_sids += 1
    print(f'-> Некорректных Steam ID: {invalid_sids}')
    return invalid_sids == 0

FACEIT_DIR = ROOT_DIR / 'data' / 'faceit'

def test_faceit():
    print('=== 3. Проверка кэша FACEIT (data/faceit/) ===')
    if not FACEIT_DIR.exists():
        print('Папка data/faceit не найдена (будет создана при первом запуске)')
        return True
    
    faceit_files = list(FACEIT_DIR.glob('*.json'))
    print(f'Найдено кэшированных профилей Faceit: {len(faceit_files)}')
    
    found_count = 0
    not_found_count = 0
    corrupt_count = 0
    
    for f_path in faceit_files:
        try:
            with open(f_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get('found'):
                found_count += 1
            else:
                not_found_count += 1
        except Exception:
            corrupt_count += 1
            
    print(f'-> Найдено активных профилей на Faceit: {found_count}')
    print(f'-> Не найдено на платформе (кэш 404): {not_found_count}')
    if corrupt_count > 0:
        print(f'-> Поврежденных файлов кэша: {corrupt_count}')
    return corrupt_count == 0

def test_site():
    print('=== 4. Проверка сгенерированного сайта (site/) ===')
    if not SITE_DIR.exists():
        print('Папка site не найдена!')
        return False
        
    core_pages = ['index.html', 'skills.html', 'demos.html', 'compare.html', 'matchmaker.html']
    missing_pages = [p for p in core_pages if not (SITE_DIR / p).exists()]
    
    if missing_pages:
        print(f'-> Отсутствуют основные HTML страницы: {missing_pages}')
        return False
        
    faceit_icons_dir = SITE_DIR / 'icons' / 'faceit'
    missing_icons = []
    if faceit_icons_dir.exists():
        for lvl in range(0, 11):
            if not (faceit_icons_dir / f"level_{lvl}.svg").exists():
                missing_icons.append(f"level_{lvl}.svg")
    else:
        missing_icons = ["директория отсутствует"]
        
    if missing_icons:
        print(f'-> Отсутствуют SVG иконки Faceit: {missing_icons}')
        return False
        
    print('-> Все основные HTML страницы и Faceit SVG иконки на месте')
    return True

def verify_all() -> bool:
    ok1 = test_matches()
    ok2 = test_players()
    ok3 = test_faceit()
    ok4 = test_site()
    all_ok = ok1 and ok2 and ok3 and ok4
    if all_ok:
        print('\n✅ Все проверки целостности данных пройдены успешно!')
    else:
        print('\n⚠️ Некоторые проверки выявили предупреждения или требуется пересборка.')
    return all_ok

if __name__ == '__main__':
    verify_all()

