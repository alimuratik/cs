# scripts/fetch_faceit.py
"""
Модуль синхронизации со статистикой официального FACEIT API v4.
Извлекает реальный Elo, уровень мастерства (1-10), K/D, винрейт, винстрик и историю матчей.
Кэширует результаты локально в data/faceit/{clean_steamid}.json со сроком жизни TTL.
Поддерживает каскадный поиск:
1. Поиск по Steam ID (игра CS2).
2. Fallback: поиск по Steam ID (игра CS:GO для аккаунтов, созданных до CS2).
3. Fallback: поиск по маппингу FACEIT_CUSTOM_PLAYERS (никнейм / ссылка).
4. Fallback: автоматический поиск по игровому никнейму (включая слитное написание).
"""

import os
import sys
import json
import time
import re
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
import logging

# Гарантия импорта из корня проекта при прямом вызове
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.config import (
    FACEIT_API_KEY,
    FACEIT_DIR,
    DATA_DIR,
    clean_steamid,
    CANONICAL_PLAYERS,
    PLAYER_ALIASES,
    FACEIT_CUSTOM_PLAYERS,
)

logger = logging.getLogger(__name__)

FACEIT_API_BASE = "https://open.faceit.com/data/v4"
CACHE_TTL_HOURS = 24
NOT_FOUND_CACHE_DAYS = 7
LOOKUP_VERSION = 2  # Версия логики поиска для сброса устаревших отрицательных кэшей

# Диапазоны ELO для уровней Faceit CS2
FACEIT_LEVEL_BRACKETS = {
    1: (1, 500),
    2: (501, 750),
    3: (751, 900),
    4: (901, 1050),
    5: (1051, 1200),
    6: (1201, 1350),
    7: (1351, 1530),
    8: (1531, 1750),
    9: (1751, 2000),
    10: (2001, 3000),
}


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


def fetch_player_faceit(steam_id: str, player_name: str = "", api_key: str = None, force: bool = False) -> dict:
    """
    Загружает и кэширует профиль Faceit для конкретного Steam ID с многоуровневым поиском.
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
                # Если найден, обновляем раз в 24 часа
                if old_data.get("found", False):
                    if now - cached_at < timedelta(hours=CACHE_TTL_HOURS):
                        return old_data
                # Если не найден, но проверялся новой версией поиска, держим кэш 7 дней
                elif old_data.get("lookup_version") == LOOKUP_VERSION:
                    if now - cached_at < timedelta(days=NOT_FOUND_CACHE_DAYS):
                        return old_data
        except Exception:
            pass

    key = api_key or FACEIT_API_KEY
    if not key:
        if old_data:
            return old_data
        return {"found": False, "steam_id": sid, "reason": "no_api_key"}

    p_res = None
    matched_by = "none"

    # 1. Шаг 1: Поиск по CS2 Steam ID
    if sid:
        player_url_cs2 = f"{FACEIT_API_BASE}/players?game=cs2&game_player_id={sid}"
        res = _make_faceit_request(player_url_cs2, key)
        if res and not res.get("error"):
            p_res = res
            matched_by = "cs2_steamid"

    # 2. Шаг 2: Fallback — поиск по CS:GO Steam ID (профили, зарегистрированные в эру CS:GO)
    if not p_res and sid:
        player_url_csgo = f"{FACEIT_API_BASE}/players?game=csgo&game_player_id={sid}"
        res = _make_faceit_request(player_url_csgo, key)
        if res and not res.get("error"):
            p_res = res
            matched_by = "csgo_steamid"

    # 3. Шаг 3: Fallback — поиск по пользовательскому маппингу FACEIT_CUSTOM_PLAYERS
    if not p_res:
        clean_name = (player_name or "").strip().lower()
        custom_target = FACEIT_CUSTOM_PLAYERS.get(sid) or FACEIT_CUSTOM_PLAYERS.get(clean_name)
        if custom_target:
            # Извлекаем никнейм из строки или ссылки (например https://www.faceit.com/ru/players/mbaliyev)
            custom_nick = custom_target.strip().rstrip("/").split("/")[-1]
            custom_url = f"{FACEIT_API_BASE}/players?nickname={urllib.parse.quote(custom_nick)}"
            res = _make_faceit_request(custom_url, key)
            if res and not res.get("error"):
                p_res = res
                matched_by = f"custom_mapping({custom_nick})"

    # 4. Шаг 4: Fallback — автоматический поиск по игровому никнейму
    if not p_res and player_name:
        nick_clean = player_name.strip()
        # Проверяем никнейм напрямую, если в нем нет пробелов и спецсимволов пути
        if len(nick_clean) >= 3 and not any(c in nick_clean for c in " \t/\\"):
            nick_url = f"{FACEIT_API_BASE}/players?nickname={urllib.parse.quote(nick_clean)}"
            res = _make_faceit_request(nick_url, key)
            if res and not res.get("error"):
                p_res = res
                matched_by = f"nickname({nick_clean})"

        # Если в нике были пробелы (например "c kaifom" -> "ckaifom" или "Resone West" -> "ResoneWest")
        if not p_res and (" " in nick_clean or "-" in nick_clean or "_" in nick_clean):
            compressed_nick = re.sub(r'[^a-zA-Z0-9_\-]', '', nick_clean)
            if len(compressed_nick) >= 3 and compressed_nick.lower() != nick_clean.lower():
                nick_url = f"{FACEIT_API_BASE}/players?nickname={urllib.parse.quote(compressed_nick)}"
                res = _make_faceit_request(nick_url, key)
                if res and not res.get("error"):
                    p_res = res
                    matched_by = f"compressed_nickname({compressed_nick})"

    # Если профиль не найден ни по одному из критериев
    if not p_res or p_res.get("error"):
        not_found_res = {
            "found": False,
            "steam_id": sid,
            "player_name": player_name,
            "cached_at": now.isoformat(),
            "lookup_version": LOOKUP_VERSION,
            "reason": p_res.get("message") if p_res else "not_found",
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(not_found_res, f, ensure_ascii=False, indent=2)
        return not_found_res

    # Профиль успешно найден!
    player_id = p_res.get("player_id")
    nickname = p_res.get("nickname", player_name or "Unknown")
    avatar = p_res.get("avatar") or ""
    faceit_url = (p_res.get("faceit_url") or "").replace("{lang}", "ru") or f"https://www.faceit.com/ru/players/{nickname}"
    country = p_res.get("country", "")

    # Извлечение уровня и Elo с поддержкой CS2 и CS:GO
    games = p_res.get("games", {})
    cs2_g = games.get("cs2", {})
    csgo_g = games.get("csgo", {})
    real_faceit_steamid = clean_steamid(cs2_g.get("game_player_id") or csgo_g.get("game_player_id"))
    elo = cs2_g.get("faceit_elo") or csgo_g.get("faceit_elo") or 1000
    skill_level = cs2_g.get("skill_level") or csgo_g.get("skill_level") or 1

    # 2. Пожизненная статистика (приоритет CS2, fallback на CS:GO)
    stats_url = f"{FACEIT_API_BASE}/players/{player_id}/stats/cs2"
    stats_res = _make_faceit_request(stats_url, key)
    if not stats_res or stats_res.get("error"):
        stats_url = f"{FACEIT_API_BASE}/players/{player_id}/stats/csgo"
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

    # 3. Последние 5 матчей на Faceit (приоритет CS2, fallback на CS:GO)
    recent_matches = []
    history_url = f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&limit=5"
    hist_res = _make_faceit_request(history_url, key)
    if not hist_res or not hist_res.get("items"):
        history_url = f"{FACEIT_API_BASE}/players/{player_id}/history?game=csgo&limit=5"
        hist_res = _make_faceit_request(history_url, key)

    if hist_res and isinstance(hist_res.get("items"), list):
        for item in hist_res["items"]:
            try:
                m_teams = item.get("teams", {})
                f1 = m_teams.get("faction1", {})
                f2 = m_teams.get("faction2", {})
                player_faction = "faction1" if any(p.get("player_id") == player_id for p in f1.get("roster", [])) else "faction2"

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

                map_raw = item.get("voting", {}).get("map", {}).get("pick", ["de_mirage"])
                map_name = map_raw[0].replace("de_", "").capitalize() if map_raw else "CS2"

                game_type = item.get("game", "cs2")
                m_url = f"https://www.faceit.com/ru/{game_type}/room/{item.get('match_id')}"

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

    # Расчет дельты Elo относительно предыдущего кэша
    prev_elo = None
    if old_data and old_data.get("found"):
        prev_elo = old_data.get("elo")

    if prev_elo and prev_elo != elo:
        elo_delta = elo - prev_elo
    else:
        elo_delta = old_data.get("elo_delta", 0) if old_data else 0

    # Расчет прогресса до следующего уровня Faceit
    lvl = int(skill_level or 1)
    min_elo, max_elo = FACEIT_LEVEL_BRACKETS.get(lvl, (1000, 1200))
    if lvl < 10:
        next_level = lvl + 1
        next_level_elo = max_elo + 1
        elo_to_next = max(0, next_level_elo - elo)
        span = max(1, max_elo - min_elo)
        progress_percent = max(0.0, min(100.0, round(((elo - min_elo) / span) * 100, 1)))
    else:
        next_level = 10
        next_level_elo = None
        elo_to_next = 0
        progress_percent = 100.0

    # Извлечение статистики по картам из Faceit API (segments)
    faceit_map_stats = {}
    for seg in (stats_res.get("segments") or []):
        seg_label = (seg.get("label") or "").lower()
        if "de_" in seg_label or seg.get("type") in ("duplicated_maps", "Map", "map"):
            map_key = seg_label.replace("de_", "").strip()
            s_data = seg.get("stats", {})
            try:
                m_cnt = int(s_data.get("Matches", 0))
                m_wr = round(float(str(s_data.get("Win Rate %", "0")).replace("%", "")), 1)
                m_kd = round(float(s_data.get("Average K/D Ratio", "1.0")), 2)
                faceit_map_stats[map_key] = {
                    "matches": m_cnt,
                    "win_rate": m_wr,
                    "kd": m_kd
                }
            except Exception:
                continue

    # Анализ соревновательного тренда формы и серии (стрика) — без снежинок
    streak_badge = ""
    trend_type = "stable"
    trend_icon = "●"
    trend_label = "Стабильно"
    trend_color = "slate"

    if win_streak >= 2:
        streak_badge = f"▲ {win_streak}W"
        trend_type = "up"
        trend_icon = "▲"
        trend_label = "На подъёме"
        trend_color = "emerald"
    elif recent_results:
        loss_streak = 0
        for r in reversed(recent_results):
            if str(r) == "0":
                loss_streak += 1
            else:
                break
        if loss_streak >= 2:
            streak_badge = f"▼ {loss_streak}L"
            trend_type = "down"
            trend_icon = "▼"
            trend_label = "Спад"
            trend_color = "rose"
        elif win_streak == 1:
            streak_badge = "▲ 1W"
            trend_type = "stable"
            trend_icon = "●"
            trend_label = "Стабильно"
            trend_color = "slate"
    elif win_streak == 1:
        streak_badge = "▲ 1W"

    # Сборка итогового объекта Faceit
    faceit_profile = {
        "found": True,
        "steam_id": sid,
        "player_id": player_id,
        "nickname": nickname,
        "matched_by": matched_by,
        "avatar": avatar,
        "country": country,
        "faceit_url": faceit_url,
        "skill_level": skill_level,
        "elo": elo,
        "prev_elo": prev_elo or elo,
        "elo_delta": elo_delta,
        "elo_delta_text": f"+{elo_delta}" if elo_delta > 0 else (str(elo_delta) if elo_delta < 0 else "0"),
        "streak_badge": streak_badge,
        "trend_type": trend_type,
        "trend_icon": trend_icon,
        "trend_label": trend_label,
        "trend_color": trend_color,
        "next_level": next_level,
        "next_level_elo": next_level_elo,
        "elo_to_next": elo_to_next,
        "progress_percent": progress_percent,
        "bracket_min": min_elo,
        "bracket_max": max_elo,
        "stats": {
            "kd": kd_ratio,
            "win_rate": win_rate,
            "matches": matches_count,
            "win_streak": win_streak,
            "longest_win_streak": longest_win_streak,
            "hs_rate": hs_rate,
        },
        "map_stats": faceit_map_stats,
        "recent_matches": recent_matches,
        "cached_at": now.isoformat(),
        "lookup_version": LOOKUP_VERSION,
    }

    # Сохранение в локальный кэш
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(faceit_profile, f, ensure_ascii=False, indent=2)

    # Если реальный Steam ID на Faceit отличается от запрошенного sid (например, float-округление)
    if real_faceit_steamid and real_faceit_steamid != sid:
        alt_cache_file = FACEIT_DIR / f"{real_faceit_steamid}.json"
        try:
            with open(alt_cache_file, "w", encoding="utf-8") as f:
                json.dump(faceit_profile, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # Дублируем для известных вариантов округления (например ...961 <-> ...968)
    if sid in ("76561198254267961", "76561198254267968") or real_faceit_steamid in ("76561198254267961", "76561198254267968"):
        for variant in ["76561198254267961", "76561198254267968"]:
            try:
                with open(FACEIT_DIR / f"{variant}.json", "w", encoding="utf-8") as f:
                    json.dump(faceit_profile, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

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

    # Собираем уникальные clean_steamid и актуальные имена игроков
    target_players = {}  # csid -> pname
    for raw_sid, pdata in players_db.items():
        csid = clean_steamid(raw_sid)
        pname = pdata.get("name", "")
        if csid in PLAYER_ALIASES:
            csid, alias_name = PLAYER_ALIASES[csid]
            if not pname:
                pname = alias_name
        pname_lower = (pname or "").lower().strip()
        if pname_lower in CANONICAL_PLAYERS:
            csid = CANONICAL_PLAYERS[pname_lower]
        if csid and csid.isdigit() and len(csid) >= 10:
            if csid not in target_players or (not target_players[csid] and pname):
                target_players[csid] = pname

    logger.info(f"Начало синхронизации FACEIT API для {len(target_players)} игроков...")
    results = {}
    found_count = 0

    for idx, (sid, pname) in enumerate(sorted(target_players.items()), 1):
        try:
            p_faceit = fetch_player_faceit(sid, player_name=pname, force=force)
            results[sid] = p_faceit
            display_title = pname or sid
            if p_faceit.get("found"):
                found_count += 1
                matched = p_faceit.get("matched_by", "direct")
                logger.info(
                    f"[{idx}/{len(target_players)}] Faceit: {p_faceit.get('nickname')} "
                    f"(Lvl {p_faceit.get('skill_level')}, Elo {p_faceit.get('elo')}) "
                    f"[Игрок: {display_title}, поиск: {matched}]"
                )
            else:
                logger.info(f"[{idx}/{len(target_players)}] {display_title} — профиль Faceit не найден.")
            time.sleep(0.15)  # Защита от лимитов запросов
        except Exception as e:
            logger.warning(f"Ошибка получения Faceit для {pname or sid}: {e}")

    logger.info(f"Синхронизация Faceit завершена! Найдено активных профилей: {found_count}/{len(target_players)}")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FACEIT API CS2 Synchronizer")
    parser.add_argument("--force", action="store_true", help="Принудительно обновить весь кэш Faceit")
    parser.add_argument("--steamid", type=str, help="Синхронизировать только один Steam ID")
    parser.add_argument("--name", type=str, default="", help="Имя игрока для поиска по никнейму")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.steamid:
        res = fetch_player_faceit(args.steamid, player_name=args.name, force=args.force)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        fetch_all_faceit(force=args.force)
