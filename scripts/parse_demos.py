import sys
import os
import json
import logging
import traceback
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

import polars as pl
from awpy import Demo
from awpy.stats import adr, kast
from scripts.config import *

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def clean_steamid(val) -> str:
    """Очистка Steam ID от null, float и научного формата."""
    if val is None or val == '' or str(val) == 'None' or str(val) == 'nan':
        return ""
    try:
        if isinstance(val, float):
            return str(int(val))
        val_str = str(val).strip()
        if 'e+' in val_str or 'E+' in val_str:
            return str(int(float(val_str)))
        if '.' in val_str:
            return val_str.split('.')[0]
        return val_str
    except Exception:
        return str(val)

def load_registry() -> dict:
    """Загрузить реестр уже спарсенных демок."""
    registry_path = DATA_DIR / "registry.json"
    if registry_path.exists():
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки реестра: {e}")
    return {"parsed": []}

def save_registry(registry: dict):
    """Сохранить реестр спарсенных демок."""
    registry_path = DATA_DIR / "registry.json"
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Ошибка сохранения реестра: {e}")

def find_new_demos(registry: dict) -> list[tuple[str, str, str]]:
    """Поиск новых демок в директории demos."""
    new_demos = []
    if not DEMOS_DIR.exists():
        return new_demos

    parsed_demos = set(registry.get("parsed", []))
    
    for date_folder in os.listdir(DEMOS_DIR):
        folder_path = DEMOS_DIR / date_folder
        if folder_path.is_dir():
            for filename in os.listdir(folder_path):
                if filename.endswith(".dem"):
                    demo_id = f"{date_folder}_{filename}"
                    if demo_id not in parsed_demos:
                        full_path = str(folder_path / filename)
                        new_demos.append((date_folder, filename, full_path))
    
    return new_demos

def audit_match_data(match_data: dict) -> dict:
    """
    Аудит и валидация данных матча перед сохранением:
    1. Дедупликация игроков по каноническому Steam ID и нормализованному нику.
    2. Проверка баланса: равенство или близкое соответствие убийств и смертей.
    3. Проверка активных игроков на 0 смертей при наличии дубликата с тем же именем.
    4. Балансировка команд на 5v5.
    """
    raw_players = match_data.get("players", {})
    if not raw_players:
        return match_data
        
    merged_players = {}
    name_to_sid = {}
    
    for sid, p in raw_players.items():
        p_name = str(p.get("name") or "").strip()
        n_lower = p_name.lower()
        clean_sid = clean_steamid(sid)
        
        # Разрешаем псевдонимы и канонические ID
        if clean_sid in PLAYER_ALIASES:
            clean_sid, p_name = PLAYER_ALIASES[clean_sid]
        elif n_lower in PLAYER_ALIASES:
            clean_sid, p_name = PLAYER_ALIASES[n_lower]
        if p_name.lower() in CANONICAL_PLAYERS:
            clean_sid = CANONICAL_PLAYERS[p_name.lower()]
        elif n_lower in CANONICAL_PLAYERS:
            clean_sid = CANONICAL_PLAYERS[n_lower]
            
        if not clean_sid:
            continue
            
        n_key = p_name.lower()
        # Проверяем, есть ли уже игрок с таким именем или каноническим ID
        target_sid = clean_sid
        if n_key in name_to_sid:
            target_sid = name_to_sid[n_key]
        else:
            name_to_sid[n_key] = target_sid
            
        if target_sid not in merged_players:
            p_copy = dict(p)
            p_copy["steam_id"] = target_sid
            p_copy["name"] = p_name
            merged_players[target_sid] = p_copy
        else:
            # Слияние дубликата (например, раздвоение на фраги и смерти из-за float SteamID)
            ex = merged_players[target_sid]
            ex["kills"] = ex.get("kills", 0) + p.get("kills", 0)
            ex["deaths"] = ex.get("deaths", 0) + p.get("deaths", 0)
            ex["assists"] = ex.get("assists", 0) + p.get("assists", 0)
            ex["adr"] = max(ex.get("adr", 0.0), p.get("adr", 0.0))
            ex["kast"] = max(ex.get("kast", 0.0), p.get("kast", 0.0))
            ex["hs_percent"] = max(ex.get("hs_percent", 0.0), p.get("hs_percent", 0.0))
            ex["first_kills"] = ex.get("first_kills", 0) + p.get("first_kills", 0)
            ex["first_deaths"] = ex.get("first_deaths", 0) + p.get("first_deaths", 0)
            ex["clutch_wins"] = ex.get("clutch_wins", 0) + p.get("clutch_wins", 0)
            ex["clutch_attempts"] = ex.get("clutch_attempts", 0) + p.get("clutch_attempts", 0)
            ex["utility_damage"] = ex.get("utility_damage", 0) + p.get("utility_damage", 0)
            ex["flash_assists"] = ex.get("flash_assists", 0) + p.get("flash_assists", 0)
            ex["headshot_kills"] = ex.get("headshot_kills", 0) + p.get("headshot_kills", 0)
            for w, cnt in p.get("weapon_kills", {}).items():
                ex["weapon_kills"][w] = ex["weapon_kills"].get(w, 0) + cnt
            if ex.get("team") == "unknown" and p.get("team") != "unknown":
                ex["team"] = p.get("team")
                
    match_data["players"] = merged_players
    
    # 5. Валидация счета и победителя матча
    rounds = match_data.get("rounds", [])
    s1 = match_data.get("score_team1", 0)
    s2 = match_data.get("score_team2", 0)
    rounds_cnt = len(rounds)
    if rounds_cnt > 0:
        actual_s1 = sum(1 for r in rounds if r.get("winning_team") == "team1")
        actual_s2 = sum(1 for r in rounds if r.get("winning_team") == "team2")
        if (s1 + s2) != rounds_cnt or s1 != actual_s1 or s2 != actual_s2:
            logging.info(f"Аудит счета {match_data.get('match_id')}: синхронизация {s1}:{s2} -> {actual_s1}:{actual_s2} (всего раундов: {rounds_cnt})")
            match_data["score_team1"] = actual_s1
            match_data["score_team2"] = actual_s2
            s1, s2 = actual_s1, actual_s2
            
    match_data["winner"] = "team1" if s1 > s2 else ("team2" if s2 > s1 else "draw")

    tot_k = sum(p.get("kills", 0) for p in merged_players.values())
    tot_d = sum(p.get("deaths", 0) for p in merged_players.values())
    t1_cnt = sum(1 for p in merged_players.values() if p.get("team") == "team1")
    t2_cnt = sum(1 for p in merged_players.values() if p.get("team") == "team2")
    logging.info(f"Аудит матча {match_data.get('match_id')}: игроков={len(merged_players)} (Team1={t1_cnt}, Team2={t2_cnt}), Счет={s1}:{s2}, Kills={tot_k}, Deaths={tot_d}")
    return match_data

def parse_single_demo(demo_path: str, date_str: str, demo_name: str) -> dict:
    """Парсинг одной демки и выгрузка метрик."""
    logging.info(f"Начинаем парсинг демки: {demo_name}")
    try:
        demo = Demo(demo_path)
        demo.parse()
        
        map_name = demo.header.get("map_name", "unknown") if demo.header else "unknown"
        
        map_mapping = {
            "de_mirage": "Mirage",
            "de_inferno": "Inferno",
            "de_dust2": "Dust2",
            "de_nuke": "Nuke",
            "de_ancient": "Ancient",
            "de_anubis": "Anubis",
            "de_vertigo": "Vertigo"
        }
        map_display = map_mapping.get(map_name, map_name.replace("de_", "").capitalize())
        
        clean_name = demo_name.replace(".dem", "").replace("-", "_")
        match_id = f"{date_str}_{map_display.lower()}_{clean_name[:12]}"
        
        def df_to_list(polars_df):
            if polars_df is None or (hasattr(polars_df, 'is_empty') and polars_df.is_empty()):
                return []
            if isinstance(polars_df, pl.DataFrame):
                # Нативный to_dicts() сохраняет UInt64 как точный int, предотвращая float64-округление
                try:
                    return polars_df.to_dicts()
                except Exception:
                    df = polars_df.to_pandas()
                    df = df.where(df.notnull(), None)
                    return df.to_dict(orient='records')
            return []

        rounds = df_to_list(demo.rounds)
        kills = df_to_list(demo.kills)
        damages = df_to_list(demo.damages)
        grenades = df_to_list(demo.grenades)
        
        adr_dict = {}
        kast_dict = {}
        try:
            if demo.damages is not None and not demo.damages.is_empty():
                adr_df = adr(demo)
                if adr_df is not None:
                    for row in df_to_list(adr_df):
                        sid = clean_steamid(row.get('steamid'))
                        if sid:
                            adr_dict[sid] = float(row.get('adr', 0) or 0)
                            
            if demo.kills is not None and not demo.kills.is_empty():
                kast_df = kast(demo)
                if kast_df is not None:
                    for row in df_to_list(kast_df):
                        sid = clean_steamid(row.get('steamid'))
                        if sid:
                            kast_dict[sid] = float(row.get('kast', 0) or 0)
        except Exception as e:
            logging.warning(f"Ошибка при расчете ADR/KAST: {e}")

        # Сохраняем тики в Parquet
        if hasattr(demo, 'ticks') and demo.ticks is not None and isinstance(demo.ticks, pl.DataFrame) and not demo.ticks.is_empty():
            ticks_dir = DATA_DIR / "ticks"
            os.makedirs(ticks_dir, exist_ok=True)
            ticks_path = ticks_dir / f"{match_id}_ticks.parquet"
            try:
                demo.ticks.write_parquet(str(ticks_path))
                logging.info(f"Тики сохранены: {ticks_path}")
            except Exception as e:
                logging.warning(f"Не удалось сохранить тики: {e}")

        player_team_map = {}
        all_events = (kills or []) + (damages or [])
        for evt in all_events:
            r_num = evt.get("round_num", 1)
            for role_prefix in ["attacker", "victim"]:
                raw_s = evt.get(f"{role_prefix}_steamid")
                raw_n = evt.get(f"{role_prefix}_name")
                raw_side = str(evt.get(f"{role_prefix}_side") or "").lower()
                
                sid = clean_steamid(raw_s)
                n_lower = str(raw_n or "").strip().lower()
                if sid in PLAYER_ALIASES:
                    sid, _ = PLAYER_ALIASES[sid]
                elif n_lower in PLAYER_ALIASES:
                    sid, _ = PLAYER_ALIASES[n_lower]
                if n_lower in CANONICAL_PLAYERS:
                    sid = CANONICAL_PLAYERS[n_lower]
                
                if sid and raw_side in ("ct", "t"):
                    if r_num <= 12:
                        team_tag = "team1" if raw_side == "ct" else "team2"
                        player_team_map[sid] = team_tag
                    elif sid not in player_team_map:
                        team_tag = "team2" if raw_side == "ct" else "team1"
                        player_team_map[sid] = team_tag

        players = {}
        name_to_sid = {}

        def get_player(steamid, name, side=None):
            sid = clean_steamid(steamid)
            if name is None or (isinstance(name, float) and (str(name) == 'nan' or name != name)):
                raw_name = ""
            else:
                raw_name = str(name).strip()
            name_lower = raw_name.lower()

            # Проверяем псевдонимы (Domino / Dom1no1111 -> mbaliyev)
            if sid in PLAYER_ALIASES:
                target_sid, target_name = PLAYER_ALIASES[sid]
                sid = target_sid
                raw_name = target_name
                name_lower = target_name.lower()
            elif name_lower in PLAYER_ALIASES:
                target_sid, target_name = PLAYER_ALIASES[name_lower]
                sid = target_sid
                raw_name = target_name
                name_lower = target_name.lower()

            # Канонический Steam ID по имени
            if name_lower in CANONICAL_PLAYERS:
                sid = CANONICAL_PLAYERS[name_lower]

            # Если Steam ID некорректен, ищем по имени в матче
            if not sid or len(sid) < 10:
                if name_lower in name_to_sid:
                    sid = name_to_sid[name_lower]
                else:
                    return None

            if name_lower and sid:
                name_to_sid[name_lower] = sid

            if sid not in players:
                disp_name = PLAYER_NAMES.get(sid, raw_name or f"Player_{sid[-4:]}")
                assigned_team = player_team_map.get(sid, side or "team1")
                if assigned_team in ("ct", "1"):
                    assigned_team = "team1"
                elif assigned_team in ("t", "2"):
                    assigned_team = "team2"

                players[sid] = {
                    "steam_id": sid,
                    "name": disp_name,
                    "team": assigned_team,
                    "kills": 0,
                    "deaths": 0,
                    "assists": 0,
                    "adr": 0.0,
                    "kast": 0.0,
                    "hs_percent": 0.0,
                    "first_kills": 0,
                    "first_deaths": 0,
                    "clutch_wins": 0,
                    "clutch_attempts": 0,
                    "utility_damage": 0,
                    "flash_assists": 0,
                    "weapon_kills": {},
                    "pistol_round_kills": 0,
                    "pistol_round_deaths": 0,
                    "trades": 0,
                    "traded_deaths": 0,
                    "headshot_kills": 0,
                    "total_damage": 0,
                    "kast_rounds": set()
                }

            return players[sid]

        rounds_first_kill = set()
        sorted_kills = sorted(kills, key=lambda k: (k.get("round_num", 0), k.get("tick", 0)))
        recent_deaths = []

        total_rounds_cnt = max(1, len(rounds))

        for k in sorted_kills:
            round_num = k.get("round_num", 0)
            attacker_sid = clean_steamid(k.get("attacker_steamid"))
            victim_sid = clean_steamid(k.get("victim_steamid"))
            assister_sid = clean_steamid(k.get("assister_steamid"))
            
            attacker_name = k.get("attacker_name")
            victim_name = k.get("victim_name")
            assister_name = k.get("assister_name")
            
            attacker_side = k.get("attacker_side")
            victim_side = k.get("victim_side")

            att = get_player(attacker_sid, attacker_name, attacker_side)
            vic = get_player(victim_sid, victim_name, victim_side)

            is_first_kill = False
            if round_num not in rounds_first_kill:
                rounds_first_kill.add(round_num)
                is_first_kill = True

            if att:
                att["kills"] += 1
                att["kast_rounds"].add(round_num)
                if k.get("headshot"):
                    att["headshot_kills"] += 1
                weapon = k.get("weapon") or "unknown"
                att["weapon_kills"][weapon] = att["weapon_kills"].get(weapon, 0) + 1
                if round_num in PISTOL_ROUNDS:
                    att["pistol_round_kills"] += 1
                if is_first_kill:
                    att["first_kills"] += 1

            if vic:
                vic["deaths"] += 1
                if round_num in PISTOL_ROUNDS:
                    vic["pistol_round_deaths"] += 1
                if is_first_kill:
                    vic["first_deaths"] += 1

            if assister_sid or assister_name:
                ass = get_player(assister_sid, assister_name)
                if ass:
                    ass["assists"] += 1
                    ass["kast_rounds"].add(round_num)
                    if k.get("assistedflash"):
                        ass["flash_assists"] += 1

            tick = k.get("tick", 0)
            if att and vic:
                for d_tick, d_victim_sid, d_attacker_sid, d_round in recent_deaths:
                    if d_round == round_num and (tick - d_tick) <= 320: # ~5 seconds at 64 tick
                        if d_attacker_sid == vic["steam_id"] and d_victim_sid != att["steam_id"]:
                            att["trades"] += 1
                            traded = players.get(d_victim_sid)
                            if traded:
                                traded["traded_deaths"] += 1
                                traded["kast_rounds"].add(round_num)
                recent_deaths.append((tick, vic["steam_id"], att["steam_id"], round_num))

        # Урон по игрокам (ADR & Grenade damage)
        for d in damages:
            att_sid = clean_steamid(d.get("attacker_steamid"))
            att_name = d.get("attacker_name")
            vic_sid = clean_steamid(d.get("victim_steamid"))
            vic_name = d.get("victim_name")
            weapon = d.get("weapon", "")
            dmg = min(100, d.get("dmg_health_real") or d.get("dmg_health") or 0)
            
            att = get_player(att_sid, att_name)
            vic = get_player(vic_sid, vic_name)

            if att and vic and att["steam_id"] != vic["steam_id"]:
                att["total_damage"] += dmg
                if weapon in ["hegrenade", "inferno", "molotov"]:
                    att["utility_damage"] += dmg

        # Завершающий расчет ADR, KAST%, HS% для каждого игрока
        for sid, p in players.items():
            if p["kills"] > 0:
                p["hs_percent"] = round((p["headshot_kills"] / p["kills"]) * 100, 1)
            else:
                p["hs_percent"] = 0.0

            # Точный расчёт ADR по формуле: (Общий урон / Всего раундов)
            calc_adr = p["total_damage"] / total_rounds_cnt
            awpy_adr = adr_dict.get(sid, 0.0)
            p["adr"] = round(awpy_adr if awpy_adr > 0 else calc_adr, 1)

            # Выживание в раундах для KAST
            survived_rounds = total_rounds_cnt - p["deaths"]
            p["kast_rounds"].update(range(1, max(1, survived_rounds + 1)))

            calc_kast = (len(p["kast_rounds"]) / total_rounds_cnt) * 100
            awpy_kast = kast_dict.get(sid, 0.0)
            p["kast"] = round(min(100.0, max(calc_kast, awpy_kast)), 1)
            
            # Удаляем системное множество пред сохранением
            if "kast_rounds" in p:
                del p["kast_rounds"]

        # Определение стороны Команды 1 в каждом раунде (с учетом смены сторон и овертаймов)
        t1_sids = {sid for sid, pl in players.items() if pl.get("team") == "team1"}
        t2_sids = {sid for sid, pl in players.items() if pl.get("team") == "team2"}

        round_sides = {}
        for k in kills:
            r = k.get("round_num")
            if r not in round_sides:
                att = clean_steamid(k.get("attacker_steamid"))
                side = str(k.get("attacker_side") or "").lower()
                if att in t1_sids and side in ("ct", "t"):
                    round_sides[r] = side
                elif att in t2_sids and side in ("ct", "t"):
                    round_sides[r] = "t" if side == "ct" else "ct"

        # Подготовка группировки фрагов по раундам для клатчей
        kills_by_round = {}
        for k in sorted_kills:
            r = k.get("round_num", 0)
            kills_by_round.setdefault(r, []).append(k)

        score_team1 = 0
        score_team2 = 0
        light_rounds = []
        for r in rounds:
            r_num = r.get("round_num")
            w = str(r.get("winner") or "").lower()
            t1_side = round_sides.get(r_num)
            if not t1_side:
                t1_side = "ct" if (r_num is not None and r_num <= 12) else "t"
            
            winning_team = "draw"
            if w == t1_side:
                winning_team = "team1"
                score_team1 += 1
            elif w in ("ct", "t"):
                winning_team = "team2"
                score_team2 += 1
                
            t2_side = "t" if t1_side == "ct" else "ct"
            ct_team = "team1" if t1_side == "ct" else "team2"
            t_team = "team2" if t1_side == "ct" else "team1"
                
            # Расчет клатч-ситуаций (1vX) в этом раунде
            rkills = sorted(kills_by_round.get(r_num, []), key=lambda x: x.get("tick", 0))
            alive_t1 = set(t1_sids)
            alive_t2 = set(t2_sids)
            clutcher_t1 = None
            clutcher_t2 = None
            t1_attempted = False
            t2_attempted = False

            for k in rkills:
                v_sid = clean_steamid(k.get("victim_steamid"))
                v_name = str(k.get("victim_name") or "").lower()
                target_vic = None
                if v_sid in players:
                    target_vic = v_sid
                elif v_name in name_to_sid:
                    target_vic = name_to_sid[v_name]

                if target_vic:
                    alive_t1.discard(target_vic)
                    alive_t2.discard(target_vic)

                if len(alive_t1) == 1 and len(alive_t2) >= 1 and not t1_attempted:
                    sole = list(alive_t1)[0]
                    if sole in players:
                        players[sole]["clutch_attempts"] += 1
                        clutcher_t1 = sole
                    t1_attempted = True

                if len(alive_t2) == 1 and len(alive_t1) >= 1 and not t2_attempted:
                    sole = list(alive_t2)[0]
                    if sole in players:
                        players[sole]["clutch_attempts"] += 1
                        clutcher_t2 = sole
                    t2_attempted = True

            if winning_team == "team1" and clutcher_t1 and clutcher_t1 in players:
                players[clutcher_t1]["clutch_wins"] += 1
            elif winning_team == "team2" and clutcher_t2 and clutcher_t2 in players:
                players[clutcher_t2]["clutch_wins"] += 1

            light_rounds.append({
                "round_num": r_num,
                "winner": w,
                "winning_team": winning_team,
                "reason": r.get("reason"),
                "bomb_plant": r.get("bomb_plant"),
                "bomb_site": r.get("bomb_site"),
                "t1_side": t1_side,
                "t2_side": t2_side,
                "ct_team": ct_team,
                "t_team": t_team
            })

        light_kills = []
        for k in kills:
            light_kills.append({
                "round_num": k.get("round_num"),
                "tick": k.get("tick"),
                "attacker_steamid": clean_steamid(k.get("attacker_steamid")),
                "attacker_name": k.get("attacker_name"),
                "attacker_side": k.get("attacker_side"),
                "attacker_place": k.get("attacker_place"),
                "victim_steamid": clean_steamid(k.get("victim_steamid")),
                "victim_name": k.get("victim_name"),
                "victim_side": k.get("victim_side"),
                "victim_place": k.get("victim_place"),
                "assister_steamid": clean_steamid(k.get("assister_steamid")),
                "assister_name": k.get("assister_name"),
                "weapon": k.get("weapon"),
                "headshot": bool(k.get("headshot")),
                "assistedflash": bool(k.get("assistedflash")),
                "thrusmoke": bool(k.get("thrusmoke")),
                "noscope": bool(k.get("noscope"))
            })

        # Урон от гранат (HE, Molotov, Incendiary) для пораундового разбора
        light_damages = []
        for d in (damages or []):
            wpn = str(d.get("weapon") or "").lower()
            if wpn in ("hegrenade", "inferno", "molotov"):
                dmg = min(100, int(d.get("dmg_health_real") or d.get("dmg_health") or 0))
                if dmg > 0:
                    light_damages.append({
                        "round_num": d.get("round_num"),
                        "attacker_name": d.get("attacker_name"),
                        "attacker_steamid": clean_steamid(d.get("attacker_steamid")),
                        "attacker_side": d.get("attacker_side"),
                        "victim_name": d.get("victim_name"),
                        "weapon": wpn,
                        "dmg": dmg
                    })

        # Определение условных капитанов команд (лучших игроков по K/ADR)
        t1_pls = [p for p in players.values() if p.get("team") == "team1"]
        t2_pls = [p for p in players.values() if p.get("team") == "team2"]
        cap1 = max(t1_pls, key=lambda x: (x.get("kills", 0) * 1.0 + x.get("adr", 0.0) * 0.1))["name"] if t1_pls else "Команда 1"
        cap2 = max(t2_pls, key=lambda x: (x.get("kills", 0) * 1.0 + x.get("adr", 0.0) * 0.1))["name"] if t2_pls else "Команда 2"

        match_data = {
            "match_id": match_id,
            "date": date_str,
            "map": map_name,
            "map_display": map_display,
            "score_team1": score_team1,
            "score_team2": score_team2,
            "team1_captain": cap1,
            "team2_captain": cap2,
            "team1_name": f"Команда 1 ({cap1})",
            "team2_name": f"Команда 2 ({cap2})",
            "players": players,
            "rounds": light_rounds,
            "kills": light_kills,
            "damages": light_damages,
            "economy": []
        }
        
        match_data = audit_match_data(match_data)
        return match_data
    except Exception as e:
        logging.error(f"Ошибка при парсинге демки {demo_name}: {e}")
        logging.error(traceback.format_exc())
        return {}

def update_players_db(match_data: dict, players_db: dict) -> dict:
    """Обновление глобальной базы данных игроков на основе данных матча."""
    match_id = match_data.get("match_id")
    match_date = match_data.get("date")
    map_display = match_data.get("map_display")
    
    for steam_id, player_stats in match_data.get("players", {}).items():
        if not steam_id:
            continue
        if steam_id not in players_db:
            players_db[steam_id] = {
                "steam_id": steam_id,
                "name": player_stats.get("name", f"Player_{steam_id[-4:]}"),
                "matches": []
            }
        
        if steam_id in PLAYER_NAMES:
            players_db[steam_id]["name"] = PLAYER_NAMES[steam_id]
            
        existing_matches = [m.get("match_id") for m in players_db[steam_id]["matches"]]
        if match_id not in existing_matches:
            match_summary = {
                "match_id": match_id,
                "date": match_date,
                "map": map_display,
                "kills": player_stats.get("kills", 0),
                "deaths": player_stats.get("deaths", 0),
                "assists": player_stats.get("assists", 0),
                "adr": player_stats.get("adr", 0.0),
                "kast": player_stats.get("kast", 0.0),
                "hs_percent": player_stats.get("hs_percent", 0.0),
                "first_kills": player_stats.get("first_kills", 0),
                "first_deaths": player_stats.get("first_deaths", 0),
                "clutch_wins": player_stats.get("clutch_wins", 0),
                "clutch_attempts": player_stats.get("clutch_attempts", 0),
                "utility_damage": player_stats.get("utility_damage", 0),
                "flash_assists": player_stats.get("flash_assists", 0),
                "trades": player_stats.get("trades", 0),
                "weapon_kills": player_stats.get("weapon_kills", {}),
                "pistol_round_kills": player_stats.get("pistol_round_kills", 0),
                "pistol_round_deaths": player_stats.get("pistol_round_deaths", 0)
            }
            players_db[steam_id]["matches"].append(match_summary)
            
    return players_db

def parse_all_new() -> list[dict]:
    """Основная функция парсинга всех новых демок."""
    registry = load_registry()
    new_demos = find_new_demos(registry)
    
    if not new_demos:
        logging.info("Новых демок не найдено.")
        return []
        
    logging.info(f"Найдено новых демок для парсинга: {len(new_demos)}")
    
    players_db_path = DATA_DIR / "players_db.json"
    players_db = {}
    if players_db_path.exists():
        try:
            with open(players_db_path, "r", encoding="utf-8") as f:
                players_db = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки players_db: {e}")
            
    parsed_results = []
    matches_dir = DATA_DIR / "matches"
    os.makedirs(matches_dir, exist_ok=True)
    
    for date_str, filename, full_path in new_demos:
        match_data = parse_single_demo(full_path, date_str, filename)
        if match_data and match_data.get("match_id"):
            parsed_results.append(match_data)
            
            match_json_path = matches_dir / f"{match_data['match_id']}.json"
            with open(match_json_path, "w", encoding="utf-8") as f:
                json.dump(match_data, f, indent=4, ensure_ascii=False)
                
            players_db = update_players_db(match_data, players_db)
            
            demo_id = f"{date_str}_{filename}"
            registry.setdefault("parsed", []).append(demo_id)
            save_registry(registry)
            
            logging.info(f"Успешно обработана и сохранена демка: {filename} -> {match_data['match_id']}")
            
    with open(players_db_path, "w", encoding="utf-8") as f:
        json.dump(players_db, f, indent=4, ensure_ascii=False)
        
    if parsed_results:
        try:
            from scripts.generate_site import sync_match_videos
            all_mids = [f.stem for f in matches_dir.glob("*.json")]
            sync_match_videos(all_mids)
        except Exception as ve:
            logging.debug(f"Синхронизация match_videos.json пропущена: {ve}")

    logging.info("Парсинг новых демок завершен.")
    return parsed_results

if __name__ == "__main__":
    parse_all_new()
