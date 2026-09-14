# scripts/fetch_faceit.py
"""
Модуль синхронизации со статистикой официального FACEIT API v4.
Извлекает реальный Elo, уровень мастерства (1-10), K/D, винрейт, винстрик и историю матчей.
Кэширует результаты локально в data/faceit/{clean_steamid}.json со сроком жизни TTL.
"""

import os
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
import logging

from scripts.config import (
    FACEIT_API_KEY,
    FACEIT_DIR,
    DATA_DIR,
    clean_steamid,
    CANONICAL_PLAYERS,
    PLAYER_ALIASES,
)

logger = logging.getLogger(__name__)

FACEIT_API_BASE = "https://open.faceit.com/data/v4"
CACHE_TTL_HOURS = 24
NOT_FOUND_CACHE_DAYS = 7


def _make_faceit_request(url: str, api_key: str) -> dict | None:
    """Выполняет авторизованный запрос к Faceit API с обработкой ошибок."""
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Accept": "application/json",
        "User-Agent": "CS2DemoAnalytics/2.0",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = response.read().decode("utf-8")
                return json.loads(data)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"error": 404, "message": "Not Found"}
        elif e.code == 401:
            logger.warning("Неверный FACEIT_API_KEY (401 Unauthorized)")
            return {"error": 401, "message": "Unauthorized"}
        elif e.code == 429:
            logger.warning("Превышен лимит запросов к FACEIT API (429 Rate Limit)")
            return {"error": 429, "message": "Rate Limit"}
        else:
            logger.warning(f"Ошибка запроса Faceit API ({e.code}): {e.reason}")
            return {"error": e.code, "message": str(e.reason)}
    except Exception as e:
        logger.warning(f"Сетевая ошибка при обращении к Faceit API: {e}")
        return None
    return None


def fetch_player_faceit(steam_id: str, api_key: str = None, force: bool = False) -> dict:
    """
    Загружает и кэширует профиль Faceit для конкретного Steam ID.
    """
    sid = clean_steamid(steam_id)
    cache_file = FACEIT_DIR / f"{sid}.json"
    now = datetime.now()

    # Проверка существующего кэша
    old_data = None
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                old_data = json.load(f)
            cached_at_str = old_data.get("cached_at")
            if cached_at_str and not force:
                cached_at = datetime.fromisoformat(cached_at_str)
                # Если игрок не найден на Faceit, держим кэш 7 дней
                if not old_data.get("found", True):
                    if now - cached_at < timedelta(days=NOT_FOUND_CACHE_DAYS):
                        return old_data
                # Если найден, обновляем раз в 24 часа
                elif now - cached_at < timedelta(hours=CACHE_TTL_HOURS):
                    return old_data
        except Exception:
            pass

    key = api_key or FACEIT_API_KEY
    if not key:
        if old_data:
            return old_data
        return {"found": False, "steam_id": sid, "reason": "no_api_key"}

    # 1. Поиск профиля игрока по CS2 Steam ID
    player_url = f"{FACEIT_API_BASE}/players?game=cs2&game_player_id={sid}"
    p_res = _make_faceit_request(player_url, key)

    if not p_res or p_res.get("error"):
        # Если 404 или ошибка, кэшируем факт отсутствия
        not_found_res = {
            "found": False,
            "steam_id": sid,
            "cached_at": now.isoformat(),
            "reason": p_res.get("message") if p_res else "network_error",
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(not_found_res, f, ensure_ascii=False, indent=2)
        return not_found_res

    player_id = p_res.get("player_id")
    nickname = p_res.get("nickname", "Unknown")
    avatar = p_res.get("avatar") or ""
    faceit_url = (p_res.get("faceit_url") or "").replace("{lang}", "ru") or f"https://www.faceit.com/ru/players/{nickname}"
    country = p_res.get("country", "")

    cs2_game = p_res.get("games", {}).get("cs2", {})
    skill_level = cs2_game.get("skill_level", 1)
    elo = cs2_game.get("faceit_elo", 1000)

    # 2. Пожизненная статистика CS2
    stats_url = f"{FACEIT_API_BASE}/players/{player_id}/stats/cs2"
    stats_res = _make_faceit_request(stats_url, key)
    lifetime = stats_res.get("lifetime", {}) if stats_res and not stats_res.get("error") else {}

    try:
        kd_ratio = round(float(lifetime.get("Average K/D Ratio") or lifetime.get("K/D Ratio") or 1.0), 2)
    except Exception:
        kd_ratio = 1.0

    try:
        win_rate = round(float(str(lifetime.get("Win Rate %", "50")).replace("%", "")), 1)
    except Exception:
        win_rate = 50.0

    try:
        matches_count = int(lifetime.get("Matches", 0))
    except Exception:
        matches_count = 0

    try:
        win_streak = int(lifetime.get("Current Win Streak", 0))
    except Exception:
        win_streak = 0

    try:
        longest_win_streak = int(lifetime.get("Longest Win Streak", 0))
    except Exception:
        longest_win_streak = 0

    try:
        hs_rate = round(float(str(lifetime.get("Average Headshots %") or lifetime.get("Total Headshots %", "0")).replace("%", "")), 1)
    except Exception:
        hs_rate = 0.0

    recent_results = lifetime.get("Recent Results", [])

    # 3. Последние 5 матчей на Faceit
    recent_matches = []
    history_url = f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&limit=5"
    hist_res = _make_faceit_request(history_url, key)
    if hist_res and isinstance(hist_res.get("items"), list):
        for item in hist_res["items"]:
            try:
                m_teams = item.get("teams", {})
                f1 = m_teams.get("faction1", {})
                f2 = m_teams.get("faction2", {})
                # Найти в какой команде был игрок
                player_faction = "faction1" if any(p.get("player_id") == player_id for p in f1.get("roster", [])) else "faction2"
                opp_faction = "faction2" if player_faction == "faction1" else "faction1"

                winner = item.get("results", {}).get("winner")
                is_win = (winner == player_faction)

                score_dict = item.get("results", {}).get("score", {})
                score_f1 = score_dict.get("faction1", 0)
                score_f2 = score_dict.get("faction2", 0)
                my_score = score_f1 if player_faction == "faction1" else score_f2
                opp_score = score_f2 if player_faction == "faction1" else score_f1
                score_str = f"{my_score}:{opp_score}"

                started_at = item.get("started_at", 0)
                match_dt = datetime.fromtimestamp(started_at).strftime("%d.%m.%Y") if started_at else ""

                # Карта
                map_raw = item.get("voting", {}).get("map", {}).get("pick", ["de_mirage"])
                map_name = map_raw[0].replace("de_", "").capitalize() if map_raw else "CS2"

                m_url = f"https://www.faceit.com/ru/cs2/room/{item.get('match_id')}"

                recent_matches.append({
                    "match_id": item.get("match_id"),
                    "date": match_dt,
                    "map": map_name,
                    "score": score_str,
                    "is_win": is_win,
                    "result_badge": "W" if is_win else "L",
                    "match_url": m_url,
                })
            except Exception:
                continue

    # Расчет дельты Elo относительно предыдущего сохраненного кэша
    prev_elo = None
    if old_data and old_data.get("found"):
        prev_elo = old_data.get("elo")
    
    if prev_elo and prev_elo != elo:
        elo_delta = elo - prev_elo
    else:
        elo_delta = old_data.get("elo_delta", 0) if old_data else 0

    # Определение индикатора серии (стрика)
    streak_badge = ""
    if win_streak >= 2:
        streak_badge = f"🔥 {win_streak}W"
    elif recent_results:
        # Посчитать текущий лузстрик с конца списка результатов
        loss_streak = 0
        for r in reversed(recent_results):
            if str(r) == "0":
                loss_streak += 1
            else:
                break
        if loss_streak >= 2:
            streak_badge = f"❄️ {loss_streak}L"

    # Сборка итогового объекта
    faceit_profile = {
        "found": True,
        "steam_id": sid,
        "player_id": player_id,
        "nickname": nickname,
        "avatar": avatar,
        "country": country,
        "faceit_url": faceit_url,
        "skill_level": skill_level,
        "elo": elo,
        "prev_elo": prev_elo or elo,
        "elo_delta": elo_delta,
        "elo_delta_text": f"+{elo_delta}" if elo_delta > 0 else (str(elo_delta) if elo_delta < 0 else "0"),
        "streak_badge": streak_badge,
        "stats": {
            "kd": kd_ratio,
            "win_rate": win_rate,
            "matches": matches_count,
            "win_streak": win_streak,
            "longest_win_streak": longest_win_streak,
            "hs_rate": hs_rate,
        },
        "recent_matches": recent_matches,
        "cached_at": now.isoformat(),
    }

    # Сохранение в кэш
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(faceit_profile, f, ensure_ascii=False, indent=2)

    return faceit_profile


def fetch_all_faceit(force: bool = False) -> dict[str, dict]:
    """
    Синхронизирует статистику Faceit для всех игроков базы players_db.json.
    """
    if not FACEIT_API_KEY:
        logger.info("ℹ️ FACEIT_API_KEY не задан в .env файле. Сбор внешней статистики Faceit пропущен.")
        return {}

    players_db_file = DATA_DIR / "players_db.json"
    if not players_db_file.exists():
        logger.warning(f"Файл {players_db_file} не найден.")
        return {}

    with open(players_db_file, "r", encoding="utf-8") as f:
        players_db = json.load(f)

    # Собираем уникальные clean_steamid
    target_sids = set()
    for raw_sid, pdata in players_db.items():
        csid = clean_steamid(raw_sid)
        if csid in PLAYER_ALIASES:
            csid, _ = PLAYER_ALIASES[csid]
        pname = (pdata.get("name") or "").lower().strip()
        if pname in CANONICAL_PLAYERS:
            csid = CANONICAL_PLAYERS[pname]
        if csid and csid.isdigit() and len(csid) >= 10:
            target_sids.add(csid)

    logger.info(f"Начало синхронизации FACEIT API для {len(target_sids)} игроков...")
    results = {}
    found_count = 0

    for idx, sid in enumerate(sorted(target_sids), 1):
        try:
            p_faceit = fetch_player_faceit(sid, force=force)
            results[sid] = p_faceit
            if p_faceit.get("found"):
                found_count += 1
                logger.info(f"[{idx}/{len(target_sids)}] Faceit: {p_faceit.get('nickname')} (Lvl {p_faceit.get('skill_level')}, Elo {p_faceit.get('elo')})")
            else:
                logger.info(f"[{idx}/{len(target_sids)}] Steam ID {sid} — аккаунт Faceit не найден.")
            time.sleep(0.15)  # Защита от лимитов запросов
        except Exception as e:
            logger.warning(f"Ошибка получения Faceit для {sid}: {e}")

    logger.info(f"Синхронизация Faceit завершена! Найдено активных профилей: {found_count}/{len(target_sids)}")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FACEIT API CS2 Synchronizer")
    parser.add_argument("--force", action="store_true", help="Принудительно обновить весь кэш Faceit")
    parser.add_argument("--steamid", type=str, help="Синхронизировать только один Steam ID")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.steamid:
        res = fetch_player_faceit(args.steamid, force=args.force)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        fetch_all_faceit(force=args.force)
