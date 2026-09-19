import os
import json
import logging
import random
import time
from collections import Counter, defaultdict
from scripts.config import *

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def get_gemini_client():
    """Инициализация клиента Google Gemini (если ключ доступен)."""
    api_key = os.getenv("GEMINI_API_KEY", GEMINI_API_KEY)
    if not api_key:
        return None
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        return client
    except Exception as e:
        logging.warning(f"Не удалось инициализировать Gemini API: {e}")
        return None

def load_instruction_prompt() -> str:
    """Загрузка базовой инструкции по разбору раундов из instruction/rounds.txt."""
    if ROUNDS_INSTRUCTION_PATH.exists():
        try:
            with open(ROUNDS_INSTRUCTION_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            logging.warning(f"Не удалось прочитать {ROUNDS_INSTRUCTION_PATH}: {e}")
    return ""

def generate_tactical_round_analysis(
    round_data: dict,
    round_kills: list,
    round_damages: list,
    map_name: str,
    winning_team_name: str = None,
    ct_team_name: str = "Команда CT",
    t_team_name: str = "Команда T"
) -> str:
    """
    Глубокий экспертный тактический разбор раунда строго по 9 пунктам:
    1. Исход и сценарий
    2. Экономический триггер
    3. Тактика и Макро-анализ
    4. Микро-анализ и ключевые дуэли
    5. Главная ошибка раунда
    6. Хайлайт раунда
    7. Икс-Фактор раунда
    8. Использование утилиты
    9. Главный вывод для работы над ошибками
    """
    round_num = round_data.get('number') or round_data.get('round_num') or 1
    winner = str(round_data.get('winner', 'CT')).upper()
    reason = str(round_data.get('reason') or round_data.get('win_type') or 'ct_killed').lower()
    
    ct_eco = round_data.get('ct_economy', 'Full Buy')
    t_eco = round_data.get('t_economy', 'Full Buy')
    bomb_site = round_data.get('bomb_site')
    bomb_plant = round_data.get('bomb_plant', False)

    # 1. Исход и сценарий
    if "defus" in reason or "defuse" in reason:
        scenario = f"Победа CT ({ct_team_name}) через успешный ретейк и обезвреживание C4{' на ' + str(bomb_site) if bomb_site else ''}."
        macro_desc = f"CT грамотно координировали выбивание плента, отсекая углы и обеспечив прикрытие саперу."
    elif "bomb" in reason or "exploded" in reason or "target_bombed" in reason:
        scenario = f"Победа T ({t_team_name}) через установку и взрыв C4{' на пленте ' + str(bomb_site) if bomb_site else ''}."
        macro_desc = f"T успешно заняли плент, выставили глубокие кроссфаеры и удержали преимущество до детонации."
    elif "time" in reason:
        scenario = f"Победа CT ({ct_team_name}) по истечению времени раунда."
        macro_desc = f"CT заблокировали все подходы к точкам, лишив атаку времени на установку бомбы."
    else:
        if winner == "CT":
            scenario = f"Победа CT ({ct_team_name}) — полное уничтожение сил T."
            macro_desc = f"Плотная позиционная оборона CT и дисциплинированный прием выхода соперника."
        else:
            scenario = f"Победа T ({t_team_name}) — полное уничтожение сил CT."
            macro_desc = f"Силовой прорыв T с подавлением опорных точек обороны."

    # 2. Экономический триггер
    ct_weapons = set()
    t_weapons = set()
    for k in round_kills:
        side = str(k.get('attacker_side') or '').lower()
        w = k.get('weapon') or ''
        if side == 'ct' and w:
            ct_weapons.add(w)
        elif side == 't' and w:
            t_weapons.add(w)
            
    ct_w_str = ", ".join(list(ct_weapons)[:3]) if ct_weapons else "стандартные девайсы"
    t_w_str = ", ".join(list(t_weapons)[:3]) if t_weapons else "стандартные девайсы"
    
    if round_num in (1, 13):
        eco_desc = f"Пистолетный раунд (Pistol Battle). Обе команды в равных базовых условиях с дефолтными пистолетами и утилитой."
    elif "Eco" in ct_eco and "Full" in t_eco:
        eco_desc = f"Eco Buy от CT ({ct_w_str}) против Full Buy от T ({t_w_str}). Т-сторона реализовывала преимущество в броне и дистанции стрельбы."
    elif "Full" in ct_eco and "Eco" in t_eco:
        eco_desc = f"Full Buy от CT ({ct_w_str}) против Eco Buy от T ({t_w_str}). Защита использовала финансовый перевес для тотального контроля карты."
    elif "Semi" in t_eco or "Force" in t_eco:
        eco_desc = f"{ct_eco} от CT против {t_eco} от T ({t_w_str}). Нестандартный закуп заставил атакующую сторону форсировать темп."
    else:
        eco_desc = f"Оружейный раунд: CT ({ct_eco}) против T ({t_eco}). Полноценное тактическое противостояние на винтовках."

    # 3. Тактика и Макро-анализ
    if bomb_plant:
        tactic_desc = f"T провели векторную атаку на плент {bomb_site or 'точки'}. Защита CT опоздала со стяжкой с противоположного фланга, оказавшись в невыгодной ситуации для выбивания."
    elif winner == "CT":
        tactic_desc = f"Дефолт защиты CT сработал безупречно: перекрестный контроль ключевых зон карты не позволил атаке развить преимущество в первом темпе."
    else:
        tactic_desc = f"T использовали численное преимущество и быстрый сплит, разбив оборону CT на изолированные дуэли без возможности размена."

    # 4. Микро-анализ и ключевые дуэли
    kill_events_desc = []
    player_kills_count = {}
    
    if round_kills:
        first_k = round_kills[0]
        fk_att = first_k.get('attacker_name') or 'Игрок'
        fk_vic = first_k.get('victim_name') or 'Соперник'
        fk_wpn = first_k.get('weapon') or 'оружие'
        fk_hs = " (Headshot 🎯)" if first_k.get('headshot') else ""
        fk_side = str(first_k.get('attacker_side') or '').upper()
        
        raw_place = first_k.get('attacker_place') or first_k.get('victim_place') or 'позиция'
        fk_place = translate_callout(map_name, raw_place)
        
        fk_desc = f"First Blood: {fk_att} ({fk_side}, {fk_wpn}{fk_hs}) срезает {fk_vic} в зоне [{fk_place}]."
        kill_events_desc.append(fk_desc)
        
        for k in round_kills:
            att = k.get('attacker_name') or 'Игрок'
            player_kills_count[att] = player_kills_count.get(att, 0) + 1
            
        if len(round_kills) > 1:
            mid_k = round_kills[1]
            m_att = mid_k.get('attacker_name')
            m_vic = mid_k.get('victim_name')
            m_wpn = mid_k.get('weapon')
            m_place = translate_callout(map_name, mid_k.get('victim_place') or '')
            kill_events_desc.append(f"Последующий контакт: {m_att} с {m_wpn} забирает {m_vic} [{m_place}].")
            
        last_k = round_kills[-1]
        l_att = last_k.get('attacker_name')
        l_vic = last_k.get('victim_name')
        l_wpn = last_k.get('weapon')
        if l_att != fk_att or len(round_kills) > 2:
            kill_events_desc.append(f"Финальную точку поставил {l_att}, закрыв {l_vic} из {l_wpn}.")
    else:
        kill_events_desc.append("Раунд прошел без активных боевых столкновений.")

    micro_desc = " ".join(kill_events_desc)

    # 5. Главная ошибка раунда
    if "Eco" in (ct_eco if winner == "T" else t_eco):
        mistake_desc = f"Принятие проигравшей стороной открытых лобовых перестрелок на эко/форс закупке против дальнобойного оружия соперника."
    elif round_kills and round_kills[0].get('attacker_side') == ('T' if winner == 'T' else 'CT'):
        mistake_desc = f"Безответная первая смерть опорника на ключевом тайминге без возможности своевременного размена сокомандниками."
    elif "time" in reason:
        mistake_desc = f"Слишком пассивная игра атаки на таймере, закончившаяся потерей контроля над пространством карты."
    else:
        mistake_desc = f"Нарушение позиционной дисциплины и неоправданные пики без флеш-поддержки тиммейтов."

    # 6. Хайлайт раунда
    top_frag_player, top_frags = None, 0
    if player_kills_count:
        top_frag_player, top_frags = max(player_kills_count.items(), key=lambda x: x[1])

    if top_frags >= 5:
        highlight_desc = f"👑 ЭЙС (5 фрагов) от {top_frag_player}! Выдающееся индивидуальное выступление и полное доминирование в раунде."
    elif top_frags == 4:
        highlight_desc = f"🔥 Квадро-килл (4 фрага) от {top_frag_player}! Соло-выигрыш важнейшего раунда для своей команды."
    elif top_frags == 3:
        highlight_desc = f"🎯 Тройное убийство (3 фрага) от {top_frag_player}, переломившее ход схватки."
    elif round_kills:
        fk_hero = round_kills[0].get('attacker_name')
        highlight_desc = f"Ключевой опенинг-фраг от {fk_hero}, давший численное преимущество с первых секунд."
    else:
        highlight_desc = "Безупречное тактическое позиционирование без необходимости рискованных дуэлей."

    # 7. Икс-Фактор раунда
    if top_frags >= 3:
        xfactor_desc = f"Высочайшая механическая точность и хладнокровие {top_frag_player}, не оставившего шансов соперникам."
    elif bomb_plant:
        xfactor_desc = "Скорость доставки и установки C4, вынудившая защиту стягиваться в спешке и на невыгодных условиях."
    elif "Eco" in ct_eco or "Eco" in t_eco:
        xfactor_desc = "Темп продвижения победившей стороны, не позволивший сопернику реализовать засады на эко."
    else:
        xfactor_desc = "Своевременный саппорт-контроль и выверенный тайминг поджима карты."

    # 8. Использование утилиты
    util_dmg_total = 0
    util_by_author = {}
    for d in (round_damages or []):
        dmg_val = d.get('dmg') or 0
        att_name = d.get('attacker_name') or 'Игрок'
        wpn = d.get('weapon') or 'grenade'
        if wpn in ('hegrenade', 'inferno', 'molotov'):
            util_dmg_total += dmg_val
            util_by_author[att_name] = util_by_author.get(att_name, 0) + dmg_val

    if util_dmg_total > 0:
        authors_breakdown = ", ".join([f"{a}: {d} HP" for a, d in util_by_author.items()])
        util_desc = f"{util_dmg_total} HP урона гранатами ({authors_breakdown})."
    else:
        util_desc = "0 HP урона гранатами."

    # 9. Главный вывод для работы над ошибками
    if "Eco" in (ct_eco if winner == "T" else t_eco):
        lesson_desc = "На эко-раундах необходимо играть от глубоких засад, закрытых позиций и перекрестного огня, избегая открытых дистанционных перестрелок."
    elif bomb_plant and winner == "T":
        lesson_desc = "CT требуется быстрее передавать информацию о векторе атаки и тренировать синхронные совместные ретейки, а не входить в плент по одному."
    else:
        lesson_desc = "Требуется жестче контролировать открывающие дуэли и всегда готовить флеш-поддержку при проверке опасных углов."

    report = (
        f"**1. Исход и сценарий:** {scenario} {macro_desc}\n\n"
        f"**2. Экономический триггер:** {eco_desc}\n\n"
        f"**3. Тактика и Макро-анализ:** {tactic_desc}\n\n"
        f"**4. Микро-анализ и ключевые дуэли:** {micro_desc}\n\n"
        f"**5. Главная ошибка раунда:** {mistake_desc}\n\n"
        f"**6. Хайлайт раунда:** {highlight_desc}\n\n"
        f"**7. Икс-Фактор раунда:** {xfactor_desc}\n\n"
        f"**8. Использование утилиты:** {util_desc}\n\n"
        f"**9. Главный вывод для работы над ошибками:** {lesson_desc}"
    )
    return report

def analyze_round_with_ai(
    round_data: dict,
    round_kills: list,
    round_damages: list,
    map_name: str,
    winning_team_name: str = None,
    ct_team_name: str = "Команда CT",
    t_team_name: str = "Команда T"
) -> str:
    """Генерация комментаторского тактического разбора раунда (через Gemini API или экспертный движок)."""
    round_num = round_data.get('number') or round_data.get('round_num') or 1
    winner = str(round_data.get('winner', 'CT')).upper()
    win_type = round_data.get('win_type') or round_data.get('reason') or 'Уничтожение'

    client = get_gemini_client()
    if client:
        instruction_base = load_instruction_prompt()
        prompt = f"""{instruction_base}

Проведи глубокий тактический разбор раунда #{round_num} на карте {map_name} строго по 9 пунктам из инструкции.

Детали раунда:
- Победитель: {winning_team_name or winner} ({win_type})
- Экономика CT ({ct_team_name}): {round_data.get('ct_economy', 'Full Buy')}
- Экономика T ({t_team_name}): {round_data.get('t_economy', 'Full Buy')}
- C4: заложена={round_data.get('bomb_plant', False)}, плент={round_data.get('bomb_site', 'нет')}

События убийств:
"""
        for k in round_kills:
            att = k.get('attacker_name') or 'Игрок'
            vic = k.get('victim_name') or 'Игрок'
            wpn = k.get('weapon') or 'девайс'
            hs = " (HS 🎯)" if k.get('headshot') else ""
            side = str(k.get('attacker_side') or '').upper()
            place = translate_callout(map_name, k.get('attacker_place') or k.get('victim_place') or '')
            prompt += f"- {att} ({side}) убил {vic} из {wpn}{hs} в зоне [{place}]\n"

        prompt += "\nСформируй подробный 9-пунктовый разбор без вводных слов и лишних шаблонных фраз."

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=AI_MODEL,
                    contents=prompt,
                )
                text = response.text.strip()
                if text and ("1. Исход и сценарий" in text or "1. Исход" in text):
                    time.sleep(1.0)  # Безопасный интервал для соблюдения квоты RPM
                    return text
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
                    logging.warning(f"Лимит запросов Gemini (429) на раунде {round_num}, пауза 8 сек... (попытка {attempt+1}/3)")
                    time.sleep(8)
                    continue
                else:
                    logging.warning(f"Ошибка вызова AI API для раунда {round_num}: {e}")
                    break

    # Fallback локальный экспертный движок
    return generate_tactical_round_analysis(
        round_data, round_kills, round_damages, map_name, winning_team_name, ct_team_name, t_team_name
    )

def generate_match_intro_commentary(match_data: dict) -> str:
    """Генерация аналитического вводного обзора всего матча для команд."""
    map_name = match_data.get('map_display') or match_data.get('map_name') or match_data.get('map', 'Mirage')
    if map_name.startswith('de_'):
        map_name = map_name[3:].title()

    score1 = match_data.get('score1')
    if score1 is None:
        score1 = match_data.get('score_team1', 0)
    
    score2 = match_data.get('score2')
    if score2 is None:
        score2 = match_data.get('score_team2', 0)

    t1_name = match_data.get('team1_name') or "Команда 1"
    t2_name = match_data.get('team2_name') or "Команда 2"

    # Ищем лучшего игрока матча
    mvp = "Игрок"
    players = match_data.get('players', {})
    if isinstance(players, dict) and players:
        best_p = max(players.values(), key=lambda p: (p.get('hltv_rating', 0.0), p.get('adr', 0)))
        mvp = best_p.get('name', 'Игрок')
    elif match_data.get('stats', {}).get('adr_leader', {}).get('name'):
        mvp = match_data.get('stats', {}).get('adr_leader', {}).get('name')

    client = get_gemini_client()
    if client:
        prompt = f"""Ты — главная аналитическая студия CS2 (в стиле HLTV / BLAST). Напиши яркий вводный обзор матча {t1_name} против {t2_name} на карте {map_name}.
Итоговый счет: {t1_name} ({score1}) — {t2_name} ({score2}).
Лидер матча (MVP): {mvp}.

Составь обзор в 2 коротких абзаца:
1. Итоги битвы и ключевой переломный момент матча на карте {map_name}.
2. Анализ игры победившей и проигравшей команды.
"""
        try:
            response = client.models.generate_content(
                model=AI_MODEL,
                contents=prompt,
            )
            text = response.text.strip()
            if text and "0 : 0" not in text:
                return text
        except Exception as e:
            logging.warning(f"Ошибка ИИ-обзора матча: {e}")

    # Fallback динамический обзор матча с учётом счета и карты
    if score1 > score2:
        winner_team = t1_name
        loser_team = t2_name
    elif score2 > score1:
        winner_team = t2_name
        loser_team = t1_name
    else:
        winner_team = "Ничья"
        loser_team = ""

    diff = abs(score1 - score2)
    if diff >= 5:
        intensity = "завершился убедительной победой"
        climax = f"{winner_team} полностью захватила инициативу со стартовых раундов и не дала сопернику восстановить экономику."
    elif diff >= 2:
        intensity = "прошел в плотной конкурентной борьбе"
        climax = f"Судьба матча решалась в последних оружейных раундах, где {winner_team} проявила хладнокровие в ключевых ситуациях."
    else:
        intensity = "завершился упорнейшим овертаймом"
        climax = "Каждая раунд разыгрывался до последней секунды, а разница в счете составила считанные фраги."

    if winner_team == "Ничья":
        return (f"Матч на карте **{map_name}** завершился боевой ничьей со счетом **{score1} : {score2}**. "
                f"Команды показали равный уровень подготовки, а MVP встречи стал **{mvp}**.")

    return (f"Матч на карте **{map_name}** {intensity} — счет **{score1} : {score2}** в пользу **{winner_team}**. "
            f"{climax} Ключевой фигурой противостояния стал **{mvp}**, продемонстрировавший высокий ADR и импакт во всех фазах игры.")

def analyze_player_with_ai(player_name: str, ratings: dict, stats: dict, style: list) -> str:
    """Генерация AI-рекомендаций для игрока."""
    client = get_gemini_client()
    if not client:
        return ""

    prompt = f"""Ты — профессиональный киберспортивный тренер CS2.
Дай развернутые персональные рекомендации для игрока {player_name}:

Рейтинги (1-10):
- Aim: {ratings.get('aim', 5.0)}
- Positioning: {ratings.get('positioning', 5.0)}
- Utility: {ratings.get('utility', 5.0)}
- Game Sense: {ratings.get('game_sense', 5.0)}
- Entry: {ratings.get('entry', 5.0)}
- Trading: {ratings.get('trading', 5.0)}
- Clutch: {ratings.get('clutch', 5.0)}
- Discipline: {ratings.get('discipline', 5.0)}
- Economy: {ratings.get('economy', 5.0)}
- Overall Impact: {ratings.get('overall_impact', 5.0)}

Стиль игры: {', '.join(style)}

Напиши профессиональный отзыв тренера (на русском языке):
1. Сильные стороны
2. Слабые стороны
3. Что конкретно тренировать (упражнения, карты, режим)
4. Какую роль лучше всего выполнять
"""
    try:
        response = client.models.generate_content(
            model=AI_MODEL,
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        logging.warning(f"Ошибка вызова AI API для игрока {player_name}: {e}")
        return ""

def extract_tactical_match_context(match_data: dict) -> dict:
    """
    Извлекает глубокий тактический контекст матча для ИИ и локального анализатора:
    - Первые дуэли и зоны контактов (First Blood)
    - Процент неразмененных смертей (Untraded deaths)
    - Ошибки и поражения на эко-раундах (Anti-eco fails)
    - Успешность плентов и ретейков (A vs B, Defuses)
    - Урон гранатами и флеш-эффективность
    - Динамика счёта и баланс половин
    """
    map_name = match_data.get('map_display') or match_data.get('map', 'Mirage')
    if map_name.startswith('de_'):
        map_name = map_name[3:].title()

    rounds = match_data.get('rounds', [])
    kills = match_data.get('kills', [])
    damages = match_data.get('damages', [])
    players = match_data.get('players', {})

    # 1. Первые дуэли раундов (First Blood) и зоны
    fb_zones_counter = Counter()
    fb_by_round = {}
    for k in kills:
        r_num = k.get('round_num')
        if r_num not in fb_by_round:
            fb_by_round[r_num] = k
            raw_place = k.get('victim_place') or k.get('attacker_place') or ''
            if raw_place and str(raw_place) != 'nan':
                place_ru = translate_callout(map_name, raw_place)
                fb_zones_counter[place_ru] += 1

    # Размен в первые 5 секунд (~320 тиков при 64 tick)
    untraded_first_deaths = 0
    traded_first_deaths = 0
    for r_num, fk in fb_by_round.items():
        v_team = fk.get('victim_side')
        v_time = fk.get('tick') or 0
        traded = False
        for k in kills:
            if k.get('round_num') == r_num and k.get('attacker_side') == v_team:
                if 0 < (k.get('tick', 0) - v_time) <= 320:
                    traded = True
                    break
        if traded:
            traded_first_deaths += 1
        else:
            untraded_first_deaths += 1

    total_fb = len(fb_by_round)
    untraded_pct = round((untraded_first_deaths / max(1, total_fb)) * 100, 1)

    # 2. Провалы на анти-эко (Full Buy против Eco/Semi-Eco)
    anti_eco_throws = []
    for r in rounds:
        ct_eco = str(r.get('ct_economy', 'Full Buy'))
        t_eco = str(r.get('t_economy', 'Full Buy'))
        winner = str(r.get('winner', 'ct')).lower()
        r_num = r.get('round_num')
        if winner == 'ct' and ('Eco' in ct_eco or 'Semi-Eco' in ct_eco) and 'Full' in t_eco:
            anti_eco_throws.append(f"раунд #{r_num} (Full Buy атаки отдан CT на эко)")
        elif winner == 't' and ('Eco' in t_eco or 'Semi-Eco' in t_eco) and 'Full' in ct_eco:
            anti_eco_throws.append(f"раунд #{r_num} (Full Buy защиты отдан T на эко)")

    # 3. Закладки C4 и ретейки
    plant_rounds = [r for r in rounds if r.get('bomb_plant') is True or r.get('bomb_site') in ('A', 'B')]
    a_plants = sum(1 for r in plant_rounds if str(r.get('bomb_site')).upper() == 'A')
    b_plants = sum(1 for r in plant_rounds if str(r.get('bomb_site')).upper() == 'B')
    defuses = sum(1 for r in plant_rounds if 'defuse' in str(r.get('reason', '')).lower())
    total_plants = len(plant_rounds)
    retake_success_pct = round((defuses / max(1, total_plants)) * 100, 1) if total_plants > 0 else 0

    # 4. Гранаты и флеш-ассисты
    util_dmg_total = sum((d.get('dmg', 0) or 0) for d in damages if d.get('weapon') in ('hegrenade', 'inferno', 'molotov'))
    total_flash_assists = sum(p.get('flash_assists', 0) for p in players.values())
    rounds_count = max(1, len(rounds))
    avg_util_per_round = round(util_dmg_total / rounds_count, 1)

    # 5. Счёт матча и половины
    score1 = match_data.get('score1') if match_data.get('score1') is not None else match_data.get('score_team1', 0)
    score2 = match_data.get('score2') if match_data.get('score2') is not None else match_data.get('score_team2', 0)
    t1_r1_12 = sum(1 for r in rounds if (r.get('round_num') or 0) <= 12 and r.get('winning_team') == 'team1')
    t2_r1_12 = sum(1 for r in rounds if (r.get('round_num') or 0) <= 12 and r.get('winning_team') == 'team2')

    top_zones = [zone for zone, _ in fb_zones_counter.most_common(4)]

    return {
        "map_name": map_name,
        "score1": score1,
        "score2": score2,
        "half_score": f"{t1_r1_12}:{t2_r1_12}",
        "top_fb_zones": [f"{zone} ({cnt} дуэлей)" for zone, cnt in fb_zones_counter.most_common(4)],
        "top_zones_clean": top_zones,
        "untraded_first_deaths": untraded_first_deaths,
        "total_fb": total_fb,
        "untraded_pct": untraded_pct,
        "anti_eco_throws": anti_eco_throws,
        "total_plants": total_plants,
        "a_plants": a_plants,
        "b_plants": b_plants,
        "defuses": defuses,
        "retake_success_pct": retake_success_pct,
        "avg_util_per_round": avg_util_per_round,
        "total_flash_assists": total_flash_assists,
    }

def analyze_match_tactical_problems(match: dict) -> list[dict]:
    """
    Глубокий анализ тактических проблем матча по 11+ сценариям.
    Ранжирует проблемы по степени остроты (severity) и возвращает ТОП-3.
    """
    map_name = match.get('map_display') or match.get('map', 'Mirage')
    if map_name.startswith('de_'):
        map_name = map_name[3:].title()

    rounds = match.get('rounds', [])
    kills = match.get('kills', [])
    damages = match.get('damages', [])
    players = match.get('players', {})
    total_rounds = max(1, len(rounds))

    problems = []

    # 1. Анализ первых смертей игроков (Кто чаще всего падал первым и где)
    fd_player_counts = Counter()
    fd_player_places = defaultdict(Counter)
    fb_by_round = {}
    for k in kills:
        r_num = k.get('round_num')
        if r_num not in fb_by_round:
            fb_by_round[r_num] = k
            vic = k.get('victim_name') or 'Игрок'
            place = k.get('victim_place') or k.get('attacker_place') or ''
            place_ru = translate_callout(map_name, place)
            fd_player_counts[vic] += 1
            if place_ru and place_ru != 'Зона карты':
                fd_player_places[vic][place_ru] += 1

    # Неразмененные опенинг-дуэли
    untraded_first_deaths = 0
    for r_num, fk in fb_by_round.items():
        v_team = fk.get('victim_side')
        v_time = fk.get('tick') or 0
        traded = False
        for k in kills:
            if k.get('round_num') == r_num and k.get('attacker_side') == v_team:
                if 0 < (k.get('tick', 0) - v_time) <= 320:
                    traded = True
                    break
        if not traded:
            untraded_first_deaths += 1

    untraded_pct = round((untraded_first_deaths / max(1, len(fb_by_round))) * 100, 1)

    # Проверяем явную уязвимость конкретного игрока
    if fd_player_counts:
        worst_fd_player, worst_fd_cnt = fd_player_counts.most_common(1)[0]
        if worst_fd_cnt >= 4:
            fav_place = fd_player_places[worst_fd_player].most_common(1)
            place_text = f" в районе зоны {fav_place[0][0]}" if fav_place else ""
            severity = 80 + worst_fd_cnt * 5
            problems.append({
                "severity": severity,
                "title": f"Позиционная уязвимость опорника ({worst_fd_player})",
                "text": f"Игрок **{worst_fd_player}** отдал **{worst_fd_cnt} первых смертей** за матч{place_text}, регулярно оставляя свою команду в ситуации 4v5 со стартовых секунд. Соперник явно нащупал эту брешь в расстановке и раз за разом форсировал контакт на его направлении. **Что тренировать:** перестроить дефолт, играть более пассивно от глубины сайта, либо выделять второго игрока для создания перекрестного огня и быстрой страховки."
            })

    # Высокий процент неразмененных опенингов
    if untraded_pct >= 55:
        top_places = Counter([translate_callout(map_name, k.get('victim_place') or k.get('attacker_place') or '') for k in fb_by_round.values()]).most_common(2)
        top_places_str = ", ".join([p[0] for p in top_places if p[0] and p[0] != 'Зона карты']) or "ключевых проходах"
        problems.append({
            "severity": 75 + int(untraded_pct / 5),
            "title": f"Изолированные дуэли и разрыв дистанции на {top_places_str}",
            "text": f"**{untraded_pct}% первых столкновений** ({untraded_first_deaths} из {len(fb_by_round)}) закончились гибелью игрока без ответа со стороны тиммейтов. Игроки предпринимают агрессивные индивидуальные выпады на дистанции, где партнеры физически не успевают среагировать и дать размен. **Что тренировать:** отработка правила 2 секунд — второй номер должен двигаться строго позади энтри и быть готовым пикать на размен мгновенно после звука выстрелов."
        })

    # 2. Провалы против эко и форс-закупов
    anti_eco_fails = []
    for r in rounds:
        ct_eco = str(r.get('ct_economy', 'Full Buy'))
        t_eco = str(r.get('t_economy', 'Full Buy'))
        winner = str(r.get('winner', 'ct')).lower()
        r_num = r.get('round_num')
        if winner == 'ct' and ('Eco' in ct_eco or 'Semi-Eco' in ct_eco) and 'Full' in t_eco:
            anti_eco_fails.append(f"раунд #{r_num} (атака слила эко CT)")
        elif winner == 't' and ('Eco' in t_eco or 'Semi-Eco' in t_eco) and 'Full' in ct_eco:
            anti_eco_fails.append(f"раунд #{r_num} (защита слила эко T)")

    if anti_eco_fails:
        cnt = len(anti_eco_fails)
        severity = 85 + cnt * 10
        rounds_str = ", ".join(anti_eco_fails[:3])
        problems.append({
            "severity": severity,
            "title": f"Недооценка соперника на эко-раундах ({cnt} сданных раундов)",
            "text": f"Команды допустили критические ошибки в оружейных раундах против пистолетов ({rounds_str}). Имея подавляющее превосходство в дальности и огневой мощи винтовок, игроки лезли в узкие коридоры и принимали упор-дуэли против Deagle и фарм-ганов. **Что тренировать:** на анти-эко запрещено входить в ближний контакт без предварительного закидывания хаешками и молотовыми; растягивать оборону и расстреливать соперника исключительно на дальних дистанциях."
        })

    # 3. Раунды, проигранные по времени (Time-out losses)
    time_losses = sum(1 for r in rounds if 'time' in str(r.get('reason', '')).lower())
    if time_losses >= 2:
        problems.append({
            "severity": 77 + time_losses * 5,
            "title": f"Потеря таймингов и срыв темпа атаки ({time_losses} раунда проиграны по таймеру)",
            "text": f"Атакующая сторона {time_losses} раз(а) не успела установить C4 до истечения времени раунда. Команда слишком долго холдит карту без навязывания давления, растрачивая драгоценные секунды, и выходит на точку под прессингом тикающего таймера. **Что тренировать:** решение о финальном выходе или ротации должно приниматься не позднее 45-й секунды раунда."
        })

    # 4. Провал ретейков защиты или удержания бомбы атакой
    plants = [r for r in rounds if r.get('bomb_plant') is True or r.get('bomb_site') in ('A', 'B')]
    a_plants = sum(1 for r in plants if str(r.get('bomb_site')).upper() == 'A')
    b_plants = sum(1 for r in plants if str(r.get('bomb_site')).upper() == 'B')
    defuses = sum(1 for r in plants if 'defuse' in str(r.get('reason', '')).lower())
    
    if len(plants) >= 4:
        retake_pct = round((defuses / len(plants)) * 100, 1)
        if retake_pct <= 25:
            worst_site = "A" if a_plants >= b_plants else "B"
            problems.append({
                "severity": 80,
                "title": f"Бессилие в ретейках (лишь {retake_pct}% успешных выбиваний)",
                "text": f"Из {len(plants)} установленных бомб защита сумела разминировать только {defuses}. Основной удар пришелся на **плент {worst_site}** ({max(a_plants, b_plants)} закладок). Защитники стягиваются с запозданием, входят на точку поодиночке без флешек и погибают в узких проходах. **Что тренировать:** командный ретейк 3v3 — синхронизация одновременного входа с двух сторон под совместный отброс слеповых гранат."
            })
    elif len(plants) == 0 and total_rounds >= 15:
        problems.append({
            "severity": 70,
            "title": "Срыв доставки C4 на пленты (0 установок бомбы)",
            "text": f"За весь матч атака ни разу не смогла заложить бомбу на точку, раунды заканчивались исключительно взаимным истреблением на подступах. Атакующей стороне не хватало базового сплит-выхода и сброса смоков на пленты. **Что тренировать:** заучить дефолтный экзекьют с тремя обязательными смоками и ставить C4 в первые 45 секунд после получения опенинг-фрага."
        })

    # 5. Снайперский террор / AWP доминирование
    awp_kills_by_player = Counter()
    for k in kills:
        if k.get('weapon') == 'awp':
            awp_kills_by_player[k.get('attacker_name') or 'Снайпер'] += 1

    if awp_kills_by_player:
        top_awper, awp_cnt = awp_kills_by_player.most_common(1)[0]
        if awp_cnt >= 8:
            problems.append({
                "severity": 78,
                "title": f"Безнаказанность снайпера ({top_awper}: {awp_cnt} фрагов с AWP)",
                "text": f"**{top_awper}** держал в страхе всю карту, настреляв {awp_cnt} фрагов со снайперской винтовки. Соперники не использовали глубокие смоки и флешки через крыши, чтобы согнать AWP с привычных позиций, и регулярно выходили на него 'в прицел'. **Что тренировать:** изучить анти-снайперские траектории гранат на {map_name}, не пикать снайпера без флешки и отрезать его позиции дымами со старта."
            })

    # 6. Дисбаланс половин (Коллапс стороны защиты или атаки)
    t1_half = sum(1 for r in rounds if (r.get('round_num') or 0) <= 12 and r.get('winning_team') == 'team1')
    t2_half = 12 - t1_half
    half_diff = abs(t1_half - t2_half)
    if half_diff >= 6:
        dom_team = match.get('team1_name') if t1_half > t2_half else match.get('team2_name')
        loser_team = match.get('team2_name') if t1_half > t2_half else match.get('team1_name')
        problems.append({
            "severity": 72,
            "title": f"Тактический ступор в первой половине ({max(t1_half, t2_half)}:{min(t1_half, t2_half)})",
            "text": f"В первой половине матча **{loser_team}** полностью отдала нити игры сопернику, взяв всего {min(t1_half, t2_half)} раундов из 12. Команда не смогла адаптироваться к быстрому темпу **{dom_team}** и продолжала использовать одну и ту же неработающую схему. **Что тренировать:** развивать навык внутриматчевой адаптации — если дефолт не работает 3 раунда подряд, капитан обязан брать паузу и менять темп."
        })

    # 7. Дефицит утилиты / флешек
    util_dmg_total = sum((d.get('dmg', 0) or 0) for d in damages if d.get('weapon') in ('hegrenade', 'inferno', 'molotov'))
    avg_util = round(util_dmg_total / total_rounds, 1)
    tot_flashes = sum(p.get('flash_assists', 0) for p in players.values())
    if avg_util < 16:
        problems.append({
            "severity": 68,
            "title": f"Пассивность по гранатам (всего {avg_util} HP урона за раунд)",
            "text": f"Игроки экономят на гранатах либо погибают с полным запасом в карманах. На карте {map_name} удержание ключевых рубежей без регулярного нанесения урона молотовыми и хаешками невозможно. **Что тренировать:** ввести обязательный командный закуп утилиты в каждом оружейном раунде и отработать стартовый проброс осколочных гранат по таймингу спавна соперника."
        })
    elif tot_flashes <= 3:
        problems.append({
            "severity": 65,
            "title": f"Недостаток командного ослепления (лишь {tot_flashes} флеш-ассиста за матч)",
            "text": f"Практически все контактные стычки велись 'в сухую', без предварительного ослепления позиций противника. Это приводит к лишним потерям при чеке стандартных укрытий. **Что тренировать:** разучить 3 базовых pop-flash для тиммейтов на {map_name} и запретить выход на чек открытых углов без запроса флешки от напарника."
        })

    # 8. Пистолетные раунды
    p1 = next((r for r in rounds if r.get('round_num') == 1), None)
    p2 = next((r for r in rounds if r.get('round_num') == 13), None)
    if p1 and p2 and p1.get('winning_team') == p2.get('winning_team') and p1.get('winning_team') in ('team1', 'team2'):
        p_winner = match.get('team1_name') if p1.get('winning_team') == 'team1' else match.get('team2_name')
        p_loser = match.get('team2_name') if p1.get('winning_team') == 'team1' else match.get('team1_name')
        problems.append({
            "severity": 66,
            "title": f"Чистый проигрыш пистолетных серий (0:2 в пользу {p_winner})",
            "text": f"**{p_loser}** проиграла обе пистолетки в матче, автоматически отдавая оппоненту стартовое экономическое преимущество в обеих половинах (потеря темпа минимум на 4-5 раундов). **Что тренировать:** уделить внимание пистолетным заготовкам: командные закупки (броня + гранаты у саппортов), групповые выходы и разминка на Pistol DM перед официальными играми."
        })

    # 9. Базовые сценарии для гарантии выбора ТОП-3
    top_places = Counter([translate_callout(map_name, k.get('victim_place') or k.get('attacker_place') or '') for k in fb_by_round.values()]).most_common(2)
    zones_str = ", ".join([p[0] for p in top_places if p[0] and p[0] != 'Зона карты']) or "ключевых рубежах карты"
    problems.append({
        "severity": 55,
        "title": f"Тайминговая борьба за {zones_str}",
        "text": f"Основная масса первых контактов на {map_name} происходила на этих направлениях. Команде необходимо отрабатывать стартовую раскидку: встречные заградительные молотовы и глубокие смоки, нейтрализующие раннюю агрессию соперника."
    })
    problems.append({
        "severity": 50,
        "title": f"Дисциплина в пост-плант расстановках на {map_name}",
        "text": f"После установки C4 игроки защиты и атаки допускали несогласованные пики вместо затягивания времени и перекрестного прикрытия. Требуется отработать позиции кросс-файра и игру строго на звук разминирования."
    })

    problems.sort(key=lambda x: x["severity"], reverse=True)
    return problems[:3]

def generate_tactical_takeaways_fallback(match_data: dict) -> str:
    """
    Генерирует 3 высокоточных тактических вывода для тренировок на основе реальных данных матча.
    """
    map_name = match_data.get('map_display') or match_data.get('map_name') or match_data.get('map', 'Mirage')
    if map_name.startswith('de_'):
        map_name = map_name[3:].title()

    probs = analyze_match_tactical_problems(match_data)
    p1, p2, p3 = probs[0], probs[1], probs[2]

    return (
        f"### 🏆 2. ГЛАВНЫЙ ВЫВОД ДЛЯ РАБОТЫ НАД ОШИБКАМИ\n"
        f"На основе тактического разбора матча на карте **{map_name}** выделены 3 ключевых системных проблемы для тренировок:\n\n"
        f"1. **{p1['title']}:** {p1['text']}\n\n"
        f"2. **{p2['title']}:** {p2['text']}\n\n"
        f"3. **{p3['title']}:** {p3['text']}"
    )

def generate_match_summary_analysis(match_data: dict) -> str:
    """
    Генерация итогового сводного анализа после всех раундов:
    1. ОБЩИЙ СВОДНЫЙ АНАЛИЗ ДЛЯ ВСЕХ 10 ИГРОКОВ (Team 1 и Team 2)
    2. ГЛАВНЫЙ ВЫВОД ДЛЯ РАБОТЫ НАД ОШИБКАМИ (3 системные проблемы)
    С использованием высокоточного локального движка Smart Data-Driven Fallback.
    """
    players = match_data.get('players', {})
    t1_name = match_data.get('team1_name') or "Команда 1"
    t2_name = match_data.get('team2_name') or "Команда 2"

    t1_players = [p for p in players.values() if p.get('team') == 'team1']
    t2_players = [p for p in players.values() if p.get('team') == 'team2']

    # Сортируем игроков по рейтингу
    t1_players.sort(key=lambda x: (x.get('hltv_rating', 0.0), x.get('adr', 0.0)), reverse=True)
    t2_players.sort(key=lambda x: (x.get('hltv_rating', 0.0), x.get('adr', 0.0)), reverse=True)

    def describe_player_coaching(p: dict) -> str:
        name = p.get('name', 'Player')
        k = p.get('kills', 0)
        d = p.get('deaths', 0)
        adr = p.get('adr', 0.0)
        kast = p.get('kast', 0.0)
        fk = p.get('first_kills', 0)
        fd = p.get('first_deaths', 0)
        
        if adr >= 100:
            role = "Главный огневой удар (Primary Fragger)"
            strength = f"Великолепный урон ({adr} ADR) и постоянное давление на соперника."
            growth = "Не форсировать лишние соло-дуэли при наличии численного преимущества."
        elif fk >= 3 and fk >= fd:
            role = "Энтри-фрагер (Entry Duelist)"
            strength = f"Отличный опенинг-импакт ({fk} первых фрагов), открывающий точки для команды."
            growth = "Синхронизировать выход с флеш-поддержкой саппортов для уменьшения риска первого падения."
        elif kast >= 75:
            role = "Стабильный якорь / Саппорт (Support Anchor)"
            strength = f"Высокая командная полезность ({kast}% KAST) и надежный холд позиций."
            growth = "Увеличивать личный урон за счет своевременного использования осколочных гранат."
        elif k < d and fd > fk:
            role = "Опорник рубежа (Rotator)"
            strength = "Принятие на себя первого удара при штурме соперника."
            growth = f"Минимизировать открытые дуэли ({fd} первых смертей), играть глубже от укрытий и засад."
        else:
            role = "Универсал (Flex Rifle)"
            strength = f"Стабильная работа по дефолту карты ({k}/{d} K/D)."
            growth = "Повышать процент размена погибших тиммейтов и коммуникацию при перетяжках."

        return f"• **{name}** [{role}]: {strength} *Зона роста:* {growth}"

    t1_lines = "\n".join([describe_player_coaching(p) for p in t1_players])
    t2_lines = "\n".join([describe_player_coaching(p) for p in t2_players])

    takeaways = generate_tactical_takeaways_fallback(match_data)

    summary_text = (
        f"### 🧠 1. ОБЩИЙ СВОДНЫЙ АНАЛИЗ ДЛЯ ВСЕХ 10 ИГРОКОВ\n\n"
        f"#### 🛡️ {t1_name}\n"
        f"{t1_lines}\n\n"
        f"#### 💣 {t2_name}\n"
        f"{t2_lines}\n\n"
        f"---\n\n"
        f"{takeaways}"
    )
    return summary_text
