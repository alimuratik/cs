import json
import os
import time
import math
from datetime import datetime
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict, Counter
import statistics
from scripts.config import clean_steamid
from scripts.ai_analysis import (
    analyze_round_with_ai, generate_match_intro_commentary,
    generate_match_summary_analysis, analyze_player_with_ai,
    get_gemini_client
)
from scripts.config import (
    PLAYER_ALIASES, CANONICAL_PLAYERS, STARTING_MMR, BASE_TEAM_DELTA,
    MAX_IMPACT_MODIFIER, MAX_REGULAR_DELTA, CALIBRATION_MATCH_LIMIT,
    CALIBRATION_VOLATILITY, MAX_CALIBRATION_DELTA, INACTIVITY_DAYS_THRESHOLD,
    AI_MODEL, MAP_DISPLAY_NAMES, MAP_ICONS, DATA_DIR
)


@dataclass
class PlayerMetrics:
    steam_id: str
    name: str

RIFLES = {"ak47", "m4a1", "m4a1_silencer", "m4a4", "awp", "aug", "sg556", "scar20", "g3sg1"}
MID_TIER = {"galilar", "famas", "ssg08", "mp9", "mac10", "mp7", "mp5sd", "ump45", "p90", "bizon", "xm1014", "mag7", "nova", "sawedoff", "m249", "negev"}
UPGRADED_PISTOLS = {"deagle", "revolver", "fn57", "tec9", "cz75a", "p250", "dualberettas"}

CS2_WEAPON_PRICES = {
    "glock": 200, "usp_silencer": 200, "hkp2000": 200, "p2000": 200,
    "p250": 300, "dualberettas": 300, "fiveseven": 500, "tec9": 500,
    "cz75a": 500, "deagle": 700, "revolver": 600,
    "mac10": 1050, "mp9": 1250, "mp7": 1500, "mp5sd": 1500, "ump45": 1200, "p90": 2350, "bizon": 1400,
    "nova": 1050, "xm1014": 2000, "sawedoff": 1100, "mag7": 1300, "m249": 5200, "negev": 1700,
    "galilar": 1800, "famas": 2050, "ak47": 2700, "m4a1": 2900, "m4a1_silencer": 2900, "m4a4": 3100,
    "ssg08": 1700, "aug": 3300, "sg556": 3000, "sg553": 3000, "awp": 4750, "scar20": 5000, "g3sg1": 5000,
    "hegrenade": 300, "flashbang": 200, "smokegrenade": 300, "molotov": 400, "incgrenade": 600,
    "taser": 200
}

def estimate_team_equipment(
    round_num: int,
    team_kills: list,
    team_damages: list,
    won_prev: bool,
    is_ct: bool,
    opp_is_eco: bool = False
) -> dict:
    """
    Расчет Team Equipment Value ($) и контекстного бейджа CS2:
    - Pistol Round (раунд 1, 13, первый раунд ОТ): $4,000 ($800/игрок)
    - Full Eco (< $5,000): сухой эко после поражения
    - Semi-Eco ($5,000 - $10,000): улучшенные пистолеты (Deagle, Tec-9, Five-Seven) + легкая броня
    - Force Buy ($10,000 - $20,000 после поражения): покупка на все деньги
    - Semi-Buy ($10,000 - $20,000 после победы): неполная выкладка
    - Anti-Eco: после победы (особенно во 2/14 раунде) с фарм-ганами (MP9, MAC-10) против эко
    - Hero Buy: 1 игрок держит оружие/AWP > $4,500, остальные четверо < $3,000
    - Full Buy (> $20,000): основное оружие (AK/M4/AWP) + шлемы + полный раскид
    """
    if round_num in (1, 13):
        return {
            "badge": "Pistol",
            "val": 4000,
            "val_display": "$4 000",
            "text": "Pistol ($4 000)",
            "short_text": "Pistol"
        }

    player_weapons = {}
    for k in team_kills:
        p = k.get("attacker_name") or k.get("attacker_steamid") or "P"
        w = (k.get("weapon") or "").lower()
        if w in CS2_WEAPON_PRICES:
            player_weapons.setdefault(p, set()).add(w)

    for d in team_damages:
        p = d.get("attacker_name") or d.get("attacker_steamid") or "P"
        w = (d.get("weapon") or "").lower()
        if w in CS2_WEAPON_PRICES:
            player_weapons.setdefault(p, set()).add(w)

    player_values = []
    has_rifles = False
    has_smg = False
    has_upgraded_pistol = False

    for i in range(5):
        p_key = list(player_weapons.keys())[i] if i < len(player_weapons) else f"Player_{i}"
        w_set = player_weapons.get(p_key, set())
        main_w = max(w_set, key=lambda x: CS2_WEAPON_PRICES.get(x, 200)) if w_set else None
        w_price = CS2_WEAPON_PRICES.get(main_w, 200) if main_w else (2700 if won_prev else 200)

        if main_w in ("ak47", "m4a1", "m4a1_silencer", "m4a4", "aug", "sg556", "sg553", "awp", "scar20", "g3sg1"):
            has_rifles = True
        if main_w in ("mac10", "mp9", "mp7", "mp5sd", "ump45", "p90", "bizon", "galilar", "famas", "ssg08"):
            has_smg = True
        if main_w in ("deagle", "revolver", "tec9", "fiveseven", "cz75a", "p250"):
            has_upgraded_pistol = True

        # Оценка брони, гранат и китов
        if w_price >= 2700:
            gear = 1000 + 1000 + (400 if is_ct else 0)  # Helm + nades + defuse kit
        elif w_price >= 1050:
            gear = 1000 + 400  # Helm + grenade
        elif w_price >= 500:
            gear = 650 + 200   # Kevlar + flash
        else:
            gear = 0 if not won_prev else (1000 + 400)

        player_values.append(w_price + gear)

    total_val = sum(player_values)
    max_p_val = max(player_values)
    rest_val = total_val - max_p_val

    # 0. Pistol Round: 1-й и 13-й раунды (старт половин, $800 капитал)
    if round_num in (1, 13):
        badge = "Pistol"
        if total_val > 4500 or total_val < 2000:
            total_val = 3800
    # 1. Hero Buy (Glass Cannon): 1 игрок держит > 4500, остальные четверо суммарно < 3200
    elif max_p_val >= 4500 and rest_val <= 3200 and not won_prev:
        badge = "Hero Buy"
    # 2. Anti-Eco: после победы (особенно во 2 раунде) с фарм-ганами против эко оппонента
    elif won_prev and round_num in (2, 14) and (has_smg or opp_is_eco):
        badge = "Anti-Eco"
    # 3. Full Buy: > 20000$ (или наличие винтовок и сумма близка к 20k)
    elif total_val >= 20000 or (has_rifles and won_prev and total_val >= 17500):
        badge = "Full Buy"
    # 4. Force Buy / Semi-Buy: 10000$ - 20000$
    elif 10000 <= total_val < 20000:
        badge = "Semi-Buy" if won_prev else "Force Buy"
    # 5. Semi-Eco: 5000$ - 10000$
    elif 5000 <= total_val < 10000:
        badge = "Semi-Eco"
    # 6. Full Eco: < 5000$
    else:
        badge = "Full Eco"

    rounded_val = int(round(total_val / 100.0) * 100)
    str_val = f"${rounded_val:,}".replace(",", " ")
    return {
        "badge": badge,
        "val": rounded_val,
        "val_display": str_val,
        "text": f"{badge} ({str_val})",
        "short_text": badge
    }

def classify_team_economy(round_num: int, team_kills: list, team_damages: list, won_previous_round: bool, avg_money: float = 0.0) -> str:
    """Для обратной совместимости."""
    res = estimate_team_equipment(round_num, team_kills, team_damages, won_previous_round, False)
    return res["text"]

def audit_and_recompute_match_events(match_data: dict) -> dict:
    """
    Пересчитывает точные First Kills, First Deaths, Clutches (1vX ситуации и победы)
    для всех игроков матча на основе сырых массивов kills и rounds.
    """
    kills = match_data.get("kills", [])
    rounds = match_data.get("rounds", [])
    players = match_data.get("players", {})

    if not kills or not rounds or not players:
        return match_data

    sid_map = {}
    for sid, p in players.items():
        cs = clean_steamid(sid)
        sid_map[cs] = cs
        p_name = p.get("name", "")
        if p_name:
            sid_map[p_name.lower().strip()] = cs

    for name_k, can_sid in CANONICAL_PLAYERS.items():
        if can_sid in players or any(clean_steamid(s) == can_sid for s in players):
            sid_map[name_k] = can_sid

    def resolve_sid(sid_val, name_val):
        cs = clean_steamid(sid_val)
        if cs in sid_map:
            return sid_map[cs]
        nl = str(name_val or "").lower().strip()
        if nl in sid_map:
            return sid_map[nl]
        if nl in CANONICAL_PLAYERS:
            return CANONICAL_PLAYERS[nl]
        return None

    fk_counts = {clean_steamid(sid): 0 for sid in players}
    fd_counts = {clean_steamid(sid): 0 for sid in players}
    clutch_wins = {clean_steamid(sid): 0 for sid in players}
    clutch_attempts = {clean_steamid(sid): 0 for sid in players}

    t1_sids = {clean_steamid(sid) for sid, p in players.items() if p.get("team") == "team1"}
    t2_sids = {clean_steamid(sid) for sid, p in players.items() if p.get("team") == "team2"}

    kills_by_round = {}
    for k in kills:
        r = k.get("round_num", 0)
        kills_by_round.setdefault(r, []).append(k)

    for r in rounds:
        r_num = r.get("round_num")
        w_team = r.get("winning_team")
        rkills = sorted(kills_by_round.get(r_num, []), key=lambda x: x.get("tick", 0))

        # First Kill / First Death (строго первый фраг раунда)
        if rkills:
            first_k = rkills[0]
            att_sid = resolve_sid(first_k.get("attacker_steamid"), first_k.get("attacker_name"))
            vic_sid = resolve_sid(first_k.get("victim_steamid"), first_k.get("victim_name"))
            if att_sid and att_sid in fk_counts:
                fk_counts[att_sid] += 1
            if vic_sid and vic_sid in fd_counts:
                fd_counts[vic_sid] += 1

        alive_t1 = set(t1_sids)
        alive_t2 = set(t2_sids)
        clutcher_t1 = None
        clutcher_t2 = None
        t1_entered = False
        t2_entered = False

        for k in rkills:
            vic = resolve_sid(k.get("victim_steamid"), k.get("victim_name"))
            if not vic:
                continue
            alive_t1.discard(vic)
            alive_t2.discard(vic)

            if len(alive_t1) == 1 and len(alive_t2) >= 1 and not t1_entered:
                sole = list(alive_t1)[0]
                if sole in clutch_attempts:
                    clutch_attempts[sole] += 1
                clutcher_t1 = sole
                t1_entered = True

            if len(alive_t2) == 1 and len(alive_t1) >= 1 and not t2_entered:
                sole = list(alive_t2)[0]
                if sole in clutch_attempts:
                    clutch_attempts[sole] += 1
                clutcher_t2 = sole
                t2_entered = True

        if w_team == "team1" and clutcher_t1 and clutcher_t1 in clutch_wins:
            clutch_wins[clutcher_t1] += 1
        elif w_team == "team2" and clutcher_t2 and clutcher_t2 in clutch_wins:
            clutch_wins[clutcher_t2] += 1

    for sid, p in players.items():
        cs = clean_steamid(sid)
        p["first_kills"] = fk_counts.get(cs, p.get("first_kills", 0))
        p["first_deaths"] = fd_counts.get(cs, p.get("first_deaths", 0))
        p["clutch_wins"] = clutch_wins.get(cs, 0)
        p["clutch_attempts"] = clutch_attempts.get(cs, 0)

    return match_data

def analyze_match(match_data: dict) -> dict:
    """
    Анализирует данные матча и обогащает их дополнительными метриками.
    """
    match_data = audit_and_recompute_match_events(match_data)
    rounds = match_data.get("rounds", [])
    
    enriched_rounds = []
    player_mvp_scores = defaultdict(float)

    # Определяем Steam ID игроков для каждой команды
    t1_sids = set()
    t2_sids = set()
    for sid, p in match_data.get("players", {}).items():
        c_sid = clean_steamid(sid)
        if p.get("team") == "team1":
            t1_sids.add(c_sid)
            t1_sids.add(str(sid))
        elif p.get("team") == "team2":
            t2_sids.add(c_sid)
            t2_sids.add(str(sid))
    
    prev_winning_team = None
    t1_name = match_data.get("team1_name") or "Команда 1"
    t2_name = match_data.get("team2_name") or "Команда 2"

    for round_idx, r in enumerate(rounds, start=1):
        r_kills = [k for k in match_data.get("kills", []) if k.get("round_num") == round_idx]
        r_dmg = [d for d in match_data.get("damages", []) if d.get("round_num") == round_idx]

        # Определение стороны команд в этом раунде
        t1_side = r.get("t1_side")
        if not t1_side:
            t1_side = "ct" if round_idx <= 12 else "t"
        t2_side = "t" if t1_side == "ct" else "ct"
        ct_team = "team1" if t1_side == "ct" else "team2"
        t_team = "team2" if t1_side == "ct" else "team1"

        ct_team_name = t1_name if t1_side == "ct" else t2_name
        t_team_name = t2_name if t1_side == "ct" else t1_name

        r_t1_kills = [
            k for k in r_kills
            if str(clean_steamid(k.get("attacker_steamid") or k.get("attacker_steam_id"))) in t1_sids
            or str(k.get("attacker_side") or "").lower() == t1_side
        ]
        r_t2_kills = [
            k for k in r_kills
            if str(clean_steamid(k.get("attacker_steamid") or k.get("attacker_steam_id"))) in t2_sids
            or str(k.get("attacker_side") or "").lower() == t2_side
        ]
        r_t1_dmg = [
            d for d in r_dmg
            if str(clean_steamid(d.get("attacker_steamid") or d.get("attacker_steam_id"))) in t1_sids
            or str(d.get("attacker_side") or "").lower() == t1_side
        ]
        r_t2_dmg = [
            d for d in r_dmg
            if str(clean_steamid(d.get("attacker_steamid") or d.get("attacker_steam_id"))) in t2_sids
            or str(d.get("attacker_side") or "").lower() == t2_side
        ]
        t1_won_prev = (prev_winning_team == "team1")
        t2_won_prev = (prev_winning_team == "team2")

        ct_kills = r_t1_kills if t1_side == "ct" else r_t2_kills
        ct_dmg = r_t1_dmg if t1_side == "ct" else r_t2_dmg
        ct_won_prev = t1_won_prev if t1_side == "ct" else t2_won_prev

        t_kills = r_t2_kills if t1_side == "ct" else r_t1_kills
        t_dmg = r_t2_dmg if t1_side == "ct" else r_t1_dmg
        t_won_prev = t2_won_prev if t1_side == "ct" else t1_won_prev

        ct_eco = estimate_team_equipment(round_idx, ct_kills, ct_dmg, ct_won_prev, is_ct=True)
        t_eco = estimate_team_equipment(round_idx, t_kills, t_dmg, t_won_prev, is_ct=False)

        # Контекстное уточнение Anti-Eco если оппонент на эко
        if ct_won_prev and t_eco["badge"] in ("Full Eco", "Semi-Eco") and round_idx in (2, 14):
            ct_eco = estimate_team_equipment(round_idx, ct_kills, ct_dmg, ct_won_prev, is_ct=True, opp_is_eco=True)
        if t_won_prev and ct_eco["badge"] in ("Full Eco", "Semi-Eco") and round_idx in (2, 14):
            t_eco = estimate_team_equipment(round_idx, t_kills, t_dmg, t_won_prev, is_ct=False, opp_is_eco=True)

        r["ct_economy_badge"] = ct_eco["badge"]
        r["ct_economy_val"] = ct_eco["val"]
        r["ct_economy_val_display"] = ct_eco["val_display"]
        r["ct_economy"] = ct_eco["text"]

        r["t_economy_badge"] = t_eco["badge"]
        r["t_economy_val"] = t_eco["val"]
        r["t_economy_val_display"] = t_eco["val_display"]
        r["t_economy"] = t_eco["text"]

        # Маппинг для обратной совместимости
        r["team_a_economy"] = r["ct_economy"] if t1_side == "ct" else r["t_economy"]
        r["team_b_economy"] = r["t_economy"] if t1_side == "ct" else r["ct_economy"]
        r["ct_team"] = ct_team
        r["t_team"] = t_team
        r["t1_side"] = t1_side
        r["t2_side"] = t2_side
        r["ct_team_name"] = ct_team_name
        r["t_team_name"] = t_team_name
        r["is_pistol_round"] = round_idx in (1, 13)

        prev_winning_team = r.get("winning_team")
        
        # Подсчет MVP очков
        for player_stat in r.get("player_stats", []):
            steam_id = player_stat.get("steam_id")
            kills = player_stat.get("kills", 0)
            assists = player_stat.get("assists", 0)
            adr = player_stat.get("adr", 0)
            first_kills = player_stat.get("first_kills", 0)
            clutch_wins = player_stat.get("clutch_wins", 0)
            
            score = (kills * 1) + (assists * 0.3) + (adr * 0.01) + (first_kills * 0.5) + (clutch_wins * 1.5)
            player_mvp_scores[steam_id] += score
            
        # Генерация подробного 9-пунктового тактического разбора раунда (если ещё не сгенерирован)
        if not r.get("ai_analysis"):
            map_n = match_data.get("map_display") or match_data.get("map") or "Mirage"
            win_team_k = r.get("winning_team")
            w_team_name = t1_name if win_team_k == "team1" else (t2_name if win_team_k == "team2" else None)
            r["ai_analysis"] = analyze_round_with_ai(
                r, r_kills, r_dmg, map_n, w_team_name, ct_team_name, t_team_name
            )
        
        enriched_rounds.append(r)
        
    match_data["rounds"] = enriched_rounds
    
    # Определение MVP матча
    if player_mvp_scores:
        match_data["mvp_steam_id"] = max(player_mvp_scores, key=player_mvp_scores.get)
    
    # Генерация вводного аналитического обзора матча для команд
    if not match_data.get("ai_analysis"):
        match_data["ai_analysis"] = generate_match_intro_commentary(match_data)

    # Генерация итогового сводного тренерского анализа (10 игроков + 3 системных вывода)
    old_static_marker = "При нехватке девайсов команды часто принимают лобовые перестрелки"
    fallback_marker = "Игроки предпринимали рискованные"
    current_summary = match_data.get("summary_analysis", "")
    if (not current_summary 
            or old_static_marker in current_summary 
            or fallback_marker in current_summary 
            or "Рассинхрон опенинг-дуэлей на" in current_summary 
            or match_data.get("summary_version") != 3):
        match_data["summary_analysis"] = generate_match_summary_analysis(match_data)
        match_data["summary_version"] = 3
    
    return match_data

def compute_hltv_rating(k: int, d: int, a: int, adr: float, kast: float, fk: int, fd: int, rounds_cnt: int) -> Tuple[float, float]:
    """
    Вычисляет честный рейтинг HLTV 2.0 и приведенную оценку 1.0 - 10.0.
    """
    r_cnt = max(1, rounds_cnt)
    impact = 2.13 * (k / r_cnt) + 0.42 * (a / r_cnt) + 0.35 * (fk / r_cnt) - 0.25 * (fd / r_cnt) - 0.35
    hltv = (
        0.30 * (k / (r_cnt * 0.679)) +
        0.20 * ((r_cnt - d) / (r_cnt * 0.317)) +
        0.25 * (adr / 75.0) +
        0.15 * (kast / 70.0) +
        0.10 * max(0.0, impact)
    )
    hltv = round(max(0.20, min(3.00, hltv)), 2)
    score_10 = round(max(1.0, min(10.0, 5.0 + (hltv - 1.00) * 5.0)), 1)
    return hltv, score_10

def clamp(val: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(val, max_val))

def linear_interp(val: float, base_val: float, max_val: float, base_rating: float = 5.0, max_rating: float = 10.0) -> float:
    if val <= base_val:
        return base_rating * (val / base_val) if base_val > 0 else base_rating
    if val >= max_val:
        return max_rating
    
    ratio = (val - base_val) / (max_val - base_val)
    return base_rating + ratio * (max_rating - base_rating)

def calculate_player_ratings(player_data: dict) -> dict:
    """
    Рассчитывает рейтинги игрока по 10-балльной шкале.
    """
    metrics = player_data.get("metrics", {})
    
    # 1. Aim
    hs_percent = metrics.get("hs_percent", 0)
    adr = metrics.get("adr", 0)
    kill_eff = metrics.get("kill_efficiency", 0)
    aim_rating = (
        linear_interp(hs_percent, 40, 65) * 0.5 +
        linear_interp(adr, 70, 100) * 0.3 +
        linear_interp(kill_eff, 40, 60) * 0.2
    )
    
    # 2. Positioning
    dpr = metrics.get("dpr", 1.0)
    sr = metrics.get("survival_rate", 0)
    tdr = metrics.get("trade_death_rate", 0)
    # Меньше dpr = лучше
    pos_dpr_rating = linear_interp(1.5 - dpr, 1.5 - 0.7, 1.5 - 0.5) 
    pos_rating = pos_dpr_rating * 0.4 + linear_interp(sr, 30, 50) * 0.3 + linear_interp(tdr, 15, 30) * 0.3
    
    # 3. Utility
    ud = metrics.get("utility_damage", 0)
    fa = metrics.get("flash_assists", 0)
    gu = metrics.get("grenade_usage", 0)
    util_rating = linear_interp(ud, 8, 20) * 0.4 + linear_interp(fa, 1, 4) * 0.3 + linear_interp(gu, 10, 25) * 0.3
    
    # 4. Game Sense
    kast = metrics.get("kast", 0)
    tr = metrics.get("trade_rate", 0)
    ri = metrics.get("round_impact", 0)
    sense_rating = linear_interp(kast, 65, 80) * 0.4 + linear_interp(tr, 25, 45) * 0.3 + linear_interp(ri, 0.8, 1.5) * 0.3
    
    # 5. Entry
    fkr = metrics.get("first_kill_rate", 0)
    es = metrics.get("entry_success", 0)
    entry_rating = linear_interp(fkr, 10, 25) * 0.5 + linear_interp(es, 45, 65) * 0.5
    
    # 6. Trading
    tp = metrics.get("trade_percentage", 0)
    ts = metrics.get("trade_speed", 0)
    trade_rating = linear_interp(tp, 25, 50) * 0.6 + linear_interp(5 - ts, 5 - 3, 5 - 1) * 0.4 # Меньше скорость(с) = лучше
    
    # 7. Clutch
    cwr = metrics.get("clutch_win_rate", 0)
    ca = metrics.get("clutch_attempts", 0)
    clutch_rating = linear_interp(cwr, 20, 50) * 0.6 + linear_interp(ca, 2, 5) * 0.4
    
    # 8. Discipline & Economy
    eco_disc = metrics.get("eco_discipline", 50)
    buy_cons = metrics.get("buy_consistency", 50)
    disc_rating = linear_interp(eco_disc, 50, 80) * 0.5 + linear_interp(buy_cons, 50, 80) * 0.5
    
    erk = metrics.get("eco_round_kills", 0.4)
    fbe = metrics.get("force_buy_eff", 1.0)
    vs_full_kd = metrics.get("vs_full_buy_kd", 1.0)
    econ_rating = (
        linear_interp(erk, 0.25, 0.75) * 0.35 +
        linear_interp(fbe, 0.70, 1.50) * 0.35 +
        linear_interp(vs_full_kd, 0.75, 1.35) * 0.30
    )
    
    ratings = {
        "Aim": clamp(aim_rating, 1.0, 10.0),
        "Positioning": clamp(pos_rating, 1.0, 10.0),
        "Utility": clamp(util_rating, 1.0, 10.0),
        "Game Sense": clamp(sense_rating, 1.0, 10.0),
        "Entry": clamp(entry_rating, 1.0, 10.0),
        "Trading": clamp(trade_rating, 1.0, 10.0),
        "Clutch": clamp(clutch_rating, 1.0, 10.0),
        "Discipline": clamp(disc_rating, 1.0, 10.0),
        "Economy": clamp(econ_rating, 1.0, 10.0)
    }
    
    overall = sum(ratings.values()) / len(ratings)
    ratings["Overall Impact"] = clamp(overall, 1.0, 10.0)
    
    return ratings

def detect_play_style(player_data: dict) -> list[str]:
    """
    Определяет роли игрока (Основная роль + Вторая роль)
    строго по правилам instruction/role.txt.
    Возможные роли:
      - Снайпер (Main AWP)
      - Энтри-фраггер (Entry Fragger)
      - Второй номер (Trader / Re-Fragger)
      - Саппорт (Support)
      - Опорник (Anchor)
      - Люркер (Lurker)
      - Клатчер (Clutcher)
      - Универсал (Flex Rifler)
    """
    m = player_data.get("metrics", {})
    candidates = []

    awp_pct = m.get("awp_kills_percent", 0.0)
    rifle_pct = m.get("rifle_kills_percent", 0.0)
    fkr = m.get("first_kill_rate", 0.0)
    fdr = m.get("first_death_rate", 0.0)
    open_inv = m.get("opening_involvement", (fkr + fdr) / 100.0)
    es = m.get("entry_success", 0.0)
    tr = m.get("trade_rate", 0.0)
    ud = m.get("utility_damage_per_round", 0.0)
    fa = m.get("flash_assists_per_match", 0.0)
    kast = m.get("kast", 0.0)
    surv = m.get("survival_rate", 0.0)
    cwr = m.get("clutch_win_rate", 0.0)
    ca = m.get("clutch_attempts_per_match", 0.0)
    kd = m.get("kd_ratio", 1.0)

    # 1. Main AWP (Снайпер)
    # Порог: awp_kills / total_kills >= 20.0% или более 20 убийств с AWP при >= 15%
    awp_k = m.get("awp_kills", 0)
    if awp_pct >= 20.0 or (awp_k >= 20 and awp_pct >= 15.0):
        candidates.append(("Снайпер", 120 + awp_pct * 2.0))

    # 2. Entry Fragger (Энтри-фраггер / Острие атаки)
    # Порог: fkr >= 14.0 или (open_inv >= 0.15 и es >= 45%)
    if fkr >= 14.0 or (open_inv >= 0.15 and es >= 45.0):
        candidates.append(("Энтри-фраггер", 105 + fkr * 2.0 + es * 0.4))

    # 3. Support (Саппорт / Гранатометчик)
    # Порог: высокий урон гранатами (>= 6.0) или частые флеш-ассисты (>= 0.35)
    if ud >= 6.0 or fa >= 0.35:
        candidates.append(("Саппорт", 95 + ud * 3.5 + fa * 25.0))

    # 4. Trader / Second Entry (Второй номер / Трейдер)
    # Порог: trade_rate >= 20.0%
    if tr >= 20.0:
        candidates.append(("Второй номер", 90 + tr * 1.5 + kd * 8.0))

    # 5. Clutcher (Клатчер / Финишер)
    clutch_att = m.get("clutch_attempts", 0)
    if cwr >= 30.0 and clutch_att >= 3:
        candidates.append(("Клатчер", 85 + cwr * 0.8))

    # 6. Anchor (Опорник точки / Сторож)
    # Защитный профиль: высокий KAST, низкие первые смерти, игра на удержание
    if kast >= 68.0 and fdr <= 10.0:
        candidates.append(("Опорник", 80 + kast * 0.4 + surv * 0.3))

    # 7. Lurker (Люркер / Одиночка)
    # Фланговая игра: низкое участие в первых дуэлях, поздние фраги, независимая игра
    if fkr <= 8.5 and surv >= 30.0:
        candidates.append(("Люркер", 75 + surv + max(0, 10.0 - fkr) * 2.0))

    # 8. Универсал (Flex Rifler)
    candidates.append(("Универсал", 70 + kd * 15.0))

    # Сортируем по силе проявления роли
    candidates.sort(key=lambda x: x[1], reverse=True)

    unique_roles = []
    for r, _ in candidates:
        if r not in unique_roles:
            unique_roles.append(r)
        if len(unique_roles) >= 2:
            break

    if len(unique_roles) == 1:
        unique_roles.append("Универсал" if unique_roles[0] != "Универсал" else "Опорник")

    return unique_roles[:2]

def identify_strengths_weaknesses(ratings: dict, metrics: dict = None) -> tuple[list[str], list[str]]:
    """
    Определяет сильные и слабые стороны с конкретным объяснением причины оценки.
    """
    metrics = metrics or {}
    explanations = {
        "Aim": {
            "low": f"Низкий процент попаданий в голову ({metrics.get('hs_percent', 0):.1f}% HS) и спрей мимо цели",
            "high": f"Отличный аим: высокий процент попадений в голову ({metrics.get('hs_percent', 0):.1f}% HS) и урона ({metrics.get('adr', 0):.1f} ADR)"
        },
        "Positioning": {
            "low": f"Частые смерти без размена и низкий процент выживаемости ({metrics.get('survival_rate', 0):.1f}%)",
            "high": f"Грамотный выбор позиций: высока выживаемость ({metrics.get('survival_rate', 0):.1f}%) и минимум глупых смертей"
        },
        "Utility": {
            "low": f"Мало урона гранатами ({metrics.get('utility_damage', 0):.1f} UD/раунд) и редкие флеш-ассисты",
            "high": f"Эффективный раскид: хороший урон гранатами ({metrics.get('utility_damage', 0):.1f} UD/раунд) и поддержка"
        },
        "Game Sense": {
            "low": f"Недостаточный KAST% ({metrics.get('kast', 0):.1f}%) и низкая активность в ключевых фазах раунда",
            "high": f"Отличный KAST ({metrics.get('kast', 0):.1f}%): умение читать игру и приносить пользу в каждом раунде"
        },
        "Entry": {
            "low": f"Редкие первые дуэли ({metrics.get('first_kill_rate', 0):.1f}% First Kills) или проигрыш открывающих стычек",
            "high": f"Агрессивный и эффективный вход ({metrics.get('first_kill_rate', 0):.1f}% FK): открывает раунды для команды"
        },
        "Trading": {
            "low": f"Редкий размен павших сокомандников (менее {metrics.get('trade_percentage', 0):.1f}% размененных смертей)",
            "high": f"Отличный размен: оперативная помощь партнерам ({metrics.get('trade_percentage', 0):.1f}% разменов)"
        },
        "Clutch": {
            "low": f"Низкая реализация соло-ситуаций и неуверенность в клатчах",
            "high": f"Хладнокровие в одиночку: высокий процент выигрыша клатч-раундов"
        },
        "Discipline": {
            "low": f"Ошибки в экономических закупках и несогласованные действия на эко",
            "high": f"Высокая дисциплина закупок и сдержанность в командной экономике"
        },
        "Economy": {
            "low": f"Слабая игра с пистолетами и в форс-бай раундах",
            "high": f"Высокая эффективность эко-раундов и фарм-ганов"
        }
    }

    sorted_ratings = sorted([(k, v) for k, v in ratings.items() if k != "Overall Impact"], key=lambda x: x[1])
    
    weaknesses = []
    for k, v in sorted_ratings:
        if v < 5.0:
            desc = explanations.get(k, {}).get("low", "требуется улучшение показателя")
            weaknesses.append(f"{k} ({v:.1f}) — {desc}")
            if len(weaknesses) >= 3:
                break
                
    strengths = []
    for k, v in reversed(sorted_ratings):
        if v > 6.0:
            desc = explanations.get(k, {}).get("high", "высокая эффективность")
            strengths.append(f"{k} ({v:.1f}) — {desc}")
            if len(strengths) >= 3:
                break

    return strengths, weaknesses

def calculate_stability(player_matches: list[dict]) -> dict:
    """
    Оценивает стабильность игрока по матчам.
    """
    if len(player_matches) < 2:
        return {"stability_score": 5.0, "most_stable": "Н/Д", "least_stable": "Н/Д"}
        
    metrics = defaultdict(list)
    for m in player_matches:
        for k, v in m.get("metrics", {}).items():
            if isinstance(v, (int, float)):
                metrics[k].append(v)
                
    stdevs = {}
    for k, vals in metrics.items():
        if len(vals) > 1:
            stdevs[k] = statistics.stdev(vals) / (statistics.mean(vals) + 0.0001) # CV
            
    if not stdevs:
        return {"stability_score": 5.0, "most_stable": "Н/Д", "least_stable": "Н/Д"}
        
    sorted_stdevs = sorted(stdevs.items(), key=lambda x: x[1])
    most_stable = sorted_stdevs[0][0]
    least_stable = sorted_stdevs[-1][0]
    
    avg_cv = sum(stdevs.values()) / len(stdevs)
    stability_score = clamp(10.0 - (avg_cv * 10), 1.0, 10.0)
    
    return {
        "stability_score": round(stability_score, 1),
        "most_stable": most_stable,
        "least_stable": least_stable
    }

def analyze_weapons(player_data: dict) -> dict:
    """
    Анализирует эффективность владения оружием.
    """
    weapons = player_data.get("weapons", {})
    total_kills = sum(w.get("kills", 0) for w in weapons.values())
    
    cats = {"Rifle": 0, "AWP": 0, "Pistol": 0, "SMG": 0, "Shotgun": 0}
    
    for w_name, w_stat in weapons.items():
        cat = w_stat.get("category", "Other")
        if cat in cats:
            cats[cat] += w_stat.get("kills", 0)
            
    return {
        "categories": cats,
        "most_effective": max(cats, key=cats.get) if total_kills > 0 else "Н/Д"
    }

# База тактических знаний по соревновательным картам CS2 (Active Duty)
MAP_TACTICAL_KNOWLEDGE = {
    "de_mirage": {
        "name": "Mirage",
        "weakness_advices": {
            "first_deaths": "На Mirage высокий процент ранних смертей ({fd} первых смертей) вызван опасными соло-пиками в начале раунда. Перестань чекать Мид и Апартаменты B в одиночку без моментальной флешки тиммейта: отходи на второй темп через Коннектор или встречай соперника кросс-файром с Тетриса/Шорта.",
            "low_kast": "На Mirage низкий KAST ({kast}%) сигнализирует о частой позиционной изоляции. Ты погибаешь без возможности тиммейтов разменять фраг. Избегай глубоких позиций в соло на B-пленте (за форестом) или на открытом А-пленте — играй в связке с напарником (Коннектор + Джангл).",
            "low_utility": "На Mirage критически не хватает утилити (всего {util} урона/раунд). Освой стандартную тройку смоков на A (Окно, Коннектор, Старт) и глубокий зажигательный на Шорт/Ковры — это отрежет перетяжки врага и поднимет выживаемость.",
            "low_firepower": "На Mirage проседает дуэльная эффективность (ADR {adr}, HS {hs}%). На этой карте ключевую роль играет пре-аим перепадов высот (Яма-Палас, спуск в Андер). Сфокусируйся на постановке прицела строго на уровне головы при проверке Коннектора и ступеней Мида.",
            "unconverted_carry": "На Mirage ты наносишь мощный урон (ADR {adr}), но побед не хватает (винрейт {wr}%). Твой урон должен превращаться в контроль раунда: прекрати разменивать фраги в меньшинстве и бери на себя колл перетяжек на поздних таймингах через центр карты."
        },
        "strength_advices": {
            "firepower": "Твоя главная цитадель доминирования (винрейт {wr}%, HLTV {hltv}, ADR {adr})! Ты безупречно контролируешь ключевые размены на карте. Сохраняй этот темп и продолжай диктовать агрессию на Миде и А-пленте всей команде!",
            "entry": "Феноменальный опенинг на Mirage ({fk} опенинг-фрагов, винрейт {wr}%)! Ты моментально вскрываешь оборону соперника на старте раунда (входы на B-апартаменты и Мид). Твоя агрессия — главный ключ к раундам команды.",
            "anchor": "Железная стабильность на Mirage (KAST {kast}%, винрейт {wr}%)! Твоё позиционное чутьё и хладнокровие при удержании плентов не оставляют шансов атаке. Ты эталонный якорь обороны на этой карте.",
            "awp": "Снайперский террор на Mirage ({awp} фрагов с AWP, HLTV {hltv})! Ты намертво закрываешь перетяжки через Мид и Окно. Продолжай агрессивно занимать позиции под первым номером."
        }
    },
    "de_inferno": {
        "name": "Inferno",
        "weakness_advices": {
            "first_deaths": "На Inferno ты слишком часто отдаёшься первым ({fd} первых смертей). Главная ошибка — ранний выход на Банан в соло под гранатный град соперника. Не форсируй дуэль у Car на первых секундах: встречай агрессию вторым номером под глубокий флеш через крышу.",
            "low_kast": "На Inferno проседает KAST ({kast}%) из-за смертей в изоляции. Если играешь опорником B (на Фонтане) или в Коврах, не оставайся отрезанным без смока или молика. Отработай парный приём плента (Фонтан + Гробы) с возможностью быстрого сейва или размена.",
            "low_utility": "На Inferno утилити решает 70% исхода раунда, а твой показатель всего {util} урона/раунд. Выучи глубокие молотовы на Банан (за Car и на Полустену), а также смок в ребра и бойлер — это лишит атаку пространства.",
            "low_firepower": "На Inferno страдает огневой размен (ADR {adr}, HS {hs}%). Здесь много узких коридоров с жесткими углами (Ковры, Ребра, Банан). Тренируй микро-пики (jiggle peek) и не выходи на длинную дистанцию с фарм-ганами против винтовок.",
            "unconverted_carry": "На Inferno высокий урон (ADR {adr}), но низкий процент побед ({wr}%). Личные фраги часто делаются поздно, когда плент уже сдан. Фокусируйся на удержании пространства в начале раунда, а не на клатчах в меньшинстве."
        },
        "strength_advices": {
            "firepower": "Твой персональный полигон побед (винрейт {wr}%, HLTV {hltv}, ADR {adr})! Ты перемалываешь соперников в ключевых точках Inferno. Держи этот огневой напор и руководи командными сплитами на B!",
            "entry": "Царь опенинг-дуэлей на Inferno ({fk} энтри-фрагов, винрейт {wr}%)! Ты первым взрываешь Банан и продавливаешь Ковры. Твоя уверенность в первых стычках выигрывает раунды ещё до постановки бомбы.",
            "anchor": "Несокрушимый опорник Inferno (KAST {kast}%, винрейт {wr}%)! Идеальный тайминг задержки рашей на Плентах А и B. Твоя выживаемость позволяет команде проводить образцовые ретейки.",
            "awp": "Снайперская крепость на Inferno ({awp} убийств с AWP, HLTV {hltv})! Безупречный контроль дальних коридоров Банана и Мида. Враги боятся даже пикать твои углы."
        }
    },
    "de_dust2": {
        "name": "Dust2",
        "weakness_advices": {
            "first_deaths": "На Dust2 частые первые смерти ({fd} первых смертей) рушат экономику. Ошибка кроется в ранних открытых дуэлях на Лонге и в прострелах дверей Мида. Используй флешки напарника перед выходом на Лонг и не выходи на открытую позицию без смока на центр.",
            "low_kast": "На Dust2 низкий KAST ({kast}%): открытые пространства карты наказывают за игру в отрыве от команды. Избегай дуэлей 1v1 на большой дистанции без напарника за спиной для моментального трейда (особенно на Лонге и при защите B-плента).",
            "low_utility": "На Dust2 катастрофически мало утилити ({util} урона/раунд). На этой карте критически важно кидать глубокий молотов в Верхнюю Тёмку при звуке шагов и задымлять двери центра при перетяжке. Включи гранаты в дефолтный раунд!",
            "low_firepower": "На Dust2 проседает точность стрельбы (ADR {adr}, HS {hs}%). На этой классической карте перестрелки идут на средних и дальних дистанциях (Лонг, Мид). Отработай теппинг и берст-стрельбу на дальних углах вместо зажима.",
            "unconverted_carry": "На Dust2 высокий индивидуальный урон (ADR {adr}) не даёт результата (винрейт {wr}%). Ты часто делаешь фраги на одном фланге, пока команда проигрывает другой. Больше общайся по радарным перетяжкам и координируй выходы."
        },
        "strength_advices": {
            "firepower": "Абсолютный хозяин Dust2 (винрейт {wr}%, HLTV {hltv}, ADR {adr})! Твоя стрельба на Лонге и Миде деморализует оппонентов. Задавай темп быстрых выходов и командуй агрессивными пушами!",
            "entry": "Безупречный энтри на Dust2 ({fk} первых фрагов, винрейт {wr}%)! Ты моментально выбиваешь двери Лонга и взламываешь Тёмку. Благодаря твоим ранним киллам команда начинает раунды с преимуществом 5v4.",
            "anchor": "Монолитная защита Dust2 (KAST {kast}%, винрейт {wr}%)! Ты грамотно принимаешь атаки на B-сайте и Лонге, всегда сохраняя позицию и давая тайминг на перетяжку тиммейтам.",
            "awp": "Властелин Лонга и дверей Мида ({awp} фрагов с AWP, HLTV {hltv})! Твой реакционный прицел на дальних линиях заставляет соперников тратить весь дым просто чтобы пройти."
        }
    },
    "de_anubis": {
        "name": "Anubis",
        "weakness_advices": {
            "first_deaths": "На Anubis ранние смерти ({fd} первых смертей) связаны с форсированием дуэлей на Воде и в Канале. Это зона быстрых таймингов, где легко нарваться на перекрёстный огонь. Не лезь в Канал в соло — выходи под флешку и контролируй мост.",
            "low_kast": "На Anubis низкий KAST ({kast}%). На этой многоуровневой карте с водой тиммейтам сложно разменивать изолированного игрока на Руинах B или в Коннекторе. Держись на дистанции контакта и не падай в Воду в одиночку.",
            "low_utility": "На Anubis мало урона гранатами ({util} урона/раунд). Молотовы на мост и глубокие смоки в Коннектор и B-руины здесь жизненно необходимы для контроля темпа. Обязательно закупи утилити!",
            "low_firepower": "На Anubis страдает дуэльная статистика (ADR {adr}, HS {hs}%). Из-за обилия выступов, колонн и перепадов воды прицел часто соскальзывает. Тренируй пре-аим за углами колонн B-сайта и входа в коннектор.",
            "unconverted_carry": "На Anubis отличный личный урон (ADR {adr}), но побед мало (винрейт {wr}%). Карта очень быстрая: твои фраги на А не спасают от быстрого планта на B. Быстрее перетягивайся через Коннектор."
        },
        "strength_advices": {
            "firepower": "Твоя несокрушимая арена (винрейт {wr}%, HLTV {hltv}, ADR {adr})! Ты идеально чувствуешь динамику Воды и Руин. Веди команду за собой и контролируй быстрые темпы раундов!",
            "entry": "Гроза Anubis в ранних дуэлях ({fk} опенинг-фрагов, винрейт {wr}%)! Ты молниеносно захватываешь Канал и вскрываешь B-сайт, оставляя защиту без шансов на закрепление.",
            "anchor": "Железный оплот Anubis (KAST {kast}%, винрейт {wr}%)! Грамотное позиционирование за колоннами B и в Heaven на А позволяет стабильно срывать сплиты соперника.",
            "awp": "Смертоносный снайпер Anubis ({awp} фрагов с AWP, HLTV {hltv})! Твой контроль длинных прострелов Воды и Коннектора решает судьбу каждого бай-раунда."
        }
    },
    "de_ancient": {
        "name": "Ancient",
        "weakness_advices": {
            "first_deaths": "На Ancient частые первые смерти ({fd} смертей в дебюте) происходят в борьбе за Центр и выход из Cave. Здесь критически важно не пикать в сухую: требуй смок в Мид или световую гранату через крышу перед агрессией.",
            "low_kast": "На Ancient низкий KAST ({kast}%). На закрытых коридорах этой карты (Donut, Cave) одиночная смерть сразу отдаёт точку. Играй в тесной связке со вторым номером: один байтит, второй мгновенно разменивает.",
            "low_utility": "На Ancient дефицит утилити ({util} урона/раунд). На этой карте гранаты решают всё: зажигательные на Рампу B и смок в Donut сдерживают пуш на 15 секунд. Освой ключевые траектории раскида!",
            "low_firepower": "На Ancient проседает стрельба (ADR {adr}, HS {hs}%). Обилие темных текстур и узких проходов в Храме требует максимальной концентрации прицела. Держи кроссхейр на уровне плеч на выходе из рампы.",
            "unconverted_carry": "На Ancient высокий импакт (ADR {adr}) не приносит побед (винрейт {wr}%). Фокусируйся не на поздних фрагах в джунглях, а на удержании стратегического контроля Пончика (Donut) в мид-гейме."
        },
        "strength_advices": {
            "firepower": "Твои родные джунгли (винрейт {wr}%, HLTV {hltv}, ADR {adr})! Ты тотально доминируешь в перестрелках в Пещере и Центре. Сохраняй лидерство и управляй перетяжками всей команды!",
            "entry": "Сокрушительный энтри на Ancient ({fk} первых фрагов, винрейт {wr}%)! Ты сметаешь оборону соперника на Рампе A и в Cave, обеспечивая легкую установку бомбы.",
            "anchor": "Непробиваемый страж Ancient (KAST {kast}%, винрейт {wr}%)! Твоё хладнокровие на Пончике и B-пленте рушит любые планы атаки противника. Образцовая опорная игра.",
            "awp": "Снайперский контроль Ancient ({awp} фрагов с AWP, HLTV {hltv})! Безупречный отстрел выходов из А-мейна и удержание мида на ключевых таймингах."
        }
    },
    "de_nuke": {
        "name": "Nuke",
        "weakness_advices": {
            "first_deaths": "На Nuke высокий показатель ранних смертей ({fd} первых смертей). Опасные пики Улицы и Рампы без саппорт-дымов часто приводят к мгновенной потере бойца. Используй стену смоков на Yard и играй от укрытий.",
            "low_kast": "На Nuke низкий KAST ({kast}%). Вертикальная структура карты делает размены сложными, если ты упал в Вент или остался на Рампе один. Держи голосовой контакт и не оставайся отрезанным на нижнем пленте.",
            "low_utility": "На Nuke критически мало гранат ({util} урона/раунд). Молотовы на Скрипучку (Squeaky) и задымление Гаража на Улице меняют ход игры. Включи утилити в каждый бай-раунд.",
            "low_firepower": "На Nuke проседает огневая мощь (ADR {adr}, HS {hs}%). Из-за вертикальных позиций (Хэвен, Будка, Скала) прицел часто гуляет по вертикали. Тренируй стрельбу вверх-вниз на высоте.",
            "unconverted_carry": "На Nuke отличный урон (ADR {adr}), но мало побед (винрейт {wr}%). На этой карте раунды выигрываются быстрой ротацией через Венты и ретейками, а не сольной стрельбой на улице. Помогай на таймингах!"
        },
        "strength_advices": {
            "firepower": "Твоя ядерная крепость (винрейт {wr}%, HLTV {hltv}, ADR {adr})! Ты идеально ориентируешься на двух ярусах Nuke и выигрываешь ключевые микро-дуэли. Веди команду к победе!",
            "entry": "Молниеносный энтри Nuke ({fk} первых убийств, винрейт {wr}%)! Твои прорывы через Рампу и Секрет открывают карте второе дыхание и ставят защиту на колени.",
            "anchor": "Железный оплот Nuke (KAST {kast}%, винрейт {wr}%)! Идеальное удержание Рампы и верхней точки A. Ты даёшь команде бесценное время на перетяжку с нижнего яруса.",
            "awp": "Снайперское господство на Nuke ({awp} убийств с AWP, HLTV {hltv})! Полный контроль Улицы из Гаража и дальних прострелов Рампы."
        }
    },
    "de_vertigo": {
        "name": "Vertigo",
        "weakness_advices": {
            "first_deaths": "На Vertigo высокий процент ранних смертей ({fd} первых смертей) связан с агрессивной борьбой за Рампу А на старте раунда. Не пикай Жёлтый и Подмостки в соло без предварительного смока или заградительного молотова под ноги атаке.",
            "low_kast": "На Vertigo проседает KAST ({kast}%). На двухъярусной карте с узкими проходами любая изолированная дуэль на B-лестнице или в Коннекторе оставляет команду 4v5 без размена. Играй в строгой паре со вторым номером.",
            "low_utility": "На Vertigo острый дефицит утилити ({util} урона/раунд). Молотовы на Мешки и глубокий дым на Рампу А жизненно необходимы, чтобы сорвать раш атаки. Закупай полный набор гранат!",
            "low_firepower": "На Vertigo проседает огневой контакт (ADR {adr}, HS {hs}%). Узкие коридоры и перепады лестниц требуют быстрого таргет-свитчинга. Тренируй наводку на уровень головы на наклонных поверхностях Рампы.",
            "unconverted_carry": "На Vertigo высокий урон (ADR {adr}) не трансформируется в победы (винрейт {wr}%). Сольные фраги на B не спасают от быстрой потери Рампы A. Помогай команде в удержании ключевой верхней зоны."
        },
        "strength_advices": {
            "firepower": "Хозяин высоты на Vertigo (винрейт {wr}%, HLTV {hltv}, ADR {adr})! Твоя стрельба на Рампе А и в Центре решает исход карты. Держи лидерство и командуй фаст-сплитами!",
            "entry": "Сокрушительный таран на Vertigo ({fk} опенинг-фрагов, винрейт {wr}%)! Ты моментально взламываешь оборону Рампы и лестницы B. Твоя стартовая агрессия обеспечивает контроль всей карты.",
            "anchor": "Непоколебимый страж Vertigo (KAST {kast}%, винрейт {wr}%)! Образцовое удержание B-сайта и Коннектора. Твоя выдержка даёт время всей команде перетянуться на помощь.",
            "awp": "Снайперская доминанта на Vertigo ({awp} фрагов с AWP, HLTV {hltv})! Безупречный контроль прострелов Центра и Рампы, лишающий соперника инициативы."
        }
    }
}

def _generate_map_advice(map_info: dict, is_favorite: bool, player_style: list[str] = None, player_ratings: dict = None) -> str:
    """
    Генерирует глубокий, тактический и уникальный совет по карте
    с привязкой к конкретным зонам карты, стилю и реальным метрикам игрока.
    """
    if not map_info:
        return ""
    mid = map_info.get("map", "")
    k_data = MAP_TACTICAL_KNOWLEDGE.get(mid)
    mname = map_info.get("name", "карте")
    
    wr = map_info.get("win_rate", 50.0)
    hltv = map_info.get("avg_hltv", 1.0)
    adr = map_info.get("avg_adr", 70.0)
    kd = map_info.get("avg_kd", 1.0)
    kast = map_info.get("avg_kast", 70.0)
    hs = map_info.get("avg_hs", 40.0)
    fk = map_info.get("first_kills", 0)
    fd = map_info.get("first_deaths", 0)
    util = map_info.get("avg_util", 0.0)
    awp = map_info.get("awp_kills", 0)
    rifle = map_info.get("rifle_kills", 0)
    tot = map_info.get("matches", 1)
    
    style_list = player_style or []
    role_tip = ""
    if any(s in style_list for s in ["Entry-фрагер", "Энтри-фраггер", "Агрессивный"]):
        role_tip = " В роли энтри согласовывай первый пик со световой гранатой напарника и входи строго под тайминг взрыва."
    elif any(s in style_list for s in ["AWP-ер", "Снайпер"]):
        role_tip = " Играя со снайперской винтовкой, всегда готовь безопасный путь для отката за укрытие после первого выстрела."
    elif any(s in style_list for s in ["Опорник", "Саппорт"]):
        role_tip = " В роли опорника фокус на максимальной затяжке времени и задерживающем молотове под первый контакт."
    elif any(s in style_list for s in ["Трейдер", "Второй номер"]):
        role_tip = " Как второй номер, держи дистанцию контакта не более 2 секунд от энтри для моментального размена."
    elif any(s in style_list for s in ["Люркер", "Клатчер"]):
        role_tip = " В роли люркера лови тайминги ротации врага в спину и не раскрывай позицию преждевременным шумом."
    else:
        role_tip = " Работай короткими очередями по 2-3 патрона и контролируй перекрестный огонь с тиммейтом."

    if is_favorite:
        # Для любимой карты: учитываем реальный уровень показателей
        if wr >= 60.0 and hltv >= 1.10:
            if awp >= 6 and awp > rifle * 0.4:
                case = "awp"
            elif fk >= 3 and fk > fd:
                case = "entry"
            elif kast >= 77.0:
                case = "anchor"
            else:
                case = "firepower"
                
            if k_data and case in k_data["strength_advices"]:
                base_text = k_data["strength_advices"][case].format(
                    wr=wr, hltv=hltv, adr=adr, kd=kd, kast=kast, hs=hs, fk=fk, fd=fd, util=util, awp=awp, name=mname
                )
            else:
                base_text = f"Твоя сигнатурная крепость на {mname} (винрейт {wr}%, HLTV {hltv}, ADR {adr})! Отличное позиционное чутьё и высокий импакт в ключевых раундах. Продолжай задавать победный темп всей команде!"
        elif wr >= 45.0 or hltv >= 0.95:
            if fk >= 2 and fk >= fd:
                base_text = f"Уверенная карта {mname} в твоем пуле (винрейт {wr}%, {fk} первых фрагов). Ты активно ищешь стартовые контакты и создаешь численное большинство. Подтяни командную поддержку для закрепления успеха."
            elif kast >= 75.0:
                base_text = f"Стабильный плацдарм на {mname} (винрейт {wr}%, KAST {kast}%). Ты надежно держишь позицию и помогаешь в разменах на ключевых точках. Развивай агрессивные командные ретейки."
            else:
                base_text = f"Крепкая карта {mname} в пуле (винрейт {wr}%, HLTV {hltv}, ADR {adr}). Хорошая реализация эпизодов на ключевых точках. Сохраняй хладнокровие и балансируй агрессию."
        else:
            base_text = f"Основная карта {mname} по наигрышу в пуле (винрейт {wr}%, HLTV {hltv}, ADR {adr}). Потенциал на карте высокий, но пока не хватает командной плотности при ретейках и разменах. Работай над дефолтным позиционированием."
        return base_text + role_tip
    else:
        # Для худшей карты (Криптонита)
        if fd > fk and (fd >= 2 or fd >= fk * 1.5):
            case = "first_deaths"
        elif kast < 72.0:
            case = "low_kast"
        elif util < 8.0 and tot >= 2:
            case = "low_utility"
        elif adr >= 85.0 and wr < 40.0:
            case = "unconverted_carry"
        elif adr < 65.0 or hs < 35.0:
            case = "low_firepower"
        else:
            case = "general"
            
        if k_data and case in k_data["weakness_advices"]:
            base_text = k_data["weakness_advices"][case].format(
                wr=wr, hltv=hltv, adr=adr, kd=kd, kast=kast, hs=hs, fk=fk, fd=fd, util=util, awp=awp, name=mname
            )
        else:
            base_text = f"Главная зона роста в пуле на {mname} (винрейт {wr}%, HLTV {hltv}, ADR {adr}). На этой карте не хватает позиционной плотности и командных разменов. Рекомендуется глубже разобрать раскидки и избегать открытых соло-дуэлей."
        return base_text + role_tip

def analyze_map_performance(player_matches: list[dict], player_style: list[str] = None, player_ratings: dict = None, player_metrics: dict = None) -> dict:
    """
    Анализирует результативность игрока на всех картах:
    - Вычисляет винрейт, средний ADR, средний HLTV 2.0, K/D, KAST, HS%, First Kills/Deaths, урон гранатами.
    - Определяет Сигнатурную (любимую) карту и Криптонит (худшую карту).
    - Генерирует глубокие персонализированные тактические советы с учетом локаций карты и роли игрока.
    """
    maps = defaultdict(list)
    for m in player_matches:
        raw_m = str(m.get("map", "")).lower().strip()
        if not raw_m.startswith("de_"):
            raw_m = f"de_{raw_m}"
        maps[raw_m].append(m)
        
    all_maps = []
    for map_id, m_list in maps.items():
        disp = MAP_DISPLAY_NAMES.get(map_id, map_id.replace("de_", "").capitalize())
        icon = MAP_ICONS.get(map_id, f"map_icon_{map_id}.svg")
        tot = len(m_list)
        wins = sum(1 for m in m_list if m.get("is_win") or m.get("team_result") == "win")
        losses = sum(1 for m in m_list if m.get("is_loss") or m.get("team_result") == "loss")
        win_rate = round((wins / max(1, tot)) * 100, 1)
        adrs = [m.get("adr", 0.0) for m in m_list if "adr" in m]
        avg_adr = round(sum(adrs) / len(adrs), 1) if adrs else 0.0
        hltvs = [m.get("hltv_rating", 1.0) for m in m_list]
        avg_hltv = round(sum(hltvs) / len(hltvs), 2) if hltvs else 1.0
        tot_k = sum(m.get("kills", 0) for m in m_list)
        tot_d = sum(m.get("deaths", 0) for m in m_list)
        kd = round(tot_k / max(1, tot_d), 2)
        
        kasts = [m.get("kast", 0.0) for m in m_list if "kast" in m and m.get("kast") is not None]
        avg_kast = round(sum(kasts) / len(kasts), 1) if kasts else 70.0
        
        hs_list = [m.get("hs_percent", 0.0) for m in m_list if "hs_percent" in m and m.get("hs_percent") is not None]
        avg_hs = round(sum(hs_list) / len(hs_list), 1) if hs_list else 40.0
        
        tot_fk = sum(m.get("first_kills", 0) for m in m_list)
        tot_fd = sum(m.get("first_deaths", 0) for m in m_list)
        
        tot_util = sum(m.get("utility_damage", 0) for m in m_list)
        avg_util = round(tot_util / max(1, tot), 1)
        
        tot_flashes = sum(m.get("flash_assists", 0) for m in m_list)
        avg_flashes = round(tot_flashes / max(1, tot), 1)
        
        awp_k = 0
        rifle_k = 0
        for m in m_list:
            wk = m.get("weapon_kills", {})
            if isinstance(wk, dict):
                awp_k += wk.get("awp", 0)
                rifle_k += wk.get("ak47", 0) + wk.get("m4a1_silencer", 0) + wk.get("m4a1", 0) + wk.get("galilar", 0) + wk.get("famas", 0)
        
        # Интегральный скор карты (баланс винрейта и личного перформанса)
        score = win_rate * 0.5 + (avg_hltv / 1.3 * 100) * 0.5
        
        all_maps.append({
            "map": map_id,
            "name": disp,
            "icon": icon,
            "matches": tot,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "avg_adr": avg_adr,
            "avg_hltv": avg_hltv,
            "avg_kd": kd,
            "avg_kast": avg_kast,
            "avg_hs": avg_hs,
            "first_kills": tot_fk,
            "first_deaths": tot_fd,
            "avg_util": avg_util,
            "avg_flashes": avg_flashes,
            "awp_kills": awp_k,
            "rifle_kills": rifle_k,
            "score": score
        })
        
    if not all_maps:
        return {"all_maps": [], "favorite_map": None, "kryptonite_map": None, "best_map": "Н/Д", "worst_map": "Н/Д"}
        
    # Приоритет картам с 2+ играми для определения фаворита и криптонита
    multi_maps = [m for m in all_maps if m["matches"] >= 2]
    fav_pool = multi_maps if multi_maps else all_maps
    favorite = dict(max(fav_pool, key=lambda x: (x["score"], x["matches"])))
    
    other_maps = [m for m in all_maps if m["map"] != favorite["map"]]
    if other_maps:
        worst_pool = [m for m in other_maps if m["matches"] >= 2] or other_maps
        kryptonite = dict(min(worst_pool, key=lambda x: (x["score"], -x["matches"])))
    else:
        kryptonite = None
        
    # Персональные тактические рекомендации
    if favorite:
        favorite["advice"] = _generate_map_advice(favorite, is_favorite=True, player_style=player_style, player_ratings=player_ratings)
        
    if kryptonite:
        kryptonite["advice"] = _generate_map_advice(kryptonite, is_favorite=False, player_style=player_style, player_ratings=player_ratings)
        
    all_maps.sort(key=lambda x: (-x["matches"], -x["avg_hltv"]))
    
    return {
        "all_maps": all_maps,
        "favorite_map": favorite,
        "kryptonite_map": kryptonite,
        "best_map": favorite["name"] if favorite else "Н/Д",
        "worst_map": kryptonite["name"] if kryptonite else "Н/Д"
    }

def calculate_archetype_matrix(metrics: dict, style: list[str]) -> dict:
    """
    Рассчитывает 2D координаты стиля игры игрока (HLTV Style Matrix):
    - Ось X: Агрессивность / Риск (-100 = Пассивный сейв / Опорник, +100 = Агрессивный энтри / W-key)
    - Ось Y: Роль / Фокус (-100 = Командный саппорт / Разменщик, +100 = Звездный соло-фраггер)
    """
    fkr = float(metrics.get("first_kill_rate", 10.0) or 10.0)
    surv = float(metrics.get("survival_rate", 30.0) or 30.0)
    oiv = float(metrics.get("opening_involvement", 0.20) or 0.20)
    
    x_val = (oiv - 0.20) * 350 + (fkr - 10.0) * 3.0 - (surv - 30.0) * 1.5
    x = round(max(-85.0, min(85.0, x_val)), 1)
    
    adr = float(metrics.get("adr", 70.0) or 70.0)
    hs = float(metrics.get("hs_percent", 35.0) or 35.0)
    ud = float(metrics.get("utility_damage_per_round", 8.0) or 8.0)
    fa = float(metrics.get("flash_assists_per_match", 0.5) or 0.5)
    tr = float(metrics.get("trade_rate", 20.0) or 20.0)
    
    y_val = (adr - 75.0) * 1.4 + (hs - 40.0) * 0.6 - (ud - 8.0) * 2.5 - (fa - 0.5) * 12.0 - (tr - 22.0) * 1.0
    y = round(max(-85.0, min(85.0, y_val)), 1)
    
    if x >= 15 and y >= 15:
        title = "Агрессивный соло-фраггер"
        desc = "Высокий опенинг-напор и ставка на победу в прямых огневых дуэлях"
    elif x >= 15 and y < 15:
        title = "Агрессивный спейсмейкер"
        desc = "Вскрывает рубежи обороны и создает оперативный простор для команды"
    elif x < -15 and y >= 15:
        title = "Скрытный снайпер / Люркер"
        desc = "Хладнокровный отлов вражеских перетяжек и игра на поздних таймингах"
    elif x < -15 and y < -15:
        title = "Железный саппорт-опорник"
        desc = "Максимальная командная дисциплина, грамотная утилита и удержание сайта"
    elif abs(x) < 15 and y >= 15:
        title = "Основной рифлер"
        desc = "Стабильный огневой костяк команды в ключевых стрелковых столкновениях"
    elif abs(x) < 15 and y < -15:
        title = "Командный разменщик"
        desc = "Держится вторым темпом за энтри и гарантирует моментальный рефраг"
    else:
        title = "Универсальный тактик"
        desc = "Сбалансированная и гибкая игра под меняющуюся ситуацию раунда"
        
    return {
        "x": x,
        "y": y,
        "title": title,
        "desc": desc,
        "primary_style": style[0] if style else "Универсал"
    }

def calculate_player_momentum(career_avg_hltv: float, session_progress: dict | None) -> dict:
    """
    Рассчитывает барометр формы крайней сессии относительно средней карьеры игрока.
    """
    if not session_progress:
        return {
            "status": "stable",
            "delta": 0.0,
            "icon": "⚖️",
            "label": "Стабильно (±0.00)",
            "badge_class": "momentum-stable",
            "session_hltv": career_avg_hltv,
            "career_hltv": career_avg_hltv
        }
    
    curr = session_progress.get("current") or session_progress.get("current_session") or {}
    sess_hltv = curr.get("hltv", career_avg_hltv)
    delta = round(sess_hltv - career_avg_hltv, 2)
    
    if delta >= 0.25:
        status = "on_fire"
        icon = "🔥"
        label = f"В огне (+{delta:.2f})"
        badge_class = "momentum-fire"
    elif delta >= 0.05:
        status = "gaining"
        icon = "📈"
        label = f"На подъёме (+{delta:.2f})"
        badge_class = "momentum-gaining"
    elif delta >= -0.05:
        status = "stable"
        icon = "⚖️"
        label = f"Стабильно ({delta:+.2f})"
        badge_class = "momentum-stable"
    else:
        status = "cooling"
        icon = "📉"
        label = f"Спад ({delta:.2f})"
        badge_class = "momentum-cooling"
        
    return {
        "status": status,
        "delta": delta,
        "icon": icon,
        "label": label,
        "badge_class": badge_class,
        "session_hltv": sess_hltv,
        "career_hltv": career_avg_hltv
    }

def _build_tiered_achievement(
    id_str: str,
    title: str,
    icon: str,
    tier: int,
    thresholds: list,
    descriptions: list,
    current_val: float | int | list,
    unit: str = "",
    custom_progress_texts: list | str = None
) -> dict:
    """
    Сборка 3-уровневого достижения со строгой последовательной прогрессией (Бронза ➔ Серебро ➔ Золото),
    3 звездами с цветовой индикацией, расчетом прогресса до СЛЕДУЮЩЕГО целевого ранга и начислением очков славы.
    """
    tier = max(0, min(3, int(tier)))
    unlocked = (tier >= 1)
    is_max = (tier == 3)

    # Очки славы: 0 = 0, Бронза = 100, Серебро = 250, Золото = 500
    points_map = {0: 0, 1: 100, 2: 250, 3: 500}
    current_points = points_map[tier]
    max_points = 500

    rank_titles = {
        0: "Не получено",
        1: "Бронза 🥉",
        2: "Серебро 🥈",
        3: "Золото 🥇 (МАКС)"
    }

    # 3 звезды (пустая серая ☆, бронзовая ★, серебряная ★, золотая ★) с поддержкой кастомных бэйджей
    tier_keys = ["bronze", "silver", "gold"]
    tier_colors = ["#d97706", "#cbd5e1", "#fbbf24"]
    tier_labels = ["Бронза", "Серебро", "Золото"]
    stars_data = []
    for lvl in range(1, 4):
        is_u = (tier >= lvl)
        t_key = tier_keys[lvl - 1]
        stars_data.append({
            "level": lvl,
            "name": tier_labels[lvl - 1],
            "tier_key": t_key,
            "unlocked": is_u,
            "symbol": "★" if is_u else "☆",
            "color_class": f"star-badge-{t_key} is-unlocked" if is_u else "star-badge-locked is-locked",
            "css_color": tier_colors[lvl - 1] if is_u else "#64748b"
        })
    stars_symbol_str = ("★" if tier >= 1 else "☆") + ("★" if tier >= 2 else "☆") + ("★" if tier >= 3 else "☆")

    # Индикаторы уровней (пипы)
    pips = [
        {"level": 1, "name": "Бронза", "status": "completed" if tier >= 1 else "locked", "star": "★" if tier >= 1 else "☆", "color": "#d97706" if tier >= 1 else "#64748b"},
        {"level": 2, "name": "Серебро", "status": "completed" if tier >= 2 else "locked", "star": "★" if tier >= 2 else "☆", "color": "#cbd5e1" if tier >= 2 else "#64748b"},
        {"level": 3, "name": "Золото", "status": "completed" if tier >= 3 else "locked", "star": "★" if tier >= 3 else "☆", "color": "#fbbf24" if tier >= 3 else "#64748b"},
    ]

    # Целевой индекс для следующего уровня (0: Бронза, 1: Серебро, 2: Золото)
    target_idx = min(2, tier)
    target_thresh = thresholds[target_idx]

    # Извлечение текущего значения для целевого уровня
    if isinstance(current_val, (list, tuple)):
        c_val = current_val[target_idx] if len(current_val) > target_idx else current_val[-1]
    else:
        c_val = current_val

    if is_max:
        prog_pct = 100.0
        prog_val = target_thresh
        prog_max = target_thresh
        prog_text = "МАКСИМАЛЬНЫЙ РАНГ 🥇"
        next_goal = "Все 3 уровня успешно получены! Легендарный ранг 🥇"
    else:
        prog_val = round(float(c_val), 1) if isinstance(c_val, float) else c_val
        prog_max = target_thresh
        if prog_max > 0:
            prog_pct = round(max(0.0, min(100.0, (float(prog_val) / float(prog_max)) * 100.0)), 1)
        else:
            prog_pct = 0.0

        if custom_progress_texts:
            if isinstance(custom_progress_texts, (list, tuple)) and len(custom_progress_texts) > target_idx:
                prog_text = custom_progress_texts[target_idx]
            else:
                prog_text = str(custom_progress_texts)
        elif unit == "%":
            prog_text = f"{prog_val}% / {prog_max}%"
        elif unit:
            prog_text = f"{prog_val} / {prog_max} {unit}"
        else:
            prog_text = f"{prog_val} / {prog_max}"

        tier_prefixes = ["Цель (Бронза 🥉):", "Цель (Серебро 🥈):", "Цель (Золото 🥇):"]
        next_goal = f"{tier_prefixes[tier]} {descriptions[tier]}"

    desc = descriptions[tier - 1] if tier >= 1 else descriptions[0]

    return {
        "id": id_str,
        "title": title,
        "icon": icon,
        "tier": tier,
        "max_tier": 3,
        "unlocked": unlocked,
        "is_max": is_max,
        "points": current_points,
        "max_points": max_points,
        "stars": stars_symbol_str,
        "stars_data": stars_data,
        "tier_name": rank_titles[tier],
        "pips": pips,
        "desc": desc,
        "next_goal": next_goal,
        "progress_val": prog_val,
        "progress_max": prog_max,
        "progress_pct": prog_pct,
        "progress": prog_text,
        "progress_text": prog_text
    }


def calculate_player_achievements(
    metrics: dict,
    overall_stats: dict,
    mmr_info: dict,
    momentum_info: dict,
    matches: list = None,
    ratings: dict = None,
    map_perf: dict = None,
    special_stats: dict = None,
    connections: dict = None
) -> tuple[list[dict], dict]:
    """
    Рассчитывает 30 соревновательных 3-уровневых достижений игрока (Бронза 🥉 / Серебро 🥈 / Золото 🥇)
    с начислением очков славы (до 15 000 Glory Points), 3-звездочной индикацией и привязкой к квестам.
    20 навыковых ачивок (Часть А) + 10 хайлайт/фановых ачивок (Часть Б).
    """
    achievements = []
    matches = matches or []
    ratings = ratings or {}
    map_perf = map_perf or {}
    special_stats = special_stats or {}
    connections = connections or {}

    tot_m = overall_stats.get("total_matches", len(matches))
    tk = overall_stats.get("total_kills", 0)

    # Статистика из матчей и истории
    knife_zeus_total = special_stats.get("knife_kills", 0) + special_stats.get("taser_kills", 0)
    multi_kz_matches = special_stats.get("multi_kz_matches", 0)
    taser_kills = special_stats.get("taser_kills", 0)
    if not knife_zeus_total and matches:
        for m in matches:
            wk = m.get("weapon_kills", {})
            kz = wk.get("knife", 0) + wk.get("taser", 0) + wk.get("zeus", 0)
            knife_zeus_total += kz
            if kz >= 2:
                multi_kz_matches += 1
            taser_kills += wk.get("taser", 0) + wk.get("zeus", 0)

    thrusmoke_kills = special_stats.get("thrusmoke", 0)
    wild_west_kills = special_stats.get("wild_west", 0)
    shotgun_kills = special_stats.get("shotgun", 0)
    blind_rage_kills = special_stats.get("blind_rage", 0)
    aces_cnt = special_stats.get("aces", 0)
    defuses_cnt = special_stats.get("defuses", 0)
    comebacks_cnt = special_stats.get("comebacks", 0)
    nemesis_matches = special_stats.get("nemesis_matches", 0)
    save_rounds_cnt = special_stats.get("save_rounds", 0)
    zero_fd_matches = special_stats.get("zero_fd_matches", sum(1 for m in matches if m.get("first_deaths", 0) == 0))
    matches_25k = special_stats.get("matches_25k", sum(1 for m in matches if m.get("kills", 0) >= 25))
    high_hltv_matches = special_stats.get("high_hltv_matches", sum(1 for h in mmr_info.get("history", []) if h.get("hltv", 0.0) >= 1.35))

    # =========================================================================
    # ЧАСТЬ А: 20 НАВЫКОВЫХ АЧИВОК (ПРИВЯЗКА К 10 КЛЮЧЕВЫМ НАВЫКАМ)
    # ПРИНЦИП: Не гринд времени, а матчи с высоким качеством (1 -> 3 -> 5 матчей)
    # =========================================================================

    # 1. 🎯 «One-Tap Хирург» (Aim)
    # Пороги: 🥉 1 матч (HS >= 50%) | 🥈 3 матча (HS >= 55%) | 🥇 5 матчей (HS >= 60%) при мин. 15 фрагах
    m_hs_50 = sum(1 for m in matches if m.get("kills", 0) >= 15 and m.get("hs_percent", 0.0) >= 50.0)
    m_hs_55 = sum(1 for m in matches if m.get("kills", 0) >= 15 and m.get("hs_percent", 0.0) >= 55.0)
    m_hs_60 = sum(1 for m in matches if m.get("kills", 0) >= 15 and m.get("hs_percent", 0.0) >= 60.0)
    t_hs = 0
    if m_hs_50 >= 1:
        t_hs = 1
        if m_hs_55 >= 3:
            t_hs = 2
            if m_hs_60 >= 5:
                t_hs = 3
    achievements.append(_build_tiered_achievement(
        "aim_onetap", "One-Tap Хирург", "🎯", t_hs,
        [1, 3, 5],
        [
            "1 матч с HS% >= 50.0% (при мин. 15 фрагах)",
            "3 матча с HS% >= 55.0% (при мин. 15 фрагах)",
            "5 матчей с HS% >= 60.0% (при мин. 15 фрагах)"
        ],
        [m_hs_50, m_hs_55, m_hs_60], "матчей",
        custom_progress_texts=[
            f"{m_hs_50} / 1 матчей (HS >= 50%, 15+K)",
            f"{m_hs_55} / 3 матчей (HS >= 55%, 15+K)",
            f"{m_hs_60} / 5 матчей (HS >= 60%, 15+K)"
        ]
    ))

    # 2. 💥 «Огневой каток» (Aim)
    # Пороги: 🥉 1 матч (ADR >= 85.0) | 🥈 3 матча (ADR >= 95.0) | 🥇 5 матчей (ADR >= 105.0)
    m_adr_85 = sum(1 for m in matches if m.get("adr", 0.0) >= 85.0)
    m_adr_95 = sum(1 for m in matches if m.get("adr", 0.0) >= 95.0)
    m_adr_105 = sum(1 for m in matches if m.get("adr", 0.0) >= 105.0)
    t_adr = 0
    if m_adr_85 >= 1:
        t_adr = 1
        if m_adr_95 >= 3:
            t_adr = 2
            if m_adr_105 >= 5:
                t_adr = 3
    achievements.append(_build_tiered_achievement(
        "aim_damage_roller", "Огневой каток", "💥", t_adr,
        [1, 3, 5],
        [
            "1 матч со средним уроном ADR >= 85.0",
            "3 матча со средним уроном ADR >= 95.0",
            "5 матчей со средним уроном ADR >= 105.0"
        ],
        [m_adr_85, m_adr_95, m_adr_105], "матчей",
        custom_progress_texts=[
            f"{m_adr_85} / 1 матчей (ADR >= 85)",
            f"{m_adr_95} / 3 матчей (ADR >= 95)",
            f"{m_adr_105} / 5 матчей (ADR >= 105)"
        ]
    ))

    # 3. 👻 «Призрак выживания» (Positioning)
    # Пороги: 🥉 1 матч (выживаемость >= 40.0% или deaths <= 10) | 🥈 3 матча (>= 45.0% или deaths <= 10) | 🥇 5 матчей (>= 50.0% или deaths <= 10) при мин. 16 раундах
    def _surv_check(m, min_pct):
        rc = m.get("rounds_count") or (m.get("score_team1", 0) + m.get("score_team2", 0)) or 20
        d = m.get("deaths", 0)
        sr = ((rc - d) / max(1, rc)) * 100
        return rc >= 16 and (sr >= min_pct or d <= 10)

    m_surv_40 = sum(1 for m in matches if _surv_check(m, 40.0))
    m_surv_45 = sum(1 for m in matches if _surv_check(m, 45.0))
    m_surv_50 = sum(1 for m in matches if _surv_check(m, 50.0))
    t_surv = 0
    if m_surv_40 >= 1:
        t_surv = 1
        if m_surv_45 >= 3:
            t_surv = 2
            if m_surv_50 >= 5:
                t_surv = 3
    achievements.append(_build_tiered_achievement(
        "pos_ghost", "Призрак выживания", "👻", t_surv,
        [1, 3, 5],
        [
            "1 матч с выживаемостью >= 40.0% (или <= 10 смертей)",
            "3 матча с выживаемостью >= 45.0% (или <= 10 смертей)",
            "5 матчей с выживаемостью >= 50.0% (или <= 10 смертей)"
        ],
        [m_surv_40, m_surv_45, m_surv_50], "матчей",
        custom_progress_texts=[
            f"{m_surv_40} / 1 матчей (выживание >= 40% / <=10 D)",
            f"{m_surv_45} / 3 матчей (выживание >= 45% / <=10 D)",
            f"{m_surv_50} / 5 матчей (выживание >= 50% / <=10 D)"
        ]
    ))

    # 4. 🛡️ «Непробиваемый якорь» (Positioning)
    # Пороги: 🥉 1 матч (Positioning rating >= 7.0) | 🥈 3 матча (>= 7.5) | 🥇 5 матчей (>= 8.0)
    # Оценивается по качеству матчей с высоким баллом (score_10 >= 7.0/7.5/8.0 при K/D >= 1.15)
    def _anchor_check(m, min_score):
        s10 = m.get("score_10", 5.0)
        kd = m.get("kills", 0) / max(1, m.get("deaths", 1))
        return s10 >= min_score and kd >= 1.10

    m_anc_70 = sum(1 for m in matches if _anchor_check(m, 7.0))
    m_anc_75 = sum(1 for m in matches if _anchor_check(m, 7.5))
    m_anc_80 = sum(1 for m in matches if _anchor_check(m, 8.0))
    t_anc = 0
    if m_anc_70 >= 1:
        t_anc = 1
        if m_anc_75 >= 3:
            t_anc = 2
            if m_anc_80 >= 5:
                t_anc = 3
    achievements.append(_build_tiered_achievement(
        "pos_anchor", "Непробиваемый якорь", "🛡️", t_anc,
        [1, 3, 5],
        [
            "1 матч с оценкой позиции >= 7.0 (K/D >= 1.10)",
            "3 матча с оценкой позиции >= 7.5 (K/D >= 1.10)",
            "5 матчей с оценкой позиции >= 8.0 (K/D >= 1.10)"
        ],
        [m_anc_70, m_anc_75, m_anc_80], "матчей",
        custom_progress_texts=[
            f"{m_anc_70} / 1 матчей (рейтинг позиции >= 7.0)",
            f"{m_anc_75} / 3 матчей (рейтинг позиции >= 7.5)",
            f"{m_anc_80} / 5 матчей (рейтинг позиции >= 8.0)"
        ]
    ))

    # 5. 💡 «Ослепительный дуэт» (Utility)
    # Пороги: 🥉 1 матч с 3+ флеш-ассистами | 🥈 3 матча с 4+ флеш-ассистами | 🥇 5 матчей с 5+ флеш-ассистами
    m_fa_3 = sum(1 for m in matches if m.get("flash_assists", 0) >= 3)
    m_fa_4 = sum(1 for m in matches if m.get("flash_assists", 0) >= 4)
    m_fa_5 = sum(1 for m in matches if m.get("flash_assists", 0) >= 5)
    t_fa = 0
    if m_fa_3 >= 1:
        t_fa = 1
        if m_fa_4 >= 3:
            t_fa = 2
            if m_fa_5 >= 5:
                t_fa = 3
    achievements.append(_build_tiered_achievement(
        "util_flash_duo", "Ослепительный дуэт", "💡", t_fa,
        [1, 3, 5],
        [
            "1 матч с >= 3 флеш-ассистами для команды",
            "3 матча с >= 4 флеш-ассистами для команды",
            "5 матчей с >= 5 флеш-ассистами для команды"
        ],
        [m_fa_3, m_fa_4, m_fa_5], "матчей",
        custom_progress_texts=[
            f"{m_fa_3} / 1 матчей (3+ flash assists)",
            f"{m_fa_4} / 3 матчей (4+ flash assists)",
            f"{m_fa_5} / 5 матчей (5+ flash assists)"
        ]
    ))

    # 6. 🧨 «Артиллерийский полк» (Utility)
    # Пороги: 🥉 1 матч (120+ HP утилиты) | 🥈 3 матча (180+ HP утилиты) | 🥇 5 матчей (250+ HP утилиты)
    m_ud_120 = sum(1 for m in matches if m.get("utility_damage", 0) >= 120)
    m_ud_180 = sum(1 for m in matches if m.get("utility_damage", 0) >= 180)
    m_ud_250 = sum(1 for m in matches if m.get("utility_damage", 0) >= 250)
    t_ud = 0
    if m_ud_120 >= 1:
        t_ud = 1
        if m_ud_180 >= 3:
            t_ud = 2
            if m_ud_250 >= 5:
                t_ud = 3
    achievements.append(_build_tiered_achievement(
        "util_artillery", "Артиллерийский полк", "🧨", t_ud,
        [1, 3, 5],
        [
            "1 матч с >= 120 HP урона гранатами",
            "3 матча с >= 180 HP урона гранатами",
            "5 матчей с >= 250 HP урона гранатами"
        ],
        [m_ud_120, m_ud_180, m_ud_250], "матчей",
        custom_progress_texts=[
            f"{m_ud_120} / 1 матчей (120+ HP utility)",
            f"{m_ud_180} / 3 матчей (180+ HP utility)",
            f"{m_ud_250} / 5 матчей (250+ HP utility)"
        ]
    ))

    # 7. 🧱 «Железный занавес» (Game Sense)
    # Пороги: 🥉 1 матч с KAST >= 75.0% | 🥈 3 матча с KAST >= 80.0% | 🥇 5 матчей с KAST >= 85.0%
    m_kast_75 = sum(1 for m in matches if m.get("kast", 0.0) >= 75.0)
    m_kast_80 = sum(1 for m in matches if m.get("kast", 0.0) >= 80.0)
    m_kast_85 = sum(1 for m in matches if m.get("kast", 0.0) >= 85.0)
    t_kast = 0
    if m_kast_75 >= 1:
        t_kast = 1
        if m_kast_80 >= 3:
            t_kast = 2
            if m_kast_85 >= 5:
                t_kast = 3
    achievements.append(_build_tiered_achievement(
        "gs_iron_curtain", "Железный занавес", "🧱", t_kast,
        [1, 3, 5],
        [
            "1 матч с показателем KAST >= 75.0%",
            "3 матча с показателем KAST >= 80.0%",
            "5 матчей с показателем KAST >= 85.0%"
        ],
        [m_kast_75, m_kast_80, m_kast_85], "матчей",
        custom_progress_texts=[
            f"{m_kast_75} / 1 матчей (KAST >= 75%)",
            f"{m_kast_80} / 3 матчей (KAST >= 80%)",
            f"{m_kast_85} / 5 матчей (KAST >= 85%)"
        ]
    ))

    # 8. 👁️ «Шестое чувство» (Game Sense)
    # Пороги: 🥉 1 матч с 3+ тактическими фрагами (прострелы/дым) | 🥈 3 матча | 🥇 5 матчей
    m_tact_3 = sum(1 for m in matches if m.get("tactical_kills", 0) >= 3 or (m.get("weapon_kills", {}).get("thrusmoke", 0) >= 3))
    # Также проверяем суммарные спец-события
    if m_tact_3 == 0 and thrusmoke_kills >= 3:
        m_tact_3 = min(len(matches), thrusmoke_kills // 2 or 1)
    t_smk = 0
    if m_tact_3 >= 1:
        t_smk = 1
        if m_tact_3 >= 3:
            t_smk = 2
            if m_tact_3 >= 5:
                t_smk = 3
    achievements.append(_build_tiered_achievement(
        "gs_sixth_sense", "Шестое чувство", "👁️", t_smk,
        [1, 3, 5],
        [
            "1 матч с >= 3 тактическими фрагами сквозь смок/стены",
            "3 матча с >= 3 тактическими фрагами сквозь смок/стены",
            "5 матчей с >= 3 тактическими фрагами сквозь смок/стены"
        ],
        m_tact_3, "матчей",
        custom_progress_texts=[
            f"{m_tact_3} / 1 матчей с 3+ тактическими фрагами",
            f"{m_tact_3} / 3 матчей с 3+ тактическими фрагами",
            f"{m_tact_3} / 5 матчей с 3+ тактическими фрагами"
        ]
    ))

    # 9. ⚡ «Гроза опенингов» (Entry)
    # Пороги: 🥉 1 матч с FK-FD >= +2 (мин. 3 FK) | 🥈 3 матча с FK-FD >= +3 | 🥇 5 матчей с FK-FD >= +4
    def _fk_diff(m):
        return m.get("first_kills", 0) - m.get("first_deaths", 0)
    m_fk_2 = sum(1 for m in matches if m.get("first_kills", 0) >= 3 and _fk_diff(m) >= 2)
    m_fk_3 = sum(1 for m in matches if m.get("first_kills", 0) >= 4 and _fk_diff(m) >= 3)
    m_fk_4 = sum(1 for m in matches if m.get("first_kills", 0) >= 4 and _fk_diff(m) >= 4)
    t_fk = 0
    if m_fk_2 >= 1:
        t_fk = 1
        if m_fk_3 >= 3:
            t_fk = 2
            if m_fk_4 >= 5:
                t_fk = 3
    achievements.append(_build_tiered_achievement(
        "entry_thunder", "Гроза опенингов", "⚡", t_fk,
        [1, 3, 5],
        [
            "1 матч с чистым перевесом энтри-дуэлей (FK - FD >= +2, мин. 3 FK)",
            "3 матча с чистым перевесом энтри-дуэлей (FK - FD >= +3)",
            "5 матчей с чистым перевесом энтри-дуэлей (FK - FD >= +4)"
        ],
        [m_fk_2, m_fk_3, m_fk_4], "матчей",
        custom_progress_texts=[
            f"{m_fk_2} / 1 матчей (FK-FD >= +2, 3+ FK)",
            f"{m_fk_3} / 3 матчей (FK-FD >= +3)",
            f"{m_fk_4} / 5 матчей (FK-FD >= +4)"
        ]
    ))

    # 10. 🚪 «Штурмовой таран» (Entry)
    # Пороги: 🥉 1 матч с винрейтом энтри >= 55% (мин. 4 дуэли) | 🥈 3 матча (>= 62%) | 🥇 5 матчей (>= 70%)
    def _open_wr_check(m, min_wr):
        tot = m.get("first_kills", 0) + m.get("first_deaths", 0)
        wr = (m.get("first_kills", 0) / max(1, tot)) * 100
        return tot >= 4 and wr >= min_wr

    m_owr_55 = sum(1 for m in matches if _open_wr_check(m, 55.0))
    m_owr_62 = sum(1 for m in matches if _open_wr_check(m, 62.0))
    m_owr_70 = sum(1 for m in matches if _open_wr_check(m, 70.0))
    t_ram = 0
    if m_owr_55 >= 1:
        t_ram = 1
        if m_owr_62 >= 3:
            t_ram = 2
            if m_owr_70 >= 5:
                t_ram = 3
    achievements.append(_build_tiered_achievement(
        "entry_battering_ram", "Штурмовой таран", "🚪", t_ram,
        [1, 3, 5],
        [
            "1 матч с винрейтом опенинг-дуэлей >= 55.0% (от 4 дуэлей)",
            "3 матча с винрейтом опенинг-дуэлей >= 62.0% (от 4 дуэлей)",
            "5 матчей с винрейтом опенинг-дуэлей >= 70.0% (от 4 дуэлей)"
        ],
        [m_owr_55, m_owr_62, m_owr_70], "матчей",
        custom_progress_texts=[
            f"{m_owr_55} / 1 матчей (WR опенингов >= 55%)",
            f"{m_owr_62} / 3 матчей (WR опенингов >= 62%)",
            f"{m_owr_70} / 5 матчей (WR опенингов >= 70%)"
        ]
    ))

    # 11. 🔄 «Кровная месть» (Trading)
    # Пороги: 🥉 1 матч с 3+ разменами | 🥈 3 матча с 4+ разменами | 🥇 5 матчей с 5+ разменами
    m_tr_3 = sum(1 for m in matches if m.get("trades", 0) >= 3)
    m_tr_4 = sum(1 for m in matches if m.get("trades", 0) >= 4)
    m_tr_5 = sum(1 for m in matches if m.get("trades", 0) >= 5)
    t_tr = 0
    if m_tr_3 >= 1:
        t_tr = 1
        if m_tr_4 >= 3:
            t_tr = 2
            if m_tr_5 >= 5:
                t_tr = 3
    achievements.append(_build_tiered_achievement(
        "trade_blood_revenge", "Кровная месть", "🔄", t_tr,
        [1, 3, 5],
        [
            "1 матч с >= 3 успешными разменами тиммейтов",
            "3 матча с >= 4 успешными разменами тиммейтов",
            "5 матчей с >= 5 успешными разменами тиммейтов"
        ],
        [m_tr_3, m_tr_4, m_tr_5], "матчей",
        custom_progress_texts=[
            f"{m_tr_3} / 1 матчей (3+ размена)",
            f"{m_tr_4} / 3 матчей (4+ размена)",
            f"{m_tr_5} / 5 матчей (5+ разменов)"
        ]
    ))

    # 12. 👥 «Идеальный напарник» (Trading)
    # Пороги: 🥉 1 матч с Trade Rate >= 25.0% | 🥈 3 матча (>= 32.0%) | 🥇 5 матчей (>= 40.0%) при мин. 10 фрагах
    def _trade_rate_check(m, min_rate):
        k = m.get("kills", 0)
        tr = m.get("trades", 0)
        rate = (tr / max(1, k)) * 100
        return k >= 10 and rate >= min_rate

    m_trr_25 = sum(1 for m in matches if _trade_rate_check(m, 25.0))
    m_trr_32 = sum(1 for m in matches if _trade_rate_check(m, 32.0))
    m_trr_40 = sum(1 for m in matches if _trade_rate_check(m, 40.0))
    t_wman = 0
    if m_trr_25 >= 1:
        t_wman = 1
        if m_trr_32 >= 3:
            t_wman = 2
            if m_trr_40 >= 5:
                t_wman = 3
    achievements.append(_build_tiered_achievement(
        "trade_wingman", "Идеальный напарник", "👥", t_wman,
        [1, 3, 5],
        [
            "1 матч с долей разменов (Trade Rate) >= 25.0% (от 10 фрагов)",
            "3 матча с долей разменов (Trade Rate) >= 32.0% (от 10 фрагов)",
            "5 матчей с долей разменов (Trade Rate) >= 40.0% (от 10 фрагов)"
        ],
        [m_trr_25, m_trr_32, m_trr_40], "матчей",
        custom_progress_texts=[
            f"{m_trr_25} / 1 матчей (Trade Rate >= 25%)",
            f"{m_trr_32} / 3 матчей (Trade Rate >= 32%)",
            f"{m_trr_40} / 5 матчей (Trade Rate >= 40%)"
        ]
    ))

    # 13. 👑 «Клатч-министр» (Clutch)
    # Пороги: 🥉 1 матч с 2+ клатчами | 🥈 3 матча с 2+ клатчами | 🥇 5 матчей с 2+ клатчами (или 1 матч с 3+ клатчами)
    m_cw_2 = sum(1 for m in matches if m.get("clutch_wins", 0) >= 2)
    m_cw_3 = sum(1 for m in matches if m.get("clutch_wins", 0) >= 3)
    t_cw = 0
    if m_cw_2 >= 1 or m_cw_3 >= 1:
        t_cw = 1
        if m_cw_2 >= 3 or m_cw_3 >= 1:
            t_cw = 2
            if m_cw_2 >= 5 or m_cw_3 >= 1:
                t_cw = 3
    achievements.append(_build_tiered_achievement(
        "clutch_minister", "Клатч-министр", "👑", t_cw,
        [1, 3, 5],
        [
            "1 матч с 2+ выигранными клатчами 1vX",
            "3 матча с 2+ выигранными клатчами 1vX",
            "5 матчей с 2+ клатчами (или 1 матч с 3+ клатчами 🥇)"
        ],
        m_cw_2, "матчей",
        custom_progress_texts=[
            f"{m_cw_2} / 1 матчей с 2+ клатчами",
            f"{m_cw_2} / 3 матчей с 2+ клатчами",
            f"{m_cw_2} / 5 матчей (или {m_cw_3}/1 с 3+ клатчами)"
        ]
    ))

    # 14. 🧊 «Стальные нервы» (Clutch)
    # Пороги: 🥉 1 матч со 100% клатч-винрейтом (мин. 2 из 2) | 🥈 суммарный WR >= 35.0% (от 6 попыток) | 🥇 суммарный WR >= 50.0% (от 10 попыток)
    tot_cw = overall_stats.get("total_clutch_wins", 0)
    tot_ca = overall_stats.get("total_clutch_attempts", 0)
    cwr_all = round((tot_cw / max(1, tot_ca)) * 100, 1)
    m_perfect_clutch = sum(1 for m in matches if m.get("clutch_attempts", 0) >= 2 and m.get("clutch_wins", 0) == m.get("clutch_attempts", 0))
    t_sn = 0
    if m_perfect_clutch >= 1 or (tot_ca >= 4 and cwr_all >= 30.0):
        t_sn = 1
        if tot_ca >= 6 and cwr_all >= 35.0:
            t_sn = 2
            if tot_ca >= 10 and cwr_all >= 50.0:
                t_sn = 3
    achievements.append(_build_tiered_achievement(
        "clutch_steel_nerves", "Стальные нервы", "🧊", t_sn,
        [1, 35.0, 50.0],
        [
            "1 матч со 100% успехом в клатчах (мин. 2 из 2) или WR >= 30%",
            "Винрейт в клатчах >= 35.0% (при мин. 6 попытках)",
            "Винрейт в клатчах >= 50.0% (при мин. 10 попытках)"
        ],
        [m_perfect_clutch, cwr_all, cwr_all], "%",
        custom_progress_texts=[
            f"{m_perfect_clutch} / 1 матчей со 100% клатчами (2/2)",
            f"{cwr_all}% / 35.0% ({tot_ca}/6 клатч-попыток)",
            f"{cwr_all}% / 50.0% ({tot_ca}/10 клатч-попыток)"
        ]
    ))

    # 15. 🧘 «Дзен спецназа» (Discipline)
    # Пороги: 🥉 1 матч с 0 первых смертей (FD = 0, мин. 16 раундов) | 🥈 3 матча | 🥇 5 матчей
    m_zero_fd = sum(1 for m in matches if m.get("first_deaths", 0) == 0 and (m.get("rounds_count") or (m.get("score_team1", 0) + m.get("score_team2", 0)) or 20) >= 16)
    if m_zero_fd == 0:
        m_zero_fd = zero_fd_matches
    t_zen = 0
    if m_zero_fd >= 1:
        t_zen = 1
        if m_zero_fd >= 3:
            t_zen = 2
            if m_zero_fd >= 5:
                t_zen = 3
    achievements.append(_build_tiered_achievement(
        "disc_zen", "Дзен спецназа", "🧘", t_zen,
        [1, 3, 5],
        [
            "1 матч без единой первой смерти (0 FD, мин. 16 раундов)",
            "3 матча без единой первой смерти (0 FD, мин. 16 раундов)",
            "5 матчей без единой первой смерти (0 FD, мин. 16 раундов)"
        ],
        m_zero_fd, "матчей",
        custom_progress_texts=[
            f"{m_zero_fd} / 1 матчей с 0 первых смертей (0 FD)",
            f"{m_zero_fd} / 3 матчей с 0 первых смертей (0 FD)",
            f"{m_zero_fd} / 5 матчей с 0 первых смертей (0 FD)"
        ]
    ))

    # 16. 🎒 «Бережливый боец» (Discipline)
    # Пороги: 🥉 2 сохранения оружия в проигранных раундах | 🥈 5 сохранений | 🥇 10 сохранений
    t_frugal = 0
    if save_rounds_cnt >= 2:
        t_frugal = 1
        if save_rounds_cnt >= 5:
            t_frugal = 2
            if save_rounds_cnt >= 10:
                t_frugal = 3
    achievements.append(_build_tiered_achievement(
        "disc_frugal_fighter", "Бережливый боец", "🎒", t_frugal,
        [2, 5, 10],
        [
            "2 сохранения девайса в заведомо проигранных раундах (Saves)",
            "5 сохранений девайса в заведомо проигранных раундах (Saves)",
            "10 сохранений девайса в заведомо проигранных раундах (Saves)"
        ],
        save_rounds_cnt, "сейвов",
        custom_progress_texts=[
            f"{save_rounds_cnt} / 2 сохраненных девайсов",
            f"{save_rounds_cnt} / 5 сохраненных девайсов",
            f"{save_rounds_cnt} / 10 сохраненных девайсов"
        ]
    ))

    # 17. 💰 «Экономический диверсант» (Economy)
    # Пороги: 🥉 1 матч с K/D vs Full Buy >= 1.15 | 🥈 3 матча (>= 1.30) | 🥇 5 матчей (>= 1.50)
    m_eco_115 = sum(1 for m in matches if m.get("vs_full_buy_kd", 1.0) >= 1.15)
    m_eco_130 = sum(1 for m in matches if m.get("vs_full_buy_kd", 1.0) >= 1.30)
    m_eco_150 = sum(1 for m in matches if m.get("vs_full_buy_kd", 1.0) >= 1.50)
    # Если мало per-match данных, учитываем средний показатель vs_full_buy_kd
    if m_eco_115 == 0 and float(metrics.get("vs_full_buy_kd", 1.0) or 1.0) >= 1.15:
        m_eco_115 = min(len(matches), 2)
    t_eco = 0
    if m_eco_115 >= 1:
        t_eco = 1
        if m_eco_130 >= 3:
            t_eco = 2
            if m_eco_150 >= 5:
                t_eco = 3
    achievements.append(_build_tiered_achievement(
        "eco_saboteur", "Экономический диверсант", "💰", t_eco,
        [1, 3, 5],
        [
            "1 матч с K/D >= 1.15 против полного закупа оппонентов",
            "3 матча с K/D >= 1.30 против полного закупа оппонентов",
            "5 матчей с K/D >= 1.50 против полного закупа оппонентов"
        ],
        [m_eco_115, m_eco_130, m_eco_150], "матчей",
        custom_progress_texts=[
            f"{m_eco_115} / 1 матчей (K/D vs Full Buy >= 1.15)",
            f"{m_eco_130} / 3 матчей (K/D vs Full Buy >= 1.30)",
            f"{m_eco_150} / 5 матчей (K/D vs Full Buy >= 1.50)"
        ]
    ))

    # 18. 🔫 «Пистолетный маэстро» (Economy)
    # Пороги: 🥉 1 матч с 3+ пистолетными фрагами | 🥈 3 матча с 3+ пистолетными фрагами | 🥇 5 матчей с 3+ (или 1 матч с 5+)
    m_pk_3 = sum(1 for m in matches if m.get("pistol_round_kills", 0) >= 3)
    m_pk_5 = sum(1 for m in matches if m.get("pistol_round_kills", 0) >= 5)
    t_pk = 0
    if m_pk_3 >= 1 or m_pk_5 >= 1:
        t_pk = 1
        if m_pk_3 >= 3 or m_pk_5 >= 1:
            t_pk = 2
            if m_pk_3 >= 5 or m_pk_5 >= 1:
                t_pk = 3
    achievements.append(_build_tiered_achievement(
        "eco_pistol_maestro", "Пистолетный маэстро", "🔫", t_pk,
        [1, 3, 5],
        [
            "1 матч с >= 3 фрагами в пистолетных раундах (1 и 13)",
            "3 матча с >= 3 фрагами в пистолетных раундах (1 и 13)",
            "5 матчей с >= 3 фрагами (или 1 матч с 5+ фрагами 🥇)"
        ],
        m_pk_3, "матчей",
        custom_progress_texts=[
            f"{m_pk_3} / 1 матчей (3+ фрага в пистолетках)",
            f"{m_pk_3} / 3 матчей (3+ фрага в пистолетках)",
            f"{m_pk_3} / 5 матчей (или {m_pk_5}/1 с 5+ фрагами)"
        ]
    ))

    # 19. 🌟 «Звездный керри» (Overall Impact)
    # Пороги: 🥉 1 матч с HLTV 2.0 >= 1.35 | 🥈 3 матча с HLTV 2.0 >= 1.45 | 🥇 5 матчей с HLTV 2.0 >= 1.60
    m_hltv_135 = sum(1 for m in matches if m.get("hltv_rating", 0.0) >= 1.35)
    m_hltv_145 = sum(1 for m in matches if m.get("hltv_rating", 0.0) >= 1.45)
    m_hltv_160 = sum(1 for m in matches if m.get("hltv_rating", 0.0) >= 1.60)
    # Резервный поиск по истории mmr
    if m_hltv_135 == 0:
        m_hltv_135 = sum(1 for h in mmr_info.get("history", []) if h.get("hltv", 0.0) >= 1.35)
        m_hltv_145 = sum(1 for h in mmr_info.get("history", []) if h.get("hltv", 0.0) >= 1.45)
        m_hltv_160 = sum(1 for h in mmr_info.get("history", []) if h.get("hltv", 0.0) >= 1.60)
    t_carry = 0
    if m_hltv_135 >= 1:
        t_carry = 1
        if m_hltv_145 >= 3:
            t_carry = 2
            if m_hltv_160 >= 5:
                t_carry = 3
    achievements.append(_build_tiered_achievement(
        "impact_star_carry", "Звездный керри", "🌟", t_carry,
        [1, 3, 5],
        [
            "1 матч с соревновательным рейтингом HLTV 2.0 >= 1.35",
            "3 матча с соревновательным рейтингом HLTV 2.0 >= 1.45",
            "5 матчей с элитным рейтингом HLTV 2.0 >= 1.60"
        ],
        [m_hltv_135, m_hltv_145, m_hltv_160], "матчей",
        custom_progress_texts=[
            f"{m_hltv_135} / 1 матчей (HLTV 2.0 >= 1.35)",
            f"{m_hltv_145} / 3 матчей (HLTV 2.0 >= 1.45)",
            f"{m_hltv_160} / 5 матчей (HLTV 2.0 >= 1.60)"
        ]
    ))

    # 20. 🎩 «Бомбардир (25+ фрагов)» (Overall Impact)
    # Пороги: 🥉 1 матч с 25+ фрагами | 🥈 3 матча с 25+ фрагами | 🥇 1 матч с 30+ фрагами (или 5 матчей с 25+)
    m_kills_25 = sum(1 for m in matches if m.get("kills", 0) >= 25)
    m_kills_30 = sum(1 for m in matches if m.get("kills", 0) >= 30)
    t_bomb = 0
    if m_kills_25 >= 1 or m_kills_30 >= 1:
        t_bomb = 1
        if m_kills_25 >= 3 or m_kills_30 >= 1:
            t_bomb = 2
            if m_kills_30 >= 1 or m_kills_25 >= 5:
                t_bomb = 3
    achievements.append(_build_tiered_achievement(
        "impact_bombardier", "Бомбардир (25+ фрагов)", "🎩", t_bomb,
        [1, 3, 5],
        [
            "1 матч с 25+ фрагами на карте",
            "3 матча с 25+ фрагами на карте",
            "1 матч с 30-бомбой (30+ фрагов) или 5 матчей с 25+ фрагами 🥇"
        ],
        m_kills_25, "матчей",
        custom_progress_texts=[
            f"{m_kills_25} / 1 матчей (25+ фрагов)",
            f"{m_kills_25} / 3 матчей (25+ фрагов)",
            f"{m_kills_25} / 5 матчей (или {m_kills_30}/1 с 30+ бомбой)"
        ]
    ))

    # =========================================================================
    # ЧАСТЬ Б: 10 ФАНОВЫХ И ХАЙЛАЙТ-АЧИВОК
    # =========================================================================

    # 21. 🔪 «Мастер унижений»
    # Пороги: 🥉 5 фрагов с ножа/Zeus | 🥈 10 фрагов | 🥇 Дабл-килл (2+ в одном матче)
    t_kz = 0
    if knife_zeus_total >= 5:
        t_kz = 1
        if knife_zeus_total >= 10:
            t_kz = 2
            if multi_kz_matches >= 1:
                t_kz = 3
    achievements.append(_build_tiered_achievement(
        "fun_humiliation", "Мастер унижений", "🔪", t_kz,
        [5, 10, 1],
        [
            "5 фрагов с ножа или Zeus суммарно",
            "10 фрагов с ножа или Zeus суммарно",
            "Дабл-килл (2+ фрага с ножа/Zeus) за одну карту"
        ],
        [knife_zeus_total, knife_zeus_total, multi_kz_matches],
        "фрагов",
        custom_progress_texts=[
            f"{knife_zeus_total} / 5 фрагов с ножа/Zeus",
            f"{knife_zeus_total} / 10 фрагов с ножа/Zeus",
            f"{multi_kz_matches} / 1 матчей с дабл-киллом"
        ]
    ))

    # 22. ⚡ «Шоковая терапия»
    # Пороги: 🥉 1 фраг из Zeus | 🥈 5 фрагов | 🥇 10 фрагов
    t_taser = 0
    if taser_kills >= 1:
        t_taser = 1
        if taser_kills >= 5:
            t_taser = 2
            if taser_kills >= 10:
                t_taser = 3
    achievements.append(_build_tiered_achievement(
        "fun_taser_therapy", "Шоковая терапия", "⚡", t_taser,
        [1, 5, 10],
        [
            "1 фраг из электрошокера Zeus x27",
            "5 фрагов из электрошокера Zeus x27",
            "10 фрагов из электрошокера Zeus x27"
        ],
        taser_kills, "фрагов из Zeus"
    ))

    # 23. 🤠 «Шериф Дикого Запада»
    # Пороги: 🥉 10 хедшотов Deagle/Revolver | 🥈 20 фрагов | 🥇 30 фрагов
    t_west = 0
    if wild_west_kills >= 10:
        t_west = 1
        if wild_west_kills >= 20:
            t_west = 2
            if wild_west_kills >= 30:
                t_west = 3
    achievements.append(_build_tiered_achievement(
        "fun_wild_west", "Шериф Дикого Запада", "🤠", t_west,
        [10, 20, 30],
        [
            "10 хедшотов из Desert Eagle или фрагов из Revolver",
            "20 хедшотов из Desert Eagle или фрагов из Revolver",
            "30 хедшотов из Desert Eagle или фрагов из Revolver"
        ],
        wild_west_kills, "фрагов Deagle/Revolver"
    ))

    # 24. 🥷 «Ниндзя-сапер»
    # Пороги: 🥉 1 победный дефьюз | 🥈 3 победных дефьюза | 🥇 5 победных дефьюзов
    t_def = 0
    if defuses_cnt >= 1:
        t_def = 1
        if defuses_cnt >= 3:
            t_def = 2
            if defuses_cnt >= 5:
                t_def = 3
    achievements.append(_build_tiered_achievement(
        "fun_ninja_defuse", "Ниндзя-сапер", "🥷", t_def,
        [1, 3, 5],
        [
            "1 победный раунд с разминированием бомбы",
            "3 победных раунда с разминированием бомбы",
            "5 победных раундов с разминированием бомбы"
        ],
        defuses_cnt, "дефьюзов"
    ))

    # 25. 🚪 «Дверной звонок»
    # Пороги: 🥉 5 фрагов из дробовиков | 🥈 15 фрагов | 🥇 30 фрагов
    t_shot = 0
    if shotgun_kills >= 5:
        t_shot = 1
        if shotgun_kills >= 15:
            t_shot = 2
            if shotgun_kills >= 30:
                t_shot = 3
    achievements.append(_build_tiered_achievement(
        "fun_doorbell_shotgun", "Дверной звонок", "🚪", t_shot,
        [5, 15, 30],
        [
            "5 фрагов из дробовиков (XM1014, Nova, MAG-7, Sawed-off)",
            "15 фрагов из дробовиков (XM1014, Nova, MAG-7, Sawed-off)",
            "30 фрагов из дробовиков (XM1014, Nova, MAG-7, Sawed-off)"
        ],
        shotgun_kills, "фрагов из дробовика"
    ))

    # 26. 🕶️ «Слепая ярость»
    # Пороги: 🥉 1 фраг при содействии световой гранаты | 🥈 3 фрага | 🥇 6 фрагов
    t_blind = 0
    if blind_rage_kills >= 1:
        t_blind = 1
        if blind_rage_kills >= 3:
            t_blind = 2
            if blind_rage_kills >= 6:
                t_blind = 3
    achievements.append(_build_tiered_achievement(
        "fun_blind_rage", "Слепая ярость", "🕶️", t_blind,
        [1, 3, 6],
        [
            "1 фраг при ослеплении противника тиммейтом (assisted flash)",
            "3 фрага при ослеплении противника тиммейтом (assisted flash)",
            "6 фрагов при ослеплении противника тиммейтом (assisted flash)"
        ],
        blind_rage_kills, "фрагов с ослеплением"
    ))

    # 27. 🧱 «ВХ без читов»
    # Пороги: 🥉 2 прострела сквозь стены/смок | 🥈 5 прострелов | 🥇 10 прострелов
    t_wall = 0
    if thrusmoke_kills >= 2:
        t_wall = 1
        if thrusmoke_kills >= 5:
            t_wall = 2
            if thrusmoke_kills >= 10:
                t_wall = 3
    achievements.append(_build_tiered_achievement(
        "fun_wallbang_god", "ВХ без читов", "🧱", t_wall,
        [2, 5, 10],
        [
            "2 прострела сквозь стены или плотный дым",
            "5 прострелов сквозь стены или плотный дым",
            "10 прострелов сквозь стены или плотный дым"
        ],
        thrusmoke_kills, "прострелов"
    ))

    # 28. 💀 «Терминатор (ACE!)»
    # Пороги: 🥉 1 эйс | 🥈 2 эйса | 🥇 4 эйса
    t_ace = 0
    if aces_cnt >= 1:
        t_ace = 1
        if aces_cnt >= 2:
            t_ace = 2
            if aces_cnt >= 4:
                t_ace = 3
    achievements.append(_build_tiered_achievement(
        "fun_terminator_ace", "Терминатор (ACE!)", "💀", t_ace,
        [1, 2, 4],
        [
            "1 эйс (уничтожение всей команды соперника из 5 игроков за раунд)",
            "2 эйса (уничтожение всей команды соперника из 5 игроков за раунд)",
            "4 эйса (уничтожение всей команды соперника из 5 игроков за раунд)"
        ],
        aces_cnt, "эйсов"
    ))

    # 29. 🩸 «Кровная вендетта (Nemesis Hunter)»
    # Пороги: 🥉 1 матч с 5+ фрагами на Nemesis | 🥈 3 матча | 🥇 6 матчей
    t_nem = 0
    if nemesis_matches >= 1:
        t_nem = 1
        if nemesis_matches >= 3:
            t_nem = 2
            if nemesis_matches >= 6:
                t_nem = 3
    achievements.append(_build_tiered_achievement(
        "fun_nemesis_hunter", "Кровная вендетта (Nemesis Hunter)", "🩸", t_nem,
        [1, 3, 6],
        [
            "1 матч с 5+ убийствами своего принципиального соперника (Nemesis)",
            "3 матча с 5+ убийствами своего принципиального соперника (Nemesis)",
            "6 матчей с 5+ убийствами своего принципиального соперника (Nemesis)"
        ],
        nemesis_matches, "матчей"
    ))

    # 30. 🌪️ «Мастер камбэка»
    # Пороги: 🥉 1 волевая победа (камбэк, овертайм, разрыв <= 3) | 🥈 2 победы | 🥇 4 победы
    t_cb = 0
    if comebacks_cnt >= 1:
        t_cb = 1
        if comebacks_cnt >= 2:
            t_cb = 2
            if comebacks_cnt >= 4:
                t_cb = 3
    achievements.append(_build_tiered_achievement(
        "fun_comeback_master", "Мастер камбэка", "🌪️", t_cb,
        [1, 2, 4],
        [
            "1 волевая победа (камбэк, овертайм или клатч-финал карты)",
            "2 волевые победы (камбэк, овертайм или клатч-финал карты)",
            "4 волевые победы (камбэк, овертайм или клатч-финал карты)"
        ],
        comebacks_cnt, "волевых побед"
    ))

    # Сводная статистика достижений (Glory Summary)
    total_unlocked = sum(1 for a in achievements if a["unlocked"])
    total_points = sum(a["points"] for a in achievements)
    bronze_cnt = sum(1 for a in achievements if a["tier"] == 1)
    silver_cnt = sum(1 for a in achievements if a["tier"] == 2)
    gold_cnt = sum(1 for a in achievements if a["tier"] == 3)
    max_pts = len(achievements) * 500  # 30 * 500 = 15000

    achievements_summary = {
        "total_unlocked": total_unlocked,
        "total_count": len(achievements),
        "tier1_count": bronze_cnt,
        "tier2_count": silver_cnt,
        "tier3_count": gold_cnt,
        "bronze_count": bronze_cnt,
        "silver_count": silver_cnt,
        "gold_count": gold_cnt,
        "total_points": total_points,
        "max_points": max_pts,
        "points_pct": round((total_points / max(1, max_pts)) * 100, 1),
    }

    return achievements, achievements_summary


def analyze_pistol_rounds(player_matches: list[dict]) -> dict:
    """
    Анализирует игру в пистолетных раундах.
    """
    pistol_wins = 0
    pistol_kills = 0
    total_pistols = 0
    
    for m in player_matches:
        pr = m.get("pistol_rounds", {})
        pistol_wins += pr.get("wins", 0)
        pistol_kills += pr.get("kills", 0)
        total_pistols += pr.get("total", 0)
        
    win_rate = (pistol_wins / total_pistols * 100) if total_pistols > 0 else 0
    avg_kills = (pistol_kills / total_pistols) if total_pistols > 0 else 0
    
    return {
        "win_rate": round(win_rate, 1),
        "avg_kills": round(avg_kills, 2),
        "effectiveness": clamp(linear_interp(win_rate, 30, 60), 1.0, 10.0)
    }

def analyze_vs_economy(player_matches: list[dict], metrics: dict = None) -> dict:
    """
    Анализирует игру против различных типов экономики.
    """
    if metrics:
        return {
            "vs_full_buy_kd": round(float(metrics.get("vs_full_buy_kd", 1.0)), 2),
            "vs_force_buy_kd": round(float(metrics.get("vs_force_buy_kd", 1.1)), 2),
            "vs_eco_kd": round(float(metrics.get("vs_eco_kd", 1.3)), 2)
        }
    return {
        "vs_full_buy_kd": 1.0,
        "vs_force_buy_kd": 1.1,
        "vs_eco_kd": 1.3
    }

def format_date_display(date_str: str) -> str:
    """Форматирование строки даты (например 10072026 -> 10 июля 2026)."""
    if len(date_str) == 8:
        day = date_str[:2]
        month_num = date_str[2:4]
        year = date_str[4:]
        months = {
            "01": "января", "02": "февраля", "03": "марта", "04": "апреля",
            "05": "мая", "06": "июня", "07": "июля", "08": "августа",
            "09": "сентября", "10": "октября", "11": "ноября", "12": "декабря"
        }
        month_name = months.get(month_num, month_num)
        return f"{day} {month_name} {year}"
    return date_str

def compute_session_progress(player_matches: list[dict]) -> dict | None:
    """
    Рассчитывает динамику игрока на крайней игровой сессии (игровом дне):
    - Сравнивает метрики последней сессии с предыдущей сессией (или дебютным уровнем).
    - Возвращает дельты (HLTV, ADR, K/D, HS%, KAST, MMR) и списки 'better' и 'worse'.
    """
    if not player_matches:
        return None

    def _parse_d(d_str: str) -> datetime:
        try:
            return datetime.strptime(d_str[:8], "%d%m%Y")
        except Exception:
            return datetime.min

    session_groups = {}
    for m in player_matches:
        d = str(m.get("date", ""))[:8]
        if not d:
            continue
        session_groups.setdefault(d, []).append(m)

    if not session_groups:
        return None

    sorted_dates = sorted(session_groups.keys(), key=lambda d: _parse_d(d))
    latest_date = sorted_dates[-1]

    def _agg_session_stats(matches_list: list[dict]) -> dict:
        if not matches_list:
            return {}
        tot_kills = sum(m.get("kills", 0) for m in matches_list)
        tot_deaths = sum(m.get("deaths", 0) for m in matches_list)
        tot_assists = sum(m.get("assists", 0) for m in matches_list)
        tot_rounds = sum((m.get("score_team1", 0) + m.get("score_team2", 0)) for m in matches_list)
        if tot_rounds == 0:
            tot_rounds = len(matches_list) * 24
        
        adrs = [m.get("adr", 0.0) for m in matches_list if "adr" in m]
        avg_adr = sum(adrs) / len(adrs) if adrs else 0.0

        hltvs = [m.get("hltv_rating", m.get("hltv", 1.0)) for m in matches_list]
        avg_hltv = sum(hltvs) / len(hltvs) if hltvs else 1.0

        kasts = [m.get("kast", 0.0) for m in matches_list if "kast" in m]
        avg_kast = sum(kasts) / len(kasts) if kasts else 0.0

        hs_percents = [m.get("hs_percent", 0.0) for m in matches_list if "hs_percent" in m]
        avg_hs = sum(hs_percents) / len(hs_percents) if hs_percents else 0.0

        kd = tot_kills / max(1, tot_deaths)
        mmr_delta = sum(m.get("mmr_delta", 0) for m in matches_list)

        tot_fk = sum(m.get("first_kills", 0) for m in matches_list)
        tot_fd = sum(m.get("first_deaths", 0) for m in matches_list)
        tot_clutches = sum(m.get("clutch_wins", 0) for m in matches_list)
        tot_clutch_att = sum(m.get("clutch_attempts", 0) for m in matches_list)
        tot_ud = sum(m.get("utility_damage", 0) for m in matches_list)
        ud_per_round = tot_ud / max(1, tot_rounds)

        wins = sum(1 for m in matches_list if m.get("is_win", False) or m.get("team_result") == "win")
        losses = sum(1 for m in matches_list if m.get("is_loss", False) or m.get("team_result") == "loss")

        return {
            "matches_count": len(matches_list),
            "kills": tot_kills,
            "deaths": tot_deaths,
            "assists": tot_assists,
            "kd": round(kd, 2),
            "adr": round(avg_adr, 1),
            "hltv": round(avg_hltv, 2),
            "kast": round(avg_kast, 1),
            "hs_percent": round(avg_hs, 1),
            "mmr_delta": mmr_delta,
            "first_kills": tot_fk,
            "first_deaths": tot_fd,
            "clutches": tot_clutches,
            "clutch_attempts": tot_clutch_att,
            "ud_per_round": round(ud_per_round, 1),
            "wins": wins,
            "losses": losses
        }

    curr = _agg_session_stats(session_groups[latest_date])
    better = []
    worse = []

    if len(sorted_dates) > 1:
        prev_date = sorted_dates[-2]
        prev = _agg_session_stats(session_groups[prev_date])
        compare_label = f"к прошлой сессии ({format_date_display(prev_date)})"

        delta_hltv = round(curr["hltv"] - prev["hltv"], 2)
        delta_adr = round(curr["adr"] - prev["adr"], 1)
        delta_kd = round(curr["kd"] - prev["kd"], 2)
        delta_hs = round(curr["hs_percent"] - prev["hs_percent"], 1)
        delta_kast = round(curr["kast"] - prev["kast"], 1)

        if delta_hltv >= 0.08:
            better.append(f"Рейтинг HLTV вырос на +{delta_hltv:.2f} (текущий {curr['hltv']:.2f}) — ощутимый рост общего импакта")
        elif delta_hltv <= -0.08:
            worse.append(f"Рейтинг HLTV снизился на {delta_hltv:.2f} (текущий {curr['hltv']:.2f}) относительно прошлой сессии")

        if delta_adr >= 7.0:
            better.append(f"Огневая мощь: средний урон вырос на +{delta_adr:.1f} ADR (достиг {curr['adr']:.1f} ADR)")
        elif delta_adr <= -7.0:
            worse.append(f"Просадка по урону: потеряно {abs(delta_adr):.1f} ADR (упал до {curr['adr']:.1f} ADR)")

        if delta_kd >= 0.12:
            better.append(f"Улучшился K/D на +{delta_kd:.2f} (текущий {curr['kd']:.2f})")
        elif delta_kd <= -0.12:
            worse.append(f"Снижение K/D на {abs(delta_kd):.2f} (текущий {curr['kd']:.2f})")

        if delta_hs >= 5.0:
            better.append(f"Точность стрельбы в голову: +{delta_hs:.1f}% HS (до {curr['hs_percent']:.1f}%)")
        elif delta_hs <= -5.0:
            worse.append(f"Снижение точности хедшотов на {abs(delta_hs):.1f}% (до {curr['hs_percent']:.1f}%)")

        if delta_kast >= 5.0:
            better.append(f"Командный вклад KAST вырос на +{delta_kast:.1f}% (до {curr['kast']:.1f}%)")
        elif delta_kast <= -5.0:
            worse.append(f"Снижение KAST на {abs(delta_kast):.1f}% (до {curr['kast']:.1f}%) — меньше раундов с полезным действием")
    else:
        compare_label = "дебютная сессия игрока"
        delta_hltv = 0.0
        delta_adr = 0.0
        delta_kd = 0.0
        delta_hs = 0.0
        delta_kast = 0.0

        if curr["hltv"] >= 1.05:
            better.append(f"Уверенный старт: рейтинг HLTV {curr['hltv']:.2f} в первых матчах")
        if curr["adr"] >= 75.0:
            better.append(f"Хороший урон по соперникам: {curr['adr']:.1f} ADR")
        if curr["hs_percent"] >= 45.0:
            better.append(f"Отличная точность хедшотов: {curr['hs_percent']:.1f}% HS")

        if curr["kd"] < 0.9:
            worse.append(f"Отрицательный K/D ({curr['kd']:.2f}) — необходимо меньше рисковать в ранних дуэлях")
        if curr["ud_per_round"] < 5.0:
            worse.append(f"Низкий урон гранатами ({curr['ud_per_round']:.1f} HP/раунд)")

    # Highlights
    if curr["first_kills"] > curr["first_deaths"] and curr["first_kills"] >= 3:
        better.append(f"Уверенные опен-дуэли: {curr['first_kills']} первых фрагов при {curr['first_deaths']} смертях")
    elif curr["first_deaths"] > curr["first_kills"] and curr["first_deaths"] >= 3:
        worse.append(f"Проигрыш ранних дуэлей: {curr['first_deaths']} первых смертей при {curr['first_kills']} опен-киллах")

    if curr["clutches"] >= 1:
        better.append(f"Выиграно важных клатчей: {curr['clutches']}")

    if curr["ud_per_round"] >= 10.0:
        better.append(f"Эффективные раскидки: {curr['ud_per_round']:.1f} урона гранатами за раунд")

    if curr["mmr_delta"] > 0:
        better.append(f"Плюсовой баланс по MMR за день: +{curr['mmr_delta']}")
    elif curr["mmr_delta"] < 0:
        worse.append(f"Отрицательный баланс MMR за сессию: {curr['mmr_delta']}")

    if not better:
        better.append("Стабильная позиционная игра без явных срывов")
    if not worse:
        worse.append("Заметных просадок не выявлено — сессия сыграна на хорошем уровне")

    return {
        "date": latest_date,
        "date_display": format_date_display(latest_date),
        "matches_count": curr["matches_count"],
        "compare_label": compare_label,
        "current": {
            "hltv": curr["hltv"],
            "adr": curr["adr"],
            "kd": curr["kd"],
            "hs_percent": curr["hs_percent"],
            "mmr_delta": curr["mmr_delta"],
            "wins": curr["wins"],
            "losses": curr["losses"],
            "kills": curr.get("kills", 0),
            "deaths": curr.get("deaths", 0),
            "first_deaths": curr.get("first_deaths", 0),
            "first_kills": curr.get("first_kills", 0),
            "clutches": curr.get("clutches", 0)
        },
        "deltas": {
            "hltv": delta_hltv,
            "adr": delta_adr,
            "kd": delta_kd,
            "hs_percent": delta_hs,
            "kast": delta_kast,
            "mmr_delta": curr["mmr_delta"]
        },
        "better": better,
        "worse": worse
    }

def generate_recommendations(player_data: dict, ratings: dict, style: list[str], map_perf: dict = None, matches: list = None, achievements: list = None) -> dict:
    """
    Генерирует советы и рекомендации на основе правил, 10 рейтингов и худших карт.
    Разграничивает:
    - current_role (фактический игровой стиль из демок, style[0])
    - best_role (рекомендуемая роль на основе пикового потенциала из 10 навыков)
    """
    m = player_data.get("metrics", {})
    primary_role = style[0] if style else "Универсал"
    map_perf = map_perf or {}
    matches = matches or []

    # Расчет рекомендуемой роли по пиковому профилю 10 навыков
    aim_v = ratings.get("Aim", 5.0)
    ent_v = ratings.get("Entry", 5.0)
    pos_v = ratings.get("Positioning", 5.0)
    ut_v = ratings.get("Utility", 5.0)
    tr_v = ratings.get("Trading", 5.0)
    cl_v = ratings.get("Clutch", 5.0)
    gs_v = ratings.get("Game Sense", 5.0)
    eco_v = ratings.get("Economy", 5.0)
    disc_v = ratings.get("Discipline", 5.0)
    awp_pct = m.get("awp_kills_percent", 0.0)

    role_candidates = []
    if awp_pct >= 20.0 or (aim_v >= 6.5 and m.get("awp_kills", 0) >= 15):
        role_candidates.append(("Основной снайпер (Main AWP)", aim_v * 0.6 + pos_v * 0.4 + (awp_pct / 10.0)))
    if ent_v >= 6.0:
        role_candidates.append(("Главный энтри-фрагер (First Entry)", ent_v * 0.7 + aim_v * 0.3))
    if ut_v >= 6.0 or disc_v >= 6.0:
        role_candidates.append(("Координатор / Главный саппорт", ut_v * 0.6 + disc_v * 0.4))
    if pos_v >= 6.0 and gs_v >= 5.5:
        role_candidates.append(("Опорник / Якорь плента (Site Anchor)", pos_v * 0.6 + gs_v * 0.4))
    if tr_v >= 6.0 or cl_v >= 6.0:
        role_candidates.append(("Второй номер / Трейдер (Refragger)", tr_v * 0.6 + cl_v * 0.4))
    if gs_v >= 6.5 and eco_v >= 6.0:
        role_candidates.append(("Ин-гейм лидер (IGL / Капитан)", gs_v * 0.6 + eco_v * 0.4))

    if role_candidates:
        best_role = max(role_candidates, key=lambda x: x[1])[0]
    else:
        skill_role_map = {
            "Entry": "Главный энтри-фрагер (First Entry)",
            "Aim": "Агрессивный рифлер (Aggressive Rifler)",
            "Positioning": "Опорник / Якорь плента (Site Anchor)",
            "Utility": "Координатор / Главный саппорт",
            "Trading": "Второй номер / Трейдер (Refragger)",
            "Clutch": "Клатч-мастер / Люркер (Lurker)",
            "Game Sense": "Ин-гейм лидер (IGL / Капитан)"
        }
        cand_keys = [k for k in skill_role_map if k in ratings]
        if cand_keys:
            top_k = max(cand_keys, key=lambda k: ratings.get(k, 0))
            best_role = skill_role_map[top_k]
        else:
            best_role = primary_role

    recs = {
        "training": [],
        "habits_to_remove": [],
        "exercises": [],
        "current_role": primary_role,
        "best_role": best_role,
        "role_comparison": f"Текущий стиль: {primary_role} ➔ Рекомендуемая роль: {best_role}"
    }

    # 1. Шаблоны персональных советов по навыкам
    skill_advice_templates = {
        "Aim": "Твой параметр Aim ({val}/10) требует внимания. Рекомендуется ежедневная разминка в Aim Botz (500 тапов, 500 спреев) и фокус на стрельбу в голову на FFA DM.",
        "Positioning": "Твой параметр Positioning ({val}/10) требует внимания. Слишком много открытых дуэлей без укрытия. Отрабатывай углы обзора (angle isolation) и не пикай повторно одну линию.",
        "Utility": "Твой параметр Utility ({val}/10) требует внимания. Дефицит полезного урона и тиммейт-флешек. Заучи по 2 ключевые моменталки и ретейк-смока на каждой соревновательной карте.",
        "Game Sense": "Твой параметр Game Sense ({val}/10) требует внимания. Частая потеря таймингов. Следи за радаром при сменах плента и читай экономику оппонента.",
        "Entry": "Твой параметр Entry ({val}/10) требует внимания. Низкий винрейт в опенинг-дуэлях. Никогда не выходи первым без звукового фейка или саппорт-флешки.",
        "Trading": "Твой параметр Trading ({val}/10) требует внимания. Тиммейты погибают без размена. Сокращай тайминг пика после смерти тиммейта до 1-1.5 секунды.",
        "Clutch": "Твой параметр Clutch ({val}/10) требует внимания. В ситуациях 1vX форсируешь бой. Разделяй оппонентов на серию изолированных дуэлей 1v1.",
        "Discipline": "Твой параметр Discipline ({val}/10) требует внимания. Ненужная агрессия при численном преимуществе (5v3, 4v2). Играй на удержание и время.",
        "Economy": "Твой параметр Economy ({val}/10) требует внимания. Рассинхрон закупок с командой. Не докупай пистолеты и девайсы на командном эко."
    }

    # 1.1. Персональная привязка к слабейшему навыку (Точка роста)
    valid_ratings = [(k, v) for k, v in ratings.items() if k != "Overall Impact"]
    if valid_ratings:
        weakest_skill, weakest_val = min(valid_ratings, key=lambda x: x[1])
        weakest_val_fmt = round(float(weakest_val), 1)
        if weakest_skill in skill_advice_templates:
            primary_weak_advice = skill_advice_templates[weakest_skill].format(val=weakest_val_fmt).replace("требует внимания", "— слабейший")
            recs["training"].append(primary_weak_advice)

    # 2. Персональная привязка к худшей карте (Криптонит)
    worst_m = map_perf.get("worst_map")
    if worst_m:
        worst_disp = map_perf.get("worst_map_display", worst_m.replace("de_", "").capitalize())
        w_stats = map_perf.get("maps", {}).get(worst_m, {})
        w_wr = w_stats.get("win_rate", 0)
        w_kd = w_stats.get("kd_ratio", 1.0)
        recs["habits_to_remove"].append(
            f"Криптонит-карта: {worst_disp}. Винрейт всего {w_wr}% (K/D {w_kd}). Изучи тайминги раскидок и безопасные углы удержания именно для этой карты."
        )

    # 3. Ролевая специфика
    if "Entry" in primary_role or "Агрессивный" in primary_role:
        recs["training"].append("Фокусируйся на таймингах первых пиков и префаерах в стандартные углы на Faceit/Yprac.")
    elif "AWP" in primary_role:
        recs["training"].append("Отрабатывай агрессивные пики с зумом и быструю смену позиции после первого выстрела.")
    elif "Саппорт" in primary_role or "Трейдер" in primary_role:
        recs["training"].append("Тренируй глубокие моменталки на бегу и моментальный размен энтри-фраггера (дистанция до 2 сек).")
    elif "Клатчер" in primary_role or "Люркер" in primary_role:
        recs["training"].append("Анализируй звуковые подсказки и тайминги фейков при игре в меньшинстве 1v2/1v3.")

    # 4. Базовые правила
    if ratings.get("Aim", 5.0) > 7 and ratings.get("Positioning", 5.0) < 4:
        recs["habits_to_remove"].append("У тебя хороший аим, но ты часто стоишь в невыгодных позициях. Смотри POV профессионалов своей роли.")
    if ratings.get("Entry", 5.0) > 7 and ratings.get("Trading", 5.0) < 4:
        recs["habits_to_remove"].append("Ты хороший entry, но тебя не трейдят. Коммуницируй команде когда выходишь.")
    if m.get("hs_percent", 0) < 35:
        recs["training"].append("Целься выше — crosshair placement строго на уровне головы. Тренируй на DM с фокусом на one-tap.")
    if ratings.get("Clutch", 5.0) > 7:
        recs["exercises"].append("Клатч-мастерство: сохраняй хладнокровие, используй звук бомбы для выманивания оппонентов.")
    if ratings.get("Economy", 5.0) < 5:
        recs["habits_to_remove"].append("Следи за экономикой команды. Не форсись один, когда команда на эко.")
    if m.get("first_death_rate", 0) > 20:
        recs["habits_to_remove"].append("Слишком часто умираешь первым (FDR > 20%). Будь осторожнее с peek'ами, используй jiggle peek.")
    if m.get("utility_damage", 0) > 20:
        recs["training"].append("Отличная работа с утилитой! Это твоя сильная сторона.")
    if m.get("flash_assists_per_match", 0) < 1:
        recs["exercises"].append("Используй флешки для тиммейтов. Учи pop-flash для входов на сайт.")
    if m.get("trade_rate", 0) < 20:
        recs["habits_to_remove"].append("Держись ближе к тиммейтам для размена. Следи за радаром.")
    if m.get("pistol_win_rate", 0) < 30:
        recs["training"].append("Пистолетные раунды — твоя слабая сторона. Тренируй USP/Glock в DM.")
    if m.get("entry_success", 0) < 40 and m.get("first_kill_rate", 0) > 15:
        recs["habits_to_remove"].append("Ты часто входишь первым, но неэффективно. Проси у тиммейтов флешку перед входом.")

    # 5. Соревновательные квесты на прокачку слабых сторон («Квесты на прокачку»)
    quests = []
    if achievements:
        ach_by_id = {a.get("id"): a for a in achievements}
        
        # Карта привязки 10 ключевых навыков к соревновательным квестам
        skill_quest_candidates = {
            "Aim": ["aim_onetap", "aim_damage_roller"],
            "Positioning": ["pos_anchor", "pos_ghost"],
            "Utility": ["util_artillery", "util_flash_duo"],
            "Game Sense": ["gs_iron_curtain", "gs_sixth_sense"],
            "Entry": ["entry_thunder", "entry_battering_ram"],
            "Trading": ["trade_blood_revenge", "trade_wingman"],
            "Clutch": ["clutch_minister", "clutch_steel_nerves"],
            "Discipline": ["disc_zen", "disc_frugal_fighter"],
            "Economy": ["eco_saboteur", "eco_pistol_maestro"],
            "Overall Impact": ["impact_star_carry", "impact_bombardier"]
        }
        
        # Сортируем навыки по возрастанию рейтинга (самые слабые первыми)
        sorted_skills = sorted(
            [(k, v) for k, v in ratings.items() if k != "Overall Impact"],
            key=lambda x: x[1]
        )
        
        used_quest_ids = set()
        for w_skill, w_val in sorted_skills:
            if len(quests) >= 3:
                break
            cand_ids = skill_quest_candidates.get(w_skill, [])
            chosen_ach = None
            # Приоритет: сначала еще не закрытая на 100% ачивка (tier < 3)
            for cid in cand_ids:
                if cid in ach_by_id and cid not in used_quest_ids:
                    cand_a = ach_by_id[cid]
                    if cand_a.get("tier", 0) < 3:
                        chosen_ach = cand_a
                        break
            # Если обе уже закрыты или в процессе, берем первую подходящую
            if not chosen_ach:
                for cid in cand_ids:
                    if cid in ach_by_id and cid not in used_quest_ids:
                        chosen_ach = ach_by_id[cid]
                        break
            
            if chosen_ach:
                used_quest_ids.add(chosen_ach["id"])
                next_tier_names = {0: "Бронза 🥉", 1: "Серебро 🥈", 2: "Золото 🥇", 3: "Золото 🥇 (МАКС)"}
                w_val_fmt = round(float(w_val), 1)
                if w_skill in skill_advice_templates:
                    adv = skill_advice_templates[w_skill].format(val=w_val_fmt)
                else:
                    adv = f"Сфокусируйся на развитии навыка {w_skill} ({w_val_fmt}/10)."
                quests.append({
                    "quest_id": chosen_ach.get("id"),
                    "title": chosen_ach.get("title"),
                    "icon": chosen_ach.get("icon"),
                    "skill": w_skill,
                    "skill_val": w_val_fmt,
                    "tier": chosen_ach.get("tier", 0),
                    "tier_name": chosen_ach.get("tier_name"),
                    "next_tier_name": next_tier_names.get(chosen_ach.get("tier", 0), "Золото 🥇"),
                    "is_max": chosen_ach.get("is_max", False),
                    "progress_val": chosen_ach.get("progress_val"),
                    "progress_max": chosen_ach.get("progress_max"),
                    "progress_pct": chosen_ach.get("progress_pct", 0.0),
                    "progress_text": chosen_ach.get("progress_text"),
                    "next_goal": chosen_ach.get("next_goal"),
                    "stars_data": chosen_ach.get("stars_data", []),
                    "advice": adv
                })
        
        # Если почему-то набралось меньше 3 квестов, дополняем любыми незакрытыми ачивками
        if len(quests) < 3:
            for a in achievements:
                if len(quests) >= 3:
                    break
                if a.get("id") not in used_quest_ids and a.get("tier", 0) < 3:
                    used_quest_ids.add(a["id"])
                    next_tier_names = {0: "Бронза 🥉", 1: "Серебро 🥈", 2: "Золото 🥇", 3: "Золото 🥇 (МАКС)"}
                    quests.append({
                        "quest_id": a.get("id"),
                        "title": a.get("title"),
                        "icon": a.get("icon"),
                        "skill": "Бонус",
                        "skill_val": 5.0,
                        "tier": a.get("tier", 0),
                        "tier_name": a.get("tier_name"),
                        "next_tier_name": next_tier_names.get(a.get("tier", 0), "Золото 🥇"),
                        "is_max": a.get("is_max", False),
                        "progress_val": a.get("progress_val"),
                        "progress_max": a.get("progress_max"),
                        "progress_pct": a.get("progress_pct", 0.0),
                        "progress_text": a.get("progress_text"),
                        "next_goal": a.get("next_goal"),
                        "stars_data": a.get("stars_data", []),
                        "advice": "Выполняй соревновательные испытания для быстрого роста Glory Points."
                    })
    
    recs["quests"] = quests
    if quests:
        # Топ-1 приоритетный квест для слабейшего навыка
        tq = dict(quests[0])
        # Формируем специализированную подсказку для целевой карточки
        tq["radar_boost_text"] = f"Выполнение этого квеста на следующий ранг ({tq.get('next_tier_name')}) даст мощный прирост параметра {tq.get('skill')} на радарной диаграмме и увеличит All-Time MMR."
        recs["target_quest"] = tq
    else:
        recs["target_quest"] = None
    return recs


def run_analysis(force_ai: bool = False):
    """
    Основная функция для запуска анализа.
    """
    matches_dir = str(DATA_DIR / "matches")
    players_dir = str(DATA_DIR / "players")
    players_db_path = str(DATA_DIR / "players_db.json")
    
    os.makedirs(matches_dir, exist_ok=True)
    os.makedirs(players_dir, exist_ok=True)
    
    ai_status = "Gemini API (" + AI_MODEL + ")" if get_gemini_client() else "Локальный тактический движок"
    print(f"Начинаем анализ матчей и игроков... [Движок аналитики: {ai_status}]")
    
    # 1. Обогащение матчей
    if os.path.exists(matches_dir):
        match_files = [f for f in os.listdir(matches_dir) if f.endswith(".json")]
        for idx, match_file in enumerate(match_files, start=1):
            match_path = os.path.join(matches_dir, match_file)
            try:
                with open(match_path, "r", encoding="utf-8") as f:
                    match_data = json.load(f)
                if force_ai:
                    match_data["summary_analysis"] = ""
                enriched_match = analyze_match(match_data)
                with open(match_path, "w", encoding="utf-8") as f:
                    json.dump(enriched_match, f, ensure_ascii=False, indent=4)
                print(f"[{idx}/{len(match_files)}] Обработан матч: {match_file}")
            except Exception as e:
                print(f"Ошибка при обработке матча {match_file}: {e}")

    # 2. Очистка старых файлов игроков для предотвращения дубликатов
    if os.path.exists(players_dir):
        for pf in os.listdir(players_dir):
            if pf.endswith(".json"):
                try:
                    os.remove(os.path.join(players_dir, pf))
                except Exception:
                    pass

    # 3. Загрузка всех матчей и хронологическая сортировка для непрерывной системы MMR
    match_items = []
    if os.path.exists(matches_dir):
        for match_file in os.listdir(matches_dir):
            if match_file.endswith(".json"):
                m_path = os.path.join(matches_dir, match_file)
                try:
                    with open(m_path, "r", encoding="utf-8") as f:
                        m_data = json.load(f)
                    match_items.append((match_file, m_path, m_data))
                except Exception as e:
                    print(f"Ошибка загрузки матча {match_file}: {e}")

    def get_match_sort_key(item):
        _, _, m_dict = item
        d_str = m_dict.get("date", "01012020")
        try:
            dt = datetime.strptime(d_str, "%d%m%Y")
        except Exception:
            dt = datetime.min
        return (dt, m_dict.get("match_id", ""))

    match_items.sort(key=get_match_sort_key)

    # 4. Непрерывный расчет MMR по всем матчам в хронологическом порядке
    players_mmr = {}
    raw_db = {}
    player_econ_stats = defaultdict(lambda: {
        "total_rounds": 0, "won_rounds": 0, "won_survived": 0,
        "lost_rounds": 0, "lost_survived": 0,
        "eco_rounds": 0, "eco_kills": 0, "eco_deaths": 0,
        "force_rounds": 0, "force_kills": 0, "force_deaths": 0,
        "vs_full_kills": 0, "vs_full_deaths": 0,
        "vs_force_kills": 0, "vs_force_deaths": 0,
        "vs_eco_kills": 0, "vs_eco_deaths": 0,
        "ct_rounds": 0, "ct_first_deaths": 0
    })
    latest_dataset_date = datetime.min

    # Инициализация матриц дуэлей и синергии напарников
    h2h_matrix = defaultdict(lambda: defaultdict(lambda: {"kills": 0, "deaths": 0}))
    team_synergy = defaultdict(lambda: defaultdict(lambda: {"matches": 0, "wins": 0}))
    trade_synergy = defaultdict(lambda: defaultdict(int))
    player_special_events = defaultdict(lambda: Counter())
    match_duels_list = []
    canonical_names = {}

    for match_file, m_path, m_data in match_items:
        m_id = m_data.get("match_id")
        m_date = m_data.get("date")
        
        # Нормализация названия карты к каноническому формату de_*
        m_raw_map = str(m_data.get("map", "")).lower().strip()
        if not m_raw_map.startswith("de_"):
            m_raw_map = f"de_{m_raw_map}"
        m_map_display = MAP_DISPLAY_NAMES.get(m_raw_map, m_data.get("map_display", m_raw_map.replace("de_", "").capitalize()))
        m_map = m_raw_map
        
        s1 = m_data.get("score_team1", 0)
        s2 = m_data.get("score_team2", 0)
        rounds_cnt = max(1, len(m_data.get("rounds", [])) or (s1 + s2))

        try:
            match_dt = datetime.strptime(m_date, "%d%m%Y")
            if match_dt > latest_dataset_date:
                latest_dataset_date = match_dt
        except Exception:
            match_dt = datetime.now()

        # Сбор раундовой статистики экономики, выживания и дисциплины для игроков этого матча
        match_p_teams = {}
        for sid_k, p_st in m_data.get("players", {}).items():
            cs = clean_steamid(p_st.get("steam_id") or sid_k)
            nl = (p_st.get("name") or "").lower().strip()
            if cs in PLAYER_ALIASES:
                cs, _ = PLAYER_ALIASES[cs]
            elif nl in PLAYER_ALIASES:
                cs, _ = PLAYER_ALIASES[nl]
            if nl in CANONICAL_PLAYERS:
                cs = CANONICAL_PLAYERS[nl]
            if cs:
                match_p_teams[cs] = p_st.get("team")

        def resolve_evt_sid(s_val, n_val):
            cs = clean_steamid(s_val)
            nl = str(n_val or "").lower().strip()
            if cs in PLAYER_ALIASES:
                cs, _ = PLAYER_ALIASES[cs]
            elif nl in PLAYER_ALIASES:
                cs, _ = PLAYER_ALIASES[nl]
            if nl in CANONICAL_PLAYERS:
                cs = CANONICAL_PLAYERS[nl]
            return cs

        round_kills_map = defaultdict(list)
        for k_evt in sorted(m_data.get("kills", []), key=lambda x: x.get("tick", 0)):
            round_kills_map[k_evt.get("round_num")].append(k_evt)

        for r_evt in m_data.get("rounds", []):
            r_n = r_evt.get("round_num")
            w_team = r_evt.get("winning_team")
            ct_team = r_evt.get("ct_team")
            t_team = r_evt.get("t_team")
            ct_eco = str(r_evt.get("ct_economy_badge", "") or "")
            t_eco = str(r_evt.get("t_economy_badge", "") or "")

            rkills = round_kills_map.get(r_n, [])
            first_dead_sid = resolve_evt_sid(rkills[0].get("victim_steamid"), rkills[0].get("victim_name")) if rkills else None
            round_dead_sids = {resolve_evt_sid(k_evt.get("victim_steamid"), k_evt.get("victim_name")) for k_evt in rkills}

            # Ace detection: 5+ kills in a single round
            r_att_counts = Counter()
            for k_evt in rkills:
                a_sid = resolve_evt_sid(k_evt.get("attacker_steamid"), k_evt.get("attacker_name"))
                if a_sid:
                    r_att_counts[a_sid] += 1
            for a_sid, cnt in r_att_counts.items():
                if cnt >= 5:
                    player_special_events[a_sid]["aces"] += 1

            for cs, pteam in match_p_teams.items():
                if not pteam or not cs:
                    continue
                pes = player_econ_stats[cs]
                pes["total_rounds"] += 1

                is_ct = (pteam == ct_team)
                my_eco = ct_eco if is_ct else t_eco
                opp_eco = t_eco if is_ct else ct_eco

                if is_ct:
                    pes["ct_rounds"] += 1
                    if first_dead_sid == cs:
                        pes["ct_first_deaths"] += 1

                survived = (cs not in round_dead_sids)
                if pteam == w_team:
                    pes["won_rounds"] += 1
                    if survived:
                        pes["won_survived"] += 1
                else:
                    pes["lost_rounds"] += 1
                    if survived:
                        pes["lost_survived"] += 1

                if r_evt.get("reason") == "bomb_defused" and is_ct and survived:
                    player_special_events[cs]["defuses"] += 1

                my_kills = sum(1 for k_evt in rkills if resolve_evt_sid(k_evt.get("attacker_steamid"), k_evt.get("attacker_name")) == cs)
                my_deaths = 1 if not survived else 0

                if "Eco" in my_eco:
                    pes["eco_rounds"] += 1
                    pes["eco_kills"] += my_kills
                    pes["eco_deaths"] += my_deaths
                elif "Force" in my_eco or "Semi-Buy" in my_eco:
                    pes["force_rounds"] += 1
                    pes["force_kills"] += my_kills
                    pes["force_deaths"] += my_deaths

                if "Full Buy" in opp_eco:
                    pes["vs_full_kills"] += my_kills
                    pes["vs_full_deaths"] += my_deaths
                elif "Force" in opp_eco or "Semi-Buy" in opp_eco:
                    pes["vs_force_kills"] += my_kills
                    pes["vs_force_deaths"] += my_deaths
                elif "Eco" in opp_eco:
                    pes["vs_eco_kills"] += my_kills
                    pes["vs_eco_deaths"] += my_deaths

        # Рассчитываем per-match K/D против Full Buy для каждого игрока
        match_vs_full_kd = {}
        for cs in match_p_teams:
            m_fk = sum(1 for k_evt in m_data.get("kills", []) if resolve_evt_sid(k_evt.get("attacker_steamid"), k_evt.get("attacker_name")) == cs and "Full Buy" in str(round_kills_map.get(k_evt.get("round_num"), [{}])[0].get("opp_eco", "") if False else ""))
            # Точный подсчет по раундам матча
            p_full_k = 0
            p_full_d = 0
            p_tactical_k = 0
            p_team = match_p_teams[cs]
            for r_evt in m_data.get("rounds", []):
                r_n = r_evt.get("round_num")
                ct_team = r_evt.get("ct_team")
                is_ct = (p_team == ct_team)
                opp_eco = str(r_evt.get("t_economy_badge", "") if is_ct else r_evt.get("ct_economy_badge", ""))
                rkills = round_kills_map.get(r_n, [])
                for k_evt in rkills:
                    att = resolve_evt_sid(k_evt.get("attacker_steamid"), k_evt.get("attacker_name"))
                    vic = resolve_evt_sid(k_evt.get("victim_steamid"), k_evt.get("victim_name"))
                    if att == cs:
                        if "Full Buy" in opp_eco:
                            p_full_k += 1
                        if k_evt.get("thrusmoke") or (k_evt.get("attacker_blind")):
                            p_tactical_k += 1
                    if vic == cs and "Full Buy" in opp_eco:
                        p_full_d += 1
            kd_full = round(p_full_k / max(1, p_full_d), 2) if (p_full_k + p_full_d) > 0 else 1.0
            match_vs_full_kd[cs] = {"vs_full_kd": kd_full, "tactical_kills": p_tactical_k}

        for sid_key, p_stat in m_data.get("players", {}).items():
            p_name = p_stat.get("name", "").strip()
            name_lower = p_name.lower()
            clean_sid = clean_steamid(p_stat.get("steam_id") or sid_key)

            if clean_sid in PLAYER_ALIASES:
                clean_sid, p_name = PLAYER_ALIASES[clean_sid]
            elif name_lower in PLAYER_ALIASES:
                clean_sid, p_name = PLAYER_ALIASES[name_lower]

            if name_lower in CANONICAL_PLAYERS:
                clean_sid = CANONICAL_PLAYERS[name_lower]

            if not clean_sid:
                continue

            p_stat["steam_id"] = clean_sid
            p_stat["name"] = p_name

            if clean_sid not in players_mmr:
                players_mmr[clean_sid] = {
                    "steam_id": clean_sid,
                    "name": p_name,
                    "current_mmr": STARTING_MMR,
                    "peak_mmr": STARTING_MMR,
                    "history": [],
                    "wins": 0,
                    "losses": 0,
                    "ties": 0,
                    "total_matches": 0,
                    "all_hltv": [],
                    "latest_date": match_dt
                }

            p_mmr = players_mmr[clean_sid]
            p_mmr["latest_date"] = max(p_mmr["latest_date"], match_dt)
            p_team = p_stat.get("team", "team1")

            # Определение исхода для команды игрока
            if s1 > s2:
                team_won = (p_team == "team1")
                team_lost = (p_team != "team1")
                is_tie = False
            elif s2 > s1:
                team_won = (p_team == "team2")
                team_lost = (p_team != "team2")
                is_tie = False
            else:
                team_won = False
                team_lost = False
                is_tie = True

            base_delta = BASE_TEAM_DELTA if team_won else (-BASE_TEAM_DELTA if team_lost else 0)

            # Честный расчет HLTV 2.0 и приведенного балла 1.0 - 10.0
            k = p_stat.get("kills", 0)
            d = p_stat.get("deaths", 0)
            a = p_stat.get("assists", 0)
            adr_val = p_stat.get("adr", 0.0)
            kast_val = p_stat.get("kast", 0.0)
            fk = p_stat.get("first_kills", 0)
            fd = p_stat.get("first_deaths", 0)
            clutches = p_stat.get("clutch_wins", 0)

            hltv, score_10 = compute_hltv_rating(k, d, a, adr_val, kast_val, fk, fd, rounds_cnt)

            # Модификатор импакта (-8 до +8)
            raw_mod = (hltv - 1.00) * 12.0
            mod = round(max(-float(MAX_IMPACT_MODIFIER), min(float(MAX_IMPACT_MODIFIER), raw_mod)), 1)

            # Калибровка (матчи 1-5)
            m_num = p_mmr["total_matches"] + 1
            is_calibrating = (m_num <= CALIBRATION_MATCH_LIMIT)
            raw_delta = base_delta + mod

            if is_calibrating:
                delta = round(raw_delta * CALIBRATION_VOLATILITY)
                delta = max(-MAX_CALIBRATION_DELTA, min(MAX_CALIBRATION_DELTA, delta))
            else:
                delta = round(raw_delta)
                delta = max(-MAX_REGULAR_DELTA, min(MAX_REGULAR_DELTA, delta))

            mmr_before = p_mmr["current_mmr"]
            p_mmr["current_mmr"] += delta
            p_mmr["peak_mmr"] = max(p_mmr["peak_mmr"], p_mmr["current_mmr"])
            p_mmr["total_matches"] += 1
            p_mmr["all_hltv"].append(hltv)
            if team_won:
                p_mmr["wins"] += 1
            elif team_lost:
                p_mmr["losses"] += 1
            else:
                p_mmr["ties"] += 1

            breakdown_str = f"База ({base_delta:+d}) + Импакт ({mod:+.1f}) = Итог ({delta:+d} MMR)"

            # Обогащаем статистику игрока в матче
            p_stat["hltv_rating"] = hltv
            p_stat["score_10"] = score_10
            p_stat["mmr_delta"] = delta
            p_stat["mmr_before"] = mmr_before
            p_stat["mmr_after"] = p_mmr["current_mmr"]
            p_stat["mmr_breakdown"] = breakdown_str
            p_stat["is_calibrating"] = is_calibrating

            # Добавляем в историю игрока
            p_mmr["history"].append({
                "match_id": m_id,
                "date": m_date,
                "map": m_map,
                "team_result": "win" if team_won else ("loss" if team_lost else "tie"),
                "delta": delta,
                "base_delta": base_delta,
                "modifier": mod,
                "mmr_before": mmr_before,
                "mmr_after": p_mmr["current_mmr"],
                "hltv": hltv,
                "score_10": score_10,
                "is_calibrating": is_calibrating,
                "breakdown": breakdown_str
            })

            # Сборка в общую базу raw_db
            if clean_sid not in raw_db:
                raw_db[clean_sid] = {"steam_id": clean_sid, "name": p_name, "matches": []}

            raw_db[clean_sid]["matches"].append({
                "match_id": m_id,
                "date": m_date,
                "map": m_map,
                "kills": k,
                "deaths": d,
                "assists": a,
                "adr": adr_val,
                "kast": kast_val,
                "hs_percent": p_stat.get("hs_percent", 0.0),
                "first_kills": fk,
                "first_deaths": fd,
                "clutch_wins": clutches,
                "clutch_attempts": p_stat.get("clutch_attempts", 0),
                "utility_damage": p_stat.get("utility_damage", 0),
                "flash_assists": p_stat.get("flash_assists", 0),
                "trades": p_stat.get("trades", 0),
                "weapon_kills": p_stat.get("weapon_kills", {}),
                "pistol_round_kills": p_stat.get("pistol_round_kills", 0),
                "pistol_round_deaths": p_stat.get("pistol_round_deaths", 0),
                "hltv_rating": hltv,
                "score_10": score_10,
                "mmr_delta": delta,
                "mmr_breakdown": breakdown_str,
                "team_result": "win" if team_won else ("loss" if team_lost else "tie"),
                "is_win": team_won,
                "is_loss": team_lost,
                "is_tie": not team_won and not team_lost,
                "player_team": p_team,
                "score_team1": s1,
                "score_team2": s2,
                "rounds_count": rounds_cnt,
                "vs_full_buy_kd": match_vs_full_kd.get(clean_sid, {}).get("vs_full_kd", 1.0),
                "tactical_kills": match_vs_full_kd.get(clean_sid, {}).get("tactical_kills", 0)
            })

        # Сбор данных по тиммейтам (синергия) и очным дуэлям (Head-to-Head)
        m_curr_pls = {}
        for sid_k, p_st in m_data.get("players", {}).items():
            cs = clean_steamid(p_st.get("steam_id") or sid_k)
            nl = (p_st.get("name") or "").lower().strip()
            if cs in PLAYER_ALIASES:
                cs, _ = PLAYER_ALIASES[cs]
            elif nl in PLAYER_ALIASES:
                cs, _ = PLAYER_ALIASES[nl]
            if nl in CANONICAL_PLAYERS:
                cs = CANONICAL_PLAYERS[nl]
            if cs:
                p_disp_name = p_st.get("name") or canonical_names.get(cs) or f"Player_{cs[-4:]}"
                m_curr_pls[cs] = {
                    "team": p_st.get("team", "team1"),
                    "name": p_disp_name
                }
                canonical_names[cs] = p_disp_name

        # 1. Тиммейты (в одной команде)
        curr_sids = list(m_curr_pls.keys())
        for i in range(len(curr_sids)):
            for j in range(i + 1, len(curr_sids)):
                s_a, s_b = curr_sids[i], curr_sids[j]
                if m_curr_pls[s_a]["team"] == m_curr_pls[s_b]["team"]:
                    p_team = m_curr_pls[s_a]["team"]
                    won = (s1 > s2 and p_team == "team1") or (s2 > s1 and p_team == "team2")
                    team_synergy[s_a][s_b]["matches"] += 1
                    team_synergy[s_b][s_a]["matches"] += 1
                    if won:
                        team_synergy[s_a][s_b]["wins"] += 1
                        team_synergy[s_b][s_a]["wins"] += 1

        # 2. Очные дуэли, размены и учет специальных событий оружия
        m_kills_sorted = sorted(m_data.get("kills", []), key=lambda x: (x.get("round_num", 0), x.get("tick", 0)))
        m_duels = Counter()
        for k_idx, k_ev in enumerate(m_kills_sorted):
            att = resolve_evt_sid(k_ev.get("attacker_steamid"), k_ev.get("attacker_name"))
            vic = resolve_evt_sid(k_ev.get("victim_steamid"), k_ev.get("victim_name"))
            if att and vic and att != vic:
                m_duels[(att, vic)] += 1
                if att in m_curr_pls and vic in m_curr_pls and m_curr_pls[att]["team"] != m_curr_pls[vic]["team"]:
                    h2h_matrix[att][vic]["kills"] += 1
                    h2h_matrix[vic][att]["deaths"] += 1

            # Учет специфических типов фрагов для ачивок
            if att:
                w = (k_ev.get("weapon") or "").lower()
                if k_ev.get("thrusmoke"):
                    player_special_events[att]["thrusmoke"] += 1
                if (w == "deagle" and k_ev.get("headshot")) or w == "revolver":
                    player_special_events[att]["wild_west"] += 1
                if w in ("xm1014", "nova", "mag7", "sawedoff"):
                    player_special_events[att]["shotgun"] += 1
                if k_ev.get("assistedflash"):
                    player_special_events[att]["blind_rage"] += 1
                if w in ("taser", "zeus"):
                    player_special_events[att]["taser_kills"] += 1
                if "knife" in w:
                    player_special_events[att]["knife_kills"] += 1

            # Размен за погибшего тиммейта (в пределах 5 сек / 320 тиков)
            if att and vic and vic in m_curr_pls:
                v_team = m_curr_pls[vic]["team"]
                v_tick = k_ev.get("tick", 0)
                v_round = k_ev.get("round_num", 0)
                for next_k in m_kills_sorted[k_idx+1:k_idx+7]:
                    if next_k.get("round_num") != v_round:
                        break
                    if (next_k.get("tick", 0) - v_tick) > 350:
                        break
                    trader = resolve_evt_sid(next_k.get("attacker_steamid"), next_k.get("attacker_name"))
                    trader_vic = resolve_evt_sid(next_k.get("victim_steamid"), next_k.get("victim_name"))
                    if trader and trader != vic and trader in m_curr_pls and m_curr_pls[trader]["team"] == v_team and trader_vic == att:
                        trade_synergy[vic][trader] += 1
                        break

        match_duels_list.append(m_duels)

        # Волевые победы (камбэк, овертайм, счет diff <= 3)
        m_winner = m_data.get("winner")
        is_close_or_ot = abs(s1 - s2) <= 3 or max(s1, s2) >= 15
        s1_half = sum(1 for r in m_data.get("rounds", [])[:12] if r.get("winning_team") == "team1")
        s2_half = 12 - s1_half
        is_half_deficit = (m_winner == "team1" and s2_half - s1_half >= 3) or (m_winner == "team2" and s1_half - s2_half >= 3)
        if m_winner and (is_close_or_ot or is_half_deficit):
            for cs, pteam in match_p_teams.items():
                if pteam == m_winner:
                    player_special_events[cs]["comebacks"] += 1

        # Обновляем условных капитанов команд по максимальному HLTV 2.0 в матче
        t1_pls = [p for p in m_data["players"].values() if p.get("team") == "team1"]
        t2_pls = [p for p in m_data["players"].values() if p.get("team") == "team2"]
        cap1 = max(t1_pls, key=lambda x: (x.get("hltv_rating", 0.0), x.get("kills", 0)))["name"] if t1_pls else "Команда 1"
        cap2 = max(t2_pls, key=lambda x: (x.get("hltv_rating", 0.0), x.get("kills", 0)))["name"] if t2_pls else "Команда 2"
        m_data["team1_captain"] = cap1
        m_data["team2_captain"] = cap2
        m_data["team1_name"] = f"Команда 1 ({cap1})"
        m_data["team2_name"] = f"Команда 2 ({cap2})"
        
        # Обновляем вводный аналитический комментарий с актуальным счетом и именами команд
        m_data["ai_analysis"] = generate_match_intro_commentary(m_data)

        # Перезаписываем обогащенный матч с актуальными MMR дельтами
        try:
            with open(m_path, "w", encoding="utf-8") as f:
                json.dump(m_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Ошибка сохранения обогащенного матча {m_path}: {e}")

    # 5. Сборка профилей игроков с полным MMR и 10 параметрами навыков
    for steam_id, p_info in raw_db.items():
        matches = p_info.get("matches", [])
        total_m = len(matches)
        if total_m == 0:
            continue

        p_mmr = players_mmr.get(steam_id, {})
        p_name = p_info.get("name") or p_mmr.get("name") or f"Player_{steam_id[-4:]}"

        tot_kills = sum(m.get("kills", 0) for m in matches)
        tot_deaths = sum(m.get("deaths", 0) for m in matches)
        tot_assists = sum(m.get("assists", 0) for m in matches)
        tot_adr = sum(m.get("adr", 0.0) for m in matches)
        tot_kast = sum(m.get("kast", 0.0) for m in matches)
        tot_hs = sum(m.get("hs_percent", 0.0) for m in matches)
        tot_fk = sum(m.get("first_kills", 0) for m in matches)
        tot_fd = sum(m.get("first_deaths", 0) for m in matches)
        tot_ud = sum(m.get("utility_damage", 0) for m in matches)
        tot_fa = sum(m.get("flash_assists", 0) for m in matches)
        tot_tr = sum(m.get("trades", 0) for m in matches)

        # Сбор реальной статистики оружия и клатчей
        total_weapon_kills = Counter()
        tot_clutch_wins = 0
        tot_clutch_attempts = 0
        for m in matches:
            for w, c in m.get("weapon_kills", {}).items():
                total_weapon_kills[str(w).lower()] += c
            tot_clutch_wins += m.get("clutch_wins", 0)
            tot_clutch_attempts += m.get("clutch_attempts", 0)

        awp_k = total_weapon_kills.get("awp", 0)
        rifle_weapons = {"ak47", "m4a1", "m4a1_silencer", "m4a4", "galilar", "famas", "aug", "sg556", "sg553"}
        rifle_k = sum(total_weapon_kills.get(w, 0) for w in rifle_weapons)

        awp_pct = (awp_k / max(1, tot_kills)) * 100
        rifle_pct = (rifle_k / max(1, tot_kills)) * 100
        pes = player_econ_stats.get(steam_id, {})
        actual_rounds = pes.get("total_rounds", total_m * 20)
        est_rounds = max(1, actual_rounds)

        won_r = pes.get("won_rounds", 0)
        won_surv_pct = (pes.get("won_survived", 0) / max(1, won_r)) * 100 if won_r > 0 else 50.0

        lost_r = pes.get("lost_rounds", 0)
        save_rate_pct = (pes.get("lost_survived", 0) / max(1, lost_r)) * 100 if lost_r > 0 else 5.0

        ct_r = pes.get("ct_rounds", 0)
        ct_fd_pct = (pes.get("ct_first_deaths", 0) / max(1, ct_r)) * 100 if ct_r > 0 else 10.0

        eco_disc = clamp(won_surv_pct * 0.8 + (100.0 - ct_fd_pct * 2.0) * 0.2, 35.0, 95.0)
        buy_cons = clamp(50.0 + (won_surv_pct - 50.0) * 0.5 + (100.0 - ct_fd_pct * 2.0) * 0.3, 40.0, 95.0)

        eco_r = pes.get("eco_rounds", 0)
        eco_round_kills = (pes.get("eco_kills", 0) / max(1, eco_r)) if eco_r > 0 else 0.40

        force_deaths = pes.get("force_deaths", 0)
        force_buy_eff = (pes.get("force_kills", 0) / max(1, force_deaths)) if force_deaths > 0 else 1.0

        vs_full_d = pes.get("vs_full_deaths", 0)
        vs_full_kd = (pes.get("vs_full_kills", 0) / max(1, vs_full_d)) if vs_full_d > 0 else 1.0

        vs_force_d = pes.get("vs_force_deaths", 0)
        vs_force_kd = (pes.get("vs_force_kills", 0) / max(1, vs_force_d)) if vs_force_d > 0 else 1.1

        vs_eco_d = pes.get("vs_eco_deaths", 0)
        vs_eco_kd = (pes.get("vs_eco_kills", 0) / max(1, vs_eco_d)) if vs_eco_d > 0 else 1.3

        avg_adr = tot_adr / total_m
        avg_kast = tot_kast / total_m
        avg_hs = tot_hs / total_m
        kd_ratio = tot_kills / max(1, tot_deaths)
        kill_eff = (tot_kills / max(1, tot_kills + tot_deaths)) * 100

        cwr = (tot_clutch_wins / max(1, tot_clutch_attempts)) * 100 if tot_clutch_attempts > 0 else 25.0

        metrics = {
            "total_kills": tot_kills,
            "awp_kills": awp_k,
            "hs_percent": round(avg_hs, 1),
            "adr": round(avg_adr, 1),
            "kd_ratio": round(kd_ratio, 2),
            "kill_efficiency": round(kill_eff, 1),
            "dpr": round(tot_deaths / est_rounds, 2),
            "survival_rate": round((1 - (tot_deaths / est_rounds)) * 100, 1),
            "trade_death_rate": 20.0,
            "utility_damage": round(tot_ud / est_rounds, 1),
            "flash_assists": round(tot_fa / total_m, 2),
            "grenade_usage": 15.0,
            "kast": round(avg_kast, 1),
            "trade_rate": round((tot_tr / max(1, tot_kills)) * 100, 1),
            "round_impact": round(1.0 + (kd_ratio - 1.0) * 0.5, 2),
            "first_kill_rate": round((tot_fk / est_rounds) * 100, 1),
            "opening_involvement": round((tot_fk + tot_fd) / est_rounds, 2),
            "entry_success": round((tot_fk / max(1, tot_fk + tot_fd)) * 100, 1),
            "trade_percentage": round((tot_tr / max(1, tot_kills)) * 100, 1),
            "trade_speed": 3.0,
            "clutch_win_rate": round(cwr, 1),
            "clutch_attempts": float(tot_clutch_attempts),
            "clutch_wins": float(tot_clutch_wins),
            "eco_discipline": round(eco_disc, 1),
            "buy_consistency": round(buy_cons, 1),
            "won_round_survival": round(won_surv_pct, 1),
            "eco_round_kills": round(eco_round_kills, 2),
            "force_buy_eff": round(force_buy_eff, 2),
            "save_rate": round(save_rate_pct, 1),
            "vs_full_buy_kd": round(vs_full_kd, 2),
            "vs_force_buy_kd": round(vs_force_kd, 2),
            "vs_eco_kd": round(vs_eco_kd, 2),
            "first_death_rate": round((tot_fd / est_rounds) * 100, 1),
            "utility_damage_per_round": round(tot_ud / est_rounds, 1),
            "flash_assists_per_match": round(tot_fa / total_m, 2),
            "clutch_attempts_per_match": round(tot_clutch_attempts / total_m if total_m > 0 else 0, 2),
            "late_round_kills": 15.0,
            "awp_kills_percent": round(awp_pct, 1),
            "rifle_kills_percent": round(rifle_pct, 1)
        }

        p_data_temp = {"metrics": metrics}
        ratings = calculate_player_ratings(p_data_temp)
        style = detect_play_style(p_data_temp)
        strengths, weaknesses = identify_strengths_weaknesses(ratings, metrics)
        weapons = analyze_weapons(p_data_temp)
        map_perf = analyze_map_performance(matches, player_style=style, player_ratings=ratings, player_metrics=metrics)
        stability = calculate_stability(matches)
        pistols = analyze_pistol_rounds(matches)
        economy_stats = analyze_vs_economy(matches, metrics=metrics)

        # Вычисление формы (последние 5 матчей)
        p_history = p_mmr.get("history", [])
        form_dots = []
        for h in p_history[-5:]:
            if h.get("team_result") == "win":
                form_dots.append("win_high" if h.get("hltv", 1.0) >= 1.10 else "win_low")
            elif h.get("team_result") == "tie":
                form_dots.append("tie")
            else:
                form_dots.append("loss")

        # Проверка активности (30 дней)
        last_dt = p_mmr.get("latest_date", datetime.min)
        days_inactive = (latest_dataset_date - last_dt).days if latest_dataset_date != datetime.min else 0
        is_inactive = days_inactive > INACTIVITY_DAYS_THRESHOLD

        all_hltv = p_mmr.get("all_hltv", [])
        avg_hltv = round(sum(all_hltv) / max(1, len(all_hltv)), 2) if all_hltv else 1.00
        last_delta = p_history[-1]["delta"] if p_history else 0

        # Новые расширенные модули: 2D Архетип, Барометр формы, Связи и Ачивки
        archetype = calculate_archetype_matrix(metrics, style)
        session_progress = compute_session_progress(matches)
        momentum = calculate_player_momentum(avg_hltv, session_progress)

        # 1. Тиммейты (Синергия связок)
        syn = team_synergy.get(steam_id, {})
        dt_cands = []
        for partner_sid, st in syn.items():
            if st["matches"] >= 1:
                wr = (st["wins"] / st["matches"]) * 100
                dt_cands.append((partner_sid, st["matches"], st["wins"], wr))
        
        dream_team = None
        if dt_cands:
            multi_cands = [c for c in dt_cands if c[1] >= 2]
            best_dt = max(multi_cands or dt_cands, key=lambda x: (x[3], x[1]))
            dream_team = {
                "steam_id": best_dt[0],
                "name": canonical_names.get(best_dt[0], f"Player_{best_dt[0][-4:]}"),
                "matches": best_dt[1],
                "wins": best_dt[2],
                "win_rate": round(best_dt[3], 1)
            }
            
        tr_partners = trade_synergy.get(steam_id, {})
        trade_partner = None
        if tr_partners:
            best_tr = max(tr_partners.items(), key=lambda x: x[1])
            trade_partner = {
                "steam_id": best_tr[0],
                "name": canonical_names.get(best_tr[0], f"Player_{best_tr[0][-4:]}"),
                "trades": best_tr[1]
            }

        # 2. Противники (Очные дуэли: Немезида и Любимая жертва)
        duels = h2h_matrix.get(steam_id, {})
        nemesis = None
        fav_victim = None
        if duels:
            nem_cands = [(opp_id, d["deaths"], d["kills"]) for opp_id, d in duels.items() if d["deaths"] > 0]
            if nem_cands:
                best_nem = max(nem_cands, key=lambda x: (x[1] - x[2], x[1]))
                nemesis = {
                    "steam_id": best_nem[0],
                    "name": canonical_names.get(best_nem[0], f"Player_{best_nem[0][-4:]}"),
                    "killed_by": best_nem[1],
                    "kills_on": best_nem[2],
                    "diff": best_nem[2] - best_nem[1]
                }
                
            vic_cands = [(opp_id, d["kills"], d["deaths"]) for opp_id, d in duels.items() if d["kills"] > 0]
            if vic_cands:
                best_vic = max(vic_cands, key=lambda x: (x[1] - x[2], x[1]))
                fav_victim = {
                    "steam_id": best_vic[0],
                    "name": canonical_names.get(best_vic[0], f"Player_{best_vic[0][-4:]}"),
                    "kills_on": best_vic[1],
                    "killed_by": best_vic[2],
                    "diff": best_vic[1] - best_vic[2]
                }

        connections = {
            "teammates": {
                "dream_team": dream_team,
                "trade_partner": trade_partner
            },
            "rivals": {
                "nemesis": nemesis,
                "favorite_victim": fav_victim
            }
        }

        overall_stats_dict = {
            "total_matches": total_m,
            "total_rounds": actual_rounds,
            "total_kills": tot_kills,
            "total_deaths": tot_deaths,
            "total_assists": tot_assists,
            "kd_ratio": round(kd_ratio, 2),
            "avg_adr": round(avg_adr, 1),
            "avg_kast": round(avg_kast, 1),
            "avg_hs": round(avg_hs, 1),
            "total_first_kills": tot_fk,
            "total_first_deaths": tot_fd,
            "total_clutch_wins": tot_clutch_wins,
            "total_clutch_attempts": tot_clutch_attempts,
            "total_utility_damage": tot_ud,
            "total_flash_assists": tot_fa,
            "total_trades": tot_tr,
            "pistol_round_kills": sum(m.get("pistol_round_kills", 0) for m in matches)
        }

        # Специальные показатели для ачивок (Хайлайты, Оружие, Спец-раунды)
        spec = dict(player_special_events.get(steam_id, {}))
        spec["multi_kz_matches"] = sum(1 for m in matches if (m.get("weapon_kills", {}).get("knife", 0) + m.get("weapon_kills", {}).get("taser", 0) + m.get("weapon_kills", {}).get("zeus", 0)) >= 2)
        spec["save_rounds"] = pes.get("lost_survived", 0)
        spec["zero_fd_matches"] = sum(1 for m in matches if m.get("first_deaths", 0) == 0)
        spec["matches_25k"] = sum(1 for m in matches if m.get("kills", 0) >= 25)
        spec["high_hltv_matches"] = sum(1 for h in p_history if h.get("hltv", 0.0) >= 1.35)
        nem_id = nemesis.get("steam_id") if nemesis else None
        if nem_id:
            spec["nemesis_matches"] = sum(1 for md in match_duels_list if md.get((steam_id, nem_id), 0) >= 5)
        else:
            spec["nemesis_matches"] = sum(1 for md in match_duels_list if any(cnt >= 5 for (att, vic), cnt in md.items() if att == steam_id))

        achievements, ach_summary = calculate_player_achievements(
            metrics, overall_stats_dict, p_mmr, momentum,
            matches=matches, ratings=ratings, map_perf=map_perf,
            special_stats=spec, connections=connections
        )

        recs = generate_recommendations(
            p_data_temp, ratings, style,
            map_perf=map_perf, matches=matches,
            achievements=achievements
        )

        player_obj = {
            "steam_id": steam_id,
            "name": p_name,
            "ratings": ratings,
            "play_style": style,
            "archetype": archetype,
            "metrics": metrics,
            "overall_stats": overall_stats_dict,
            "mmr": {
                "current_mmr": p_mmr.get("current_mmr", STARTING_MMR),
                "peak_mmr": p_mmr.get("peak_mmr", STARTING_MMR),
                "last_delta": last_delta,
                "wins": p_mmr.get("wins", 0),
                "losses": p_mmr.get("losses", 0),
                "ties": p_mmr.get("ties", 0),
                "win_rate": round((p_mmr.get("wins", 0) / max(1, total_m)) * 100, 1),
                "avg_hltv": avg_hltv,
                "is_calibrating": total_m <= CALIBRATION_MATCH_LIMIT,
                "is_inactive": is_inactive,
                "form_dots": form_dots,
                "sparkline": [h["mmr_after"] for h in p_history],
                "history": p_history
            },
            "strengths": strengths,
            "weaknesses": weaknesses,
            "recommendations": recs,
            "stability": stability,
            "weapons": weapons,
            "map_performance": map_perf,
            "pistol_rounds": pistols,
            "vs_economy": economy_stats,
            "session_progress": session_progress,
            "momentum": momentum,
            "connections": connections,
            "achievements": achievements,
            "achievements_summary": ach_summary,
            "matches": matches
        }

        out_path = os.path.join(players_dir, f"{steam_id}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(player_obj, f, ensure_ascii=False, indent=4)

        print(f"Обработан игрок: {player_obj['name']} ({steam_id}) | MMR: {player_obj['mmr']['current_mmr']} (Peak: {player_obj['mmr']['peak_mmr']})")

    # 6. Экспорт глобальной матрицы Head-to-Head для интерактивного Бойцовского клуба и Матчмейкера
    all_players_summary = []
    if os.path.exists(players_dir):
        for pf in os.listdir(players_dir):
            if pf.endswith(".json"):
                try:
                    with open(os.path.join(players_dir, pf), "r", encoding="utf-8") as f:
                        po = json.load(f)
                    recs_p = po.get("recommendations", {})
                    c_role = recs_p.get("current_role", po["play_style"][0] if po.get("play_style") else "Универсал")
                    b_role = recs_p.get("best_role", c_role)
                    all_players_summary.append({
                        "steam_id": po["steam_id"],
                        "name": po["name"],
                        "mmr": po["mmr"]["current_mmr"],
                        "peak_mmr": po["mmr"]["peak_mmr"],
                        "hltv": po["mmr"]["avg_hltv"],
                        "score_10": po["ratings"].get("Overall Impact", 5.0),
                        "role": c_role,
                        "current_role": c_role,
                        "best_role": b_role,
                        "archetype": po.get("archetype", {}).get("title", "Универсальный тактик"),
                        "ratings": po.get("ratings", {}),
                        "metrics": {
                            "kd": po["overall_stats"]["kd_ratio"],
                            "adr": po["overall_stats"]["avg_adr"],
                            "hs": po["overall_stats"]["avg_hs"],
                            "kast": po["overall_stats"]["avg_kast"],
                            "winrate": po["mmr"]["win_rate"],
                            "matches": po["overall_stats"]["total_matches"]
                        }
                    })
                except Exception:
                    pass

    h2h_export = {
        "players": sorted(all_players_summary, key=lambda x: x["mmr"], reverse=True),
        "matrix": {
            s1: {s2: dict(h2h_matrix[s1][s2]) for s2 in h2h_matrix[s1]}
            for s1 in h2h_matrix
        },
        "teammates": {
            s1: {s2: dict(team_synergy[s1][s2]) for s2 in team_synergy[s1]}
            for s1 in team_synergy
        }
    }
    with open(DATA_DIR / "head_to_head.json", "w", encoding="utf-8") as f:
        json.dump(h2h_export, f, ensure_ascii=False, indent=2)

    # 7. Расчет 5 сессионных номинаций Зала славы для крайней сессии
    all_session_dates = set()
    for _, _, m_dict in match_items:
        d = str(m_dict.get("date", ""))[:8]
        if d:
            all_session_dates.add(d)
    
    if all_session_dates:
        latest_sess_date = sorted(list(all_session_dates), key=lambda x: datetime.strptime(x, "%d%m%Y") if len(x)==8 else datetime.min)[-1]
        sess_players = []
        
        for p_sum in all_players_summary:
            p_file = os.path.join(players_dir, f"{p_sum['steam_id']}.json")
            if os.path.exists(p_file):
                try:
                    with open(p_file, "r", encoding="utf-8") as f:
                        p_full = json.load(f)
                    sp = p_full.get("session_progress")
                    if sp and (sp.get("date") == latest_sess_date or sp.get("session_date") == latest_sess_date):
                        curr_s = sp.get("current") or sp.get("current_session") or {}
                        sess_players.append({
                            "steam_id": p_sum["steam_id"],
                            "name": p_sum["name"],
                            "hltv": curr_s.get("hltv", 1.0),
                            "adr": curr_s.get("adr", 0.0),
                            "hs_percent": curr_s.get("hs_percent", 0.0),
                            "clutches": curr_s.get("clutches", 0),
                            "deaths": curr_s.get("deaths", 0),
                            "first_deaths": curr_s.get("first_deaths", 0),
                            "kills": curr_s.get("kills", 0),
                            "mmr_delta": curr_s.get("mmr_delta", 0)
                        })
                except Exception:
                    pass
                    
        if sess_players:
            # 1. MVP
            mvp = max(sess_players, key=lambda x: (x["hltv"], x["kills"]))
            # 2. ADR Monster
            adr_monster = max(sess_players, key=lambda x: x["adr"])
            # 3. Headshot King (min 8 kills or highest)
            hs_pool = [p for p in sess_players if p["kills"] >= 8] or sess_players
            hs_king = max(hs_pool, key=lambda x: x["hs_percent"])
            # 4. Clutch Master
            clutch_master = max(sess_players, key=lambda x: (x["clutches"], x["hltv"]))
            # 5. Bullet Magnet (Принял огонь на себя: много смертей/первой агрессии)
            bullet_magnet = max(sess_players, key=lambda x: (x["deaths"] + x["first_deaths"]))
            
            awards = {
                "session_date": latest_sess_date,
                "mvp": {
                    "title": "MVP Сессии",
                    "player": mvp["name"],
                    "steam_id": mvp["steam_id"],
                    "value": f"{mvp['hltv']:.2f} HLTV",
                    "desc": f"Лучший интегральный перформанс дня ({mvp['kills']} фрагов, {mvp['mmr_delta']:+d} MMR)",
                    "icon": "👑"
                },
                "adr_monster": {
                    "title": "ADR Монстр",
                    "player": adr_monster["name"],
                    "steam_id": adr_monster["steam_id"],
                    "value": f"{adr_monster['adr']:.1f} ADR",
                    "desc": "Максимальное огневое давление и урон в каждом раунде",
                    "icon": "💥"
                },
                "headshot_king": {
                    "title": "Headshot King",
                    "player": hs_king["name"],
                    "steam_id": hs_king["steam_id"],
                    "value": f"{hs_king['hs_percent']:.1f}% HS",
                    "desc": "Хирургическая точность и доминирование прицела",
                    "icon": "🎯"
                },
                "clutch_master": {
                    "title": "Clutch Master",
                    "player": clutch_master["name"],
                    "steam_id": clutch_master["steam_id"],
                    "value": f"{clutch_master['clutches']} побед",
                    "desc": "Железные нервы и победы в ситуациях 1vX",
                    "icon": "🧠"
                },
                "bullet_magnet": {
                    "title": "Магнит пуль",
                    "player": bullet_magnet["name"],
                    "steam_id": bullet_magnet["steam_id"],
                    "value": f"{bullet_magnet['deaths']} смертей",
                    "desc": "Принял на себя основной урон врага, создавая пространство для команды",
                    "icon": "🧲"
                }
            }
            with open(DATA_DIR / "session_awards.json", "w", encoding="utf-8") as f:
                json.dump(awards, f, ensure_ascii=False, indent=2)

    print("Анализ и расчёт непрерывного MMR, рейтингов, связей и достижений успешно завершён!")

if __name__ == "__main__":
    run_analysis()

