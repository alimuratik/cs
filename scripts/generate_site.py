import sys
import os
import json
import logging
import re
from datetime import datetime
from html import escape

sys.stdout.reconfigure(encoding='utf-8')

from jinja2 import Environment, FileSystemLoader
from scripts.config import *
from scripts.faceit_icons import render_faceit_svg, generate_faceit_svg_files



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

def clean_name(raw_val) -> str:
    """Безопасное форматирование имени игрока в строку."""
    if raw_val is None:
        return "Player"
    if isinstance(raw_val, float):
        if str(raw_val) == "nan":
            return "Player"
    s = str(raw_val).strip()
    return s if s and s != "nan" else "Player"

def parse_date_key(date_str: str) -> datetime:
    """Парсит строку даты (DDMMYYYY) в объект datetime для правильной хронологической сортировки."""
    if not date_str:
        return datetime.min
    clean_d = str(date_str).strip()
    if len(clean_d) >= 8 and clean_d[:8].isdigit():
        try:
            return datetime.strptime(clean_d[:8], "%d%m%Y")
        except Exception:
            pass
    return datetime.min

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

def extract_youtube_id(url_or_id: str) -> str:
    """
    Извлекает чистый 11-значный YouTube video ID из ссылки любого формата.
    """
    if not url_or_id or not isinstance(url_or_id, str):
        return ""
    s = url_or_id.strip()
    if not s:
        return ""

    if len(s) == 11 and re.match(r'^[0-9A-Za-z_-]{11}$', s):
        return s

    patterns = [
        r'(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/live\/)([0-9A-Za-z_-]{11})',
        r'[\?&]v=([0-9A-Za-z_-]{11})'
    ]
    for p in patterns:
        m = re.search(p, s)
        if m:
            return m.group(1)

    if "v=" in s:
        part = s.split("v=")[1].split("&")[0].split("?")[0]
        if len(part) == 11:
            return part

    return ""

def build_highlight_embed_url(url_or_id: str, start_sec: int = 0) -> tuple[str, str]:
    """
    Формирует (embed_url, watch_url) для YouTube с точным таймкодом:
    - embed_url: https://www.youtube-nocookie.com/embed/{id}?start={start_sec}&rel=0
    - watch_url: https://www.youtube.com/watch?v={id}&t={start_sec}s
    """
    vid = extract_youtube_id(url_or_id)
    if not vid:
        return "", ""
    if start_sec > 0:
        embed = f"https://www.youtube-nocookie.com/embed/{vid}?start={start_sec}&rel=0"
        watch = f"https://www.youtube.com/watch?v={vid}&t={start_sec}s"
    else:
        embed = f"https://www.youtube-nocookie.com/embed/{vid}?rel=0"
        watch = f"https://www.youtube.com/watch?v={vid}"
    return embed, watch

def extract_youtube_embed(url_or_id: str) -> str:
    """Для обратной совместимости: возвращает базовый Embed URL."""
    embed, _ = build_highlight_embed_url(url_or_id, 0)
    return embed

def sync_match_videos(match_ids: list[str]) -> dict:
    """
    Синхронизирует файл data/match_videos.json:
    - Читает существующие ссылки (добавленные пользователем на GitHub или локально).
    - Добавляет только новые match_id со значением "" (пустая строка).
    - НИКОГДА не удаляет и не затирает существующие ссылки пользователя!
    - Поддерживает как простые строки ("https://youtu.be/..."), так и словари ({"url": "...", "offset_sec": ...}).
    """
    videos_file = DATA_DIR / "match_videos.json"
    videos_data = {}
    if videos_file.exists():
        try:
            with open(videos_file, "r", encoding="utf-8") as f:
                videos_data = json.load(f)
        except Exception as e:
            logging.warning(f"Не удалось прочитать {videos_file}: {e}")
            videos_data = {}

    changed = False
    for mid in sorted(match_ids):
        if mid and mid not in videos_data:
            videos_data[mid] = ""
            changed = True

    if changed or not videos_file.exists():
        try:
            with open(videos_file, "w", encoding="utf-8") as f:
                json.dump(videos_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning(f"Не удалось сохранить {videos_file}: {e}")

    return videos_data

def compute_faceit_map_performance(faceit_data: dict) -> dict:
    """
    Вычисляет лучшую («Сигнатурная крепость FACEIT») и худшую («Зона риска FACEIT») карты
    на основе сегментов официальной статистики Faceit API.
    """
    if not faceit_data or not faceit_data.get("found"):
        return {"has_data": False, "favorite": None, "kryptonite": None, "all_maps": []}

    map_stats = faceit_data.get("map_stats", {})
    if not map_stats or not isinstance(map_stats, dict):
        return {"has_data": False, "favorite": None, "kryptonite": None, "all_maps": []}

    map_icons = {
        "mirage": "map_icon_de_mirage.svg",
        "dust2": "map_icon_de_dust2.svg",
        "inferno": "map_icon_de_inferno.svg",
        "nuke": "map_icon_de_nuke.svg",
        "ancient": "map_icon_de_ancient.svg",
        "anubis": "map_icon_de_anubis.svg",
        "vertigo": "map_icon_de_vertigo.svg",
        "overpass": "map_icon_de_overpass.svg",
        "train": "map_icon_de_train.svg",
        "cache": "map_icon_de_cache.svg"
    }

    parsed_maps = []
    for raw_m_name, st in map_stats.items():
        m_clean = raw_m_name.lower().replace("de_", "").strip()
        cnt = int(st.get("matches", 0) or 0)
        wr = float(st.get("win_rate", 0.0) or 0.0)
        kd = float(st.get("kd", 1.0) or 1.0)
        if cnt <= 0:
            continue
        parsed_maps.append({
            "key": m_clean,
            "name": m_clean.capitalize(),
            "matches": cnt,
            "win_rate": wr,
            "kd": kd,
            "icon": map_icons.get(m_clean, f"map_icon_de_{m_clean}.svg")
        })

    if not parsed_maps:
        return {"has_data": False, "favorite": None, "kryptonite": None, "all_maps": []}

    # Сортировка: приоритет картам с 2+ играми
    multi_maps = [m for m in parsed_maps if m["matches"] >= 2]
    pool = multi_maps if multi_maps else parsed_maps

    favorite = dict(max(pool, key=lambda x: (x["win_rate"], x["kd"], x["matches"])))
    favorite["advice"] = f"Ваша главная опора на FACEIT: {favorite['win_rate']}% побед при K/D {favorite['kd']}. Используйте уверенный контроль ключевых зон и агрессивные размены."

    other_maps = [m for m in parsed_maps if m["key"] != favorite["key"]]
    if other_maps:
        worst_pool = [m for m in other_maps if m["matches"] >= 2] or other_maps
        kryptonite = dict(min(worst_pool, key=lambda x: (x["win_rate"], x["kd"], -x["matches"])))
        kryptonite["advice"] = f"Зона повышенного риска на FACEIT: {kryptonite['win_rate']}% винрейт за {kryptonite['matches']} матчей. Тренируйте смоки и позиционную игру на приеме плентов."
    else:
        kryptonite = None

    parsed_maps.sort(key=lambda x: (-x["matches"], -x["win_rate"]))

    return {
        "has_data": True,
        "favorite": favorite,
        "kryptonite": kryptonite,
        "all_maps": parsed_maps
    }

# ─── Маппинг weapon slug → CDN filename для иконок из cs2-killfeed-generator ─
_WEAPON_ICON_CDN = "https://raw.githubusercontent.com/ChetdeJong/cs2-killfeed-generator/master/public/weapons/{slug}.svg"

_WEAPON_SLUG_MAP: dict[str, str] = {
    # Rifles
    "ak47":           "ak47",
    "m4a1":           "m4a1",
    "m4a1_silencer":  "m4a1_silencer",
    "aug":            "aug",
    "sg556":          "sg556",
    "famas":          "famas",
    "galilar":        "galilar",
    "ssg08":          "ssg08",
    "awp":            "awp",
    # Pistols
    "glock":          "glock",
    "usp_silencer":   "usp_silencer",
    "hkp2000":        "hkp2000",
    "p250":           "p250",
    "deagle":         "deagle",
    "fiveseven":      "fiveseven",
    "tec9":           "tec9",
    "elite":          "elite",
    "cz75a":          "cz75a",
    # SMGs
    "mac10":          "mac10",
    "mp9":            "mp9",
    "mp7":            "mp7",
    "mp5sd":          "mp5sd",
    "ump45":          "ump45",
    "p90":            "p90",
    "bizon":          "bizon",
    # Shotguns
    "mag7":           "mag7",
    "nova":           "nova",
    "xm1014":         "xm1014",
    # Machine guns
    "negev":          "negev",
    "m249":           "m249",
    # Grenades / special
    "hegrenade":      "hegrenade",
    "inferno":        "incgrenade",
    "planted_c4":     "c4",
    # Knives (one icon)
    "knife":          "knife",
    "knife_t":        "knife_t",
    "knife_kukri":    "knife_kukri",
    "knife_push":     "knife_push",
    # World / unknown
    "world":          None,
    "worldent":       None,
}

# Человекочитаемые названия оружий
_WEAPON_DISPLAY: dict[str, str] = {
    "ak47": "AK-47", "m4a1": "M4A4", "m4a1_silencer": "M4A1-S",
    "aug": "AUG", "sg556": "SG 553", "famas": "FAMAS", "galilar": "Galil AR",
    "ssg08": "SSG 08", "awp": "AWP",
    "glock": "Glock", "usp_silencer": "USP-S", "hkp2000": "P2000",
    "p250": "P250", "deagle": "Desert Eagle", "fiveseven": "Five-SeveN",
    "tec9": "Tec-9", "elite": "Dual Berettas", "cz75a": "CZ75-Auto",
    "mac10": "MAC-10", "mp9": "MP9", "mp7": "MP7", "mp5sd": "MP5-SD",
    "ump45": "UMP-45", "p90": "P90", "bizon": "PP-Bizon",
    "mag7": "MAG-7", "nova": "Nova", "xm1014": "XM1014",
    "negev": "Negev", "m249": "M249",
    "hegrenade": "HE Grenade", "inferno": "Molotov",
    "planted_c4": "Бомба",
    "knife": "Нож", "knife_t": "Нож", "knife_kukri": "Нож", "knife_push": "Нож",
    "world": "Мир",
}

def get_weapon_icon_url(weapon: str) -> str | None:
    """Возвращает URL SVG-иконки оружия или None если нет иконки."""
    slug = _WEAPON_SLUG_MAP.get(weapon.lower().strip())
    if slug is None:
        return None
    return _WEAPON_ICON_CDN.format(slug=slug)

def get_weapon_display(weapon: str) -> str:
    """Возвращает красивое название оружия."""
    return _WEAPON_DISPLAY.get(weapon.lower().strip(), weapon.upper())

# Иконки для каждой из 9 секций тактического разбора
_SECTION_ICONS = {
    "1": "⚔️", "2": "💰", "3": "🗺️", "4": "🔍",
    "5": "❌", "6": "🌟", "7": "💨", "8": "🏆", "9": "🧠",
}

def format_round_analysis(text: str) -> str:
    """Конвертирует markdown-разметку ai_analysis в читаемый HTML.

    Преобразует:
      **N. Заголовок:** текст   →  цветной div-заголовок + параграф
      **жирный текст**          →  <strong>
      *курсив*                  →  <em>
    """
    if not text:
        return ""

    # 1. Разбиваем на абзацы по двойному переводу строки
    paragraphs = re.split(r"\n{2,}", text.strip())
    html_parts = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # 2. Проверяем: это заголовок раздела вида **N. Название:**
        section_match = re.match(
            r"^\*{1,2}(\d+)\.\s+([^*:]+?):\*{0,2}\s*(.*)", para, re.DOTALL
        )
        if section_match:
            num = section_match.group(1)
            title = section_match.group(2).strip()
            body = section_match.group(3).strip()
            icon = _SECTION_ICONS.get(num, "•")

            # Заголовок раздела
            html_parts.append(
                f'<div class="flex items-start gap-2 mt-3 mb-1">'
                f'<span class="text-sm shrink-0 mt-px">{icon}</span>'
                f'<span class="text-[11px] font-black uppercase tracking-wider text-emerald-300 leading-tight">{num}. {title}</span>'
                f'</div>'
            )
            if body:
                body_html = _inline_md(body)
                html_parts.append(
                    f'<p class="text-slate-200 text-xs md:text-sm leading-relaxed pl-6 mb-1">{body_html}</p>'
                )
        else:
            # 3. Обычный параграф — конвертируем inline md
            html_parts.append(
                f'<p class="text-slate-300 text-xs md:text-sm leading-relaxed mb-1">{_inline_md(para)}</p>'
            )

    return "\n".join(html_parts)


def _inline_md(text: str) -> str:
    """Конвертирует inline markdown (**bold**, *italic*) в HTML теги."""
    # Сначала заменяем строки вида \n внутри параграфа на <br>
    text = text.replace("\n", "<br>")
    # **bold**
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong class='text-white'>\1</strong>", text)
    # *italic*
    text = re.sub(r"\*(.+?)\*", r"<em class='text-slate-300'>\1</em>", text)
    return text


def format_coach_summary(text: str) -> str:
    """
    Преобразует итоговый тренерский разбор матча в красивый структурированный HTML.
    Убирает все ###, ####, сырой markdown и строит карточки игроков и выводы.
    """
    if not text:
        return ""

    text = text.strip()
    sections = re.split(r'\n+(?:---+\n+)?(?=###\s+)', text)

    # Проверяем, подходит ли под двухсекционную структуру (10 игроков + 3 вывода)
    if len(sections) >= 2 and re.search(r'ИГРОК|СВОДНЫЙ|КОМАНД', sections[0], re.I) and re.search(r'ВЫВОД|ОШИБК|ТРЕНИРОВ', sections[1], re.I):
        sec0 = sections[0].strip()
        sec1 = sections[1].strip()

        # --- СЕКЦИЯ 1: Аудит игроков ---
        team_blocks = re.split(r'\n+(?=####\s+)', sec0)
        team_cards_html = []

        for idx, tblock in enumerate(team_blocks[1:], start=1):
            t_lines = tblock.strip().split('\n')
            raw_title = t_lines[0].replace('####', '').strip()
            
            # Определяем сторону (CT синий / T золотой)
            is_team1 = (idx == 1) or ("команда 1" in raw_title.lower()) or ("🛡️" in raw_title)
            border_color = "border-blue-500/30" if is_team1 else "border-amber-500/30"
            header_text_color = "text-blue-400" if is_team1 else "text-amber-400"
            badge_bg = "bg-blue-500/20 text-blue-300 border-blue-500/30" if is_team1 else "bg-amber-500/20 text-amber-300 border-amber-500/30"
            item_hover = "hover:border-blue-500/40" if is_team1 else "hover:border-amber-500/40"

            player_items_html = []
            for l in t_lines[1:]:
                l = l.strip()
                if not l:
                    continue
                # Парсим • **Player** [Role]: Strength *Зона роста:* Growth
                m = re.search(r'[•\*\-]?\s*\*\*([^*]+)\*\*\s*(?:\[([^\]]+)\])?:\s*(.*?)(?:\*?Зона роста:\*?)\s*(.*)', l, re.I)
                if m:
                    p_name = m.group(1).strip()
                    p_role = m.group(2).strip() if m.group(2) else ""
                    p_strength = m.group(3).strip()
                    p_growth = m.group(4).strip()

                    role_badge = f'<span class="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">{escape(p_role)}</span>' if p_role else ""

                    player_items_html.append(f"""
                        <div class="bg-slate-950/60 border border-slate-800/80 {item_hover} rounded-xl p-3.5 transition flex flex-col gap-2">
                            <div class="flex flex-wrap items-center justify-between gap-2">
                                <span class="font-bold text-white text-sm">{escape(p_name)}</span>
                                {role_badge}
                            </div>
                            <div class="text-xs text-slate-300 leading-relaxed flex items-start gap-2">
                                <span class="text-emerald-400 text-xs shrink-0 mt-0.5">💪</span>
                                <span>{_inline_md(p_strength)}</span>
                            </div>
                            <div class="text-xs text-amber-200/90 leading-relaxed flex items-start gap-2 pt-1.5 border-t border-slate-800/60">
                                <span class="text-amber-400 text-xs shrink-0 mt-0.5">🎯</span>
                                <span><strong class="text-amber-300 font-semibold">Зона роста:</strong> {_inline_md(p_growth)}</span>
                            </div>
                        </div>
                    """)
                else:
                    # Обычная строчка
                    player_items_html.append(f"""
                        <div class="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3 text-xs text-slate-300">
                            {_inline_md(l)}
                        </div>
                    """)

            team_cards_html.append(f"""
                <div class="bg-slate-900/80 border {border_color} rounded-2xl p-4 md:p-5 shadow-lg flex flex-col gap-3">
                    <div class="flex items-center justify-between pb-3 border-b border-slate-800">
                        <span class="font-black text-sm md:text-base {header_text_color} uppercase tracking-wider flex items-center gap-2">
                            {raw_title}
                        </span>
                        <span class="text-[11px] font-bold px-2.5 py-0.5 rounded {badge_bg} border">
                            {len(player_items_html)} игроков
                        </span>
                    </div>
                    <div class="space-y-2.5">
                        {''.join(player_items_html)}
                    </div>
                </div>
            """)

        audit_html = f"""
            <div class="mb-6">
                <div class="flex items-center gap-2 mb-3">
                    <span class="text-xl">👥</span>
                    <h3 class="text-sm md:text-base font-black text-white uppercase tracking-wider">
                        Индивидуальный аудит игроков матча
                    </h3>
                </div>
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {''.join(team_cards_html)}
                </div>
            </div>
        """

        # --- СЕКЦИЯ 2: Ключевые выводы и работа над ошибками ---
        lines1 = sec1.split('\n')
        intro_parts = []
        takeaways = []

        for l in lines1[1:]:
            l = l.strip()
            if not l:
                continue
            m = re.match(r'^(\d+)\.\s+\*\*([^*]+)\*\*:?\s*(.*)', l)
            if m:
                takeaways.append({
                    "num": m.group(1),
                    "title": m.group(2).strip(),
                    "body": m.group(3).strip()
                })
            else:
                intro_parts.append(l)

        intro_text = " ".join(intro_parts)
        intro_html = f'<p class="text-xs md:text-sm text-slate-300 mb-4 leading-relaxed">{_inline_md(intro_text)}</p>' if intro_text else ""

        takeaways_html = []
        for tw in takeaways:
            takeaways_html.append(f"""
                <div class="bg-slate-950/70 border border-emerald-500/25 hover:border-emerald-500/50 rounded-xl p-4 transition flex flex-col gap-2">
                    <div class="flex items-center gap-2.5">
                        <span class="w-6 h-6 rounded-lg bg-amber-500/20 text-amber-300 border border-amber-500/40 text-xs font-black flex items-center justify-center shrink-0">
                            {tw['num']}
                        </span>
                        <span class="font-bold text-white text-xs md:text-sm leading-snug">{escape(tw['title'])}</span>
                    </div>
                    <p class="text-xs text-slate-300 leading-relaxed flex-1 mt-0.5">
                        {_inline_md(tw['body'])}
                    </p>
                </div>
            """)

        takeaways_section_html = f"""
            <div class="bg-gradient-to-br from-slate-900/90 via-emerald-950/20 to-slate-900/90 border border-emerald-500/30 rounded-2xl p-4 md:p-6 shadow-xl">
                <div class="flex items-center gap-2 mb-2">
                    <span class="text-xl">🏆</span>
                    <h3 class="text-sm md:text-base font-black text-white uppercase tracking-wider">
                        Ключевые системные выводы для тренировок
                    </h3>
                </div>
                {intro_html}
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {''.join(takeaways_html)}
                </div>
            </div>
        """

        return f'<div class="coach-summary-wrapper space-y-6">{audit_html}{takeaways_section_html}</div>'

    # Fallback на случай нестандартного формата: чистим все ### и строим параграфы
    clean_lines = []
    for l in text.split('\n'):
        l = l.strip()
        if not l or l == '---':
            continue
        if l.startswith('###'):
            header_clean = l.replace('#', '').strip()
            clean_lines.append(f'<div class="text-sm font-black text-emerald-300 uppercase tracking-wider mt-4 mb-2">{header_clean}</div>')
        elif l.startswith('####'):
            header_clean = l.replace('#', '').strip()
            clean_lines.append(f'<div class="text-xs font-bold text-slate-200 uppercase tracking-wider mt-3 mb-1.5">{header_clean}</div>')
        else:
            clean_lines.append(f'<p class="text-slate-300 text-xs md:text-sm leading-relaxed mb-2">{_inline_md(l)}</p>')

    return '\n'.join(clean_lines)


def get_player_rank_tier(mmr: int, is_calibrating: bool = False, is_inactive: bool = False) -> dict:
    """10-уровневая система рангов в стиле Faceit с аутентичными SVG-иконками:
    Lv10: >= 1180 | Lv9: 1135-1179 | Lv8: 1090-1134 | Lv7: 1045-1089 | Lv6: 1000-1044
    Lv5:  955-999 | Lv4: 910-954   | Lv3: 865-909   | Lv2: 820-864   | Lv1: < 820
    Для калибрующихся: Faceit Unranked значок (?), серый цвет MMR.
    Для неактивных: сохраненный уровень, но серый цвет MMR.
    """
    if is_calibrating:
        svg_icon = render_faceit_svg(0, size=20)
        svg_icon_sm = render_faceit_svg(0, size=16)
        svg_icon_lg = render_faceit_svg(0, size=32)
        return {
            "tier_id": "unranked",
            "tier_name": "Калибровка",
            "tier_badge": "Калибровка",
            "tier_short": "Калибр.",
            "icon": svg_icon,
            "badge_svg": svg_icon,
            "badge_svg_small": svg_icon_sm,
            "badge_svg_large": svg_icon_lg,
            "level": 0,
            "next_level": 1,
            "next_level_name": "Level 1",
            "next_level_mmr": 820,
            "min_level_mmr": 0,
            "mmr_to_next": 0,
            "progress_percent": 0.0,
            "is_max_level": False,
            "is_calibrating": True,
            "is_inactive": is_inactive,
            "color": "slate",
            "avatar_classes": "bg-slate-900/80 border-slate-700/60 text-slate-400 group-hover:border-slate-500",
            "row_classes": "hover:bg-slate-800/20 border-l-slate-600 opacity-80",
            "card_border": "border-slate-700/40",
            "badge_classes": "bg-slate-900/80 text-slate-400 border border-slate-700/50",
            "mmr_classes": "text-slate-400 font-mono"
        }

    if mmr >= 1180:
        lvl = 10
        color = "red"
        avatar_classes = "bg-red-950/80 border-red-500/60 text-red-200 group-hover:border-red-400 group-hover:shadow-red-500/40 group-hover:shadow-md"
        row_classes = "hover:bg-red-950/20 border-l-red-500"
        card_border = "border-red-500/50"
        badge_classes = "bg-red-950/80 text-red-200 border border-red-500/50"
        mmr_classes = "text-slate-400 font-mono" if is_inactive else "text-red-300"
    elif mmr >= 1135:
        lvl = 9
        color = "orange"
        avatar_classes = "bg-orange-950/80 border-orange-500/50 text-orange-200 group-hover:border-orange-400 group-hover:shadow-orange-500/30 group-hover:shadow-md"
        row_classes = "hover:bg-orange-950/20 border-l-orange-500"
        card_border = "border-orange-500/40"
        badge_classes = "bg-orange-950/80 text-orange-200 border border-orange-500/40"
        mmr_classes = "text-slate-400 font-mono" if is_inactive else "text-orange-300"
    elif mmr >= 1090:
        lvl = 8
        color = "orange"
        avatar_classes = "bg-orange-950/80 border-orange-500/50 text-orange-200 group-hover:border-orange-400 group-hover:shadow-orange-500/30 group-hover:shadow-md"
        row_classes = "hover:bg-orange-950/20 border-l-orange-500"
        card_border = "border-orange-500/40"
        badge_classes = "bg-orange-950/80 text-orange-200 border border-orange-500/40"
        mmr_classes = "text-slate-400 font-mono" if is_inactive else "text-orange-300"
    elif mmr >= 1045:
        lvl = 7
        color = "amber"
        avatar_classes = "bg-amber-950/80 border-amber-400/50 text-amber-200 group-hover:border-amber-300 group-hover:shadow-amber-500/30 group-hover:shadow-md"
        row_classes = "hover:bg-amber-950/20 border-l-amber-400"
        card_border = "border-amber-400/40"
        badge_classes = "bg-amber-950/80 text-amber-200 border border-amber-400/40"
        mmr_classes = "text-slate-400 font-mono" if is_inactive else "text-amber-300"
    elif mmr >= 1000:
        lvl = 6
        color = "amber"
        avatar_classes = "bg-amber-950/80 border-amber-400/50 text-amber-200 group-hover:border-amber-300 group-hover:shadow-amber-500/30 group-hover:shadow-md"
        row_classes = "hover:bg-amber-950/20 border-l-amber-400"
        card_border = "border-amber-400/40"
        badge_classes = "bg-amber-950/80 text-amber-200 border border-amber-400/40"
        mmr_classes = "text-slate-400 font-mono" if is_inactive else "text-amber-300"
    elif mmr >= 955:
        lvl = 5
        color = "amber"
        avatar_classes = "bg-amber-950/80 border-amber-400/50 text-amber-200 group-hover:border-amber-300 group-hover:shadow-amber-500/30 group-hover:shadow-md"
        row_classes = "hover:bg-amber-950/20 border-l-amber-400"
        card_border = "border-amber-400/40"
        badge_classes = "bg-amber-950/80 text-amber-200 border border-amber-400/40"
        mmr_classes = "text-slate-400 font-mono" if is_inactive else "text-amber-300"
    elif mmr >= 910:
        lvl = 4
        color = "amber"
        avatar_classes = "bg-amber-950/80 border-amber-400/50 text-amber-200 group-hover:border-amber-300 group-hover:shadow-amber-500/30 group-hover:shadow-md"
        row_classes = "hover:bg-amber-950/20 border-l-amber-400"
        card_border = "border-amber-400/40"
        badge_classes = "bg-amber-950/80 text-amber-200 border border-amber-400/40"
        mmr_classes = "text-slate-400 font-mono" if is_inactive else "text-amber-300"
    elif mmr >= 865:
        lvl = 3
        color = "emerald"
        avatar_classes = "bg-emerald-950/80 border-emerald-500/50 text-emerald-200 group-hover:border-emerald-400 group-hover:shadow-emerald-500/30 group-hover:shadow-md"
        row_classes = "hover:bg-emerald-950/20 border-l-emerald-500"
        card_border = "border-emerald-500/40"
        badge_classes = "bg-emerald-950/80 text-emerald-200 border border-emerald-500/40"
        mmr_classes = "text-slate-400 font-mono" if is_inactive else "text-emerald-300"
    elif mmr >= 820:
        lvl = 2
        color = "emerald"
        avatar_classes = "bg-emerald-950/80 border-emerald-500/50 text-emerald-200 group-hover:border-emerald-400 group-hover:shadow-emerald-500/30 group-hover:shadow-md"
        row_classes = "hover:bg-emerald-950/20 border-l-emerald-500"
        card_border = "border-emerald-500/40"
        badge_classes = "bg-emerald-950/80 text-emerald-200 border border-emerald-500/40"
        mmr_classes = "text-slate-400 font-mono" if is_inactive else "text-emerald-300"
    else:
        lvl = 1
        color = "slate"
        avatar_classes = "bg-slate-800/80 border-slate-500/50 text-slate-300 group-hover:border-slate-400 group-hover:shadow-slate-500/20 group-hover:shadow-md"
        row_classes = "hover:bg-slate-800/20 border-l-slate-500"
        card_border = "border-slate-500/40"
        badge_classes = "bg-slate-800/80 text-slate-300 border border-slate-500/40"
        mmr_classes = "text-slate-400 font-mono" if is_inactive else "text-slate-300"

    svg_icon = render_faceit_svg(lvl, size=20)
    svg_icon_sm = render_faceit_svg(lvl, size=16)
    svg_icon_lg = render_faceit_svg(lvl, size=32)

    # Расчет прогресса до следующего соревновательного уровня
    TIER_BOUNDS = [
        (1, 0, 820),
        (2, 820, 865),
        (3, 865, 910),
        (4, 910, 955),
        (5, 955, 1000),
        (6, 1000, 1045),
        (7, 1045, 1090),
        (8, 1090, 1135),
        (9, 1135, 1180),
        (10, 1180, 2000),
    ]
    cur_bound = next((b for b in TIER_BOUNDS if b[0] == lvl), (1, 0, 820))
    min_mmr, next_mmr = cur_bound[1], cur_bound[2]
    next_lvl = min(10, lvl + 1)
    is_max = (lvl == 10)
    mmr_to_next = max(0, next_mmr - mmr) if not is_max else 0
    span = max(1, next_mmr - min_mmr)
    prog_pct = 100.0 if is_max else round(min(100.0, max(0.0, (mmr - min_mmr) / span * 100.0)), 1)

    return {
        "tier_id": f"level{lvl}",
        "tier_name": f"Level {lvl}",
        "tier_badge": f"Level {lvl}",
        "tier_short": f"Lv{lvl}",
        "icon": svg_icon,
        "badge_svg": svg_icon,
        "badge_svg_small": svg_icon_sm,
        "badge_svg_large": svg_icon_lg,
        "level": lvl,
        "next_level": next_lvl,
        "next_level_name": f"Level {next_lvl}",
        "next_level_mmr": next_mmr,
        "min_level_mmr": min_mmr,
        "mmr_to_next": mmr_to_next,
        "progress_percent": prog_pct,
        "is_max_level": is_max,
        "is_calibrating": False,
        "is_inactive": is_inactive,
        "color": color,
        "avatar_classes": avatar_classes,
        "row_classes": row_classes,
        "card_border": card_border,
        "badge_classes": badge_classes,
        "mmr_classes": mmr_classes
    }

def load_data():
    """Загрузка всех обработанных данных из директории data/."""
    matches = []
    players = []
    sessions_dict = {}

    matches_dir = DATA_DIR / "matches"
    players_dir = DATA_DIR / "players"

    # Загрузка матчей
    if matches_dir.exists():
        for filename in os.listdir(matches_dir):
            if filename.endswith(".json"):
                path = matches_dir / filename
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        m_data = json.load(f)
                        m_data["date_display"] = format_date_display(m_data.get("date", ""))
                        matches.append(m_data)
                except Exception as e:
                    logging.error(f"Ошибка чтения матча {filename}: {e}")

    # Загрузка игроков
    if players_dir.exists():
        for filename in os.listdir(players_dir):
            if filename.endswith(".json"):
                path = players_dir / filename
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        p_data = json.load(f)
                        sid = clean_steamid(p_data.get("steam_id", filename.replace(".json", "")))
                        faceit_file = FACEIT_DIR / f"{sid}.json"
                        if not faceit_file.exists():
                            candidates = []
                            if sid in PLAYER_ALIASES:
                                candidates.append(PLAYER_ALIASES[sid][0])
                            p_name_lower = (p_data.get("name") or "").lower().strip()
                            if p_name_lower in CANONICAL_PLAYERS:
                                candidates.append(CANONICAL_PLAYERS[p_name_lower])
                            if sid == "76561198254267968":
                                candidates.append("76561198254267961")
                            elif sid == "76561198254267961":
                                candidates.append("76561198254267968")
                            for c in candidates:
                                cand_file = FACEIT_DIR / f"{c}.json"
                                if cand_file.exists():
                                    faceit_file = cand_file
                                    break
                        if faceit_file.exists():
                            try:
                                with open(faceit_file, "r", encoding="utf-8") as ff:
                                    f_data = json.load(ff)
                                    if f_data.get("found"):
                                        p_data["faceit"] = f_data
                            except Exception as fe:
                                logging.warning(f"Ошибка чтения Faceit данных для {sid}: {fe}")
                        players.append(p_data)
                except Exception as e:
                    logging.error(f"Ошибка чтения игрока {filename}: {e}")

    # Группировка матчей по сессиям (датам)
    for m in matches:
        d = m.get("date", "unknown")
        if d not in sessions_dict:
            sessions_dict[d] = {
                "date": d,
                "date_display": format_date_display(d),
                "match_count": 0,
                "maps": [],
                "matches": [],
                "mvp": None
            }
        sessions_dict[d]["match_count"] += 1
        map_name = m.get("map_display", m.get("map", ""))
        if map_name not in sessions_dict[d]["maps"]:
            sessions_dict[d]["maps"].append(map_name)
        sessions_dict[d]["matches"].append(m)

    sessions = list(sessions_dict.values())
    # Сортируем сессии строго по реальной дате (самые свежие первыми)
    sessions.sort(key=lambda s: parse_date_key(s.get("date", "")), reverse=True)
    return matches, players, sessions

def format_match_data(m: dict) -> dict:
    """Форматирование данных матча под ожидания шаблона match.html."""
    players_dict = m.get("players", {})
    mvp_sid = m.get("mvp_steam_id")
    
    team1_players = []
    team2_players = []
    
    all_players = list(players_dict.values())
    
    # Дедупликация и сопоставление по псевдонимам и каноническим Steam ID
    unique_map = {}
    for p in all_players:
        raw_name = clean_name(p.get("name"))
        name_lower = raw_name.lower()
        sid = clean_steamid(p.get("steam_id"))

        if sid in PLAYER_ALIASES:
            sid, raw_name = PLAYER_ALIASES[sid]
        elif name_lower in PLAYER_ALIASES:
            sid, raw_name = PLAYER_ALIASES[name_lower]

        if name_lower in CANONICAL_PLAYERS:
            sid = CANONICAL_PLAYERS[name_lower]

        p["steam_id"] = sid
        p["name"] = raw_name

        if sid not in unique_map:
            unique_map[sid] = p
        else:
            # Объединяем показатели если один игрок попал дважды
            ex = unique_map[sid]
            ex["kills"] = max(ex.get("kills", 0), p.get("kills", 0))
            ex["deaths"] = max(ex.get("deaths", 0), p.get("deaths", 0))
            ex["assists"] = max(ex.get("assists", 0), p.get("assists", 0))
            ex["adr"] = max(ex.get("adr", 0.0), p.get("adr", 0.0))
            ex["kast"] = max(ex.get("kast", 0.0), p.get("kast", 0.0))
            ex["hs_percent"] = max(ex.get("hs_percent", 0.0), p.get("hs_percent", 0.0))

    unique_list = list(unique_map.values())
    
    t1_list = [p for p in unique_list if str(p.get("team", "")).lower() in ("team1", "ct", "1")]
    t2_list = [p for p in unique_list if str(p.get("team", "")).lower() in ("team2", "t", "2", "3")]

    if len(t1_list) == 5 and len(t2_list) == 5:
        raw_team1 = t1_list
        raw_team2 = t2_list
    elif len(t1_list) >= 5 and len(t2_list) >= 5:
        raw_team1 = t1_list[:5]
        raw_team2 = t2_list[:5]
    else:
        raw_team1 = t1_list if len(t1_list) == 5 else unique_list[:5]
        raw_team2 = [p for p in unique_list if p not in raw_team1][:5]

    def build_player_row(p):
        k = p.get("kills", 0)
        d = p.get("deaths", 0)
        a = p.get("assists", 0)
        adr_val = p.get("adr", 0.0)
        kast_val = p.get("kast", 0.0)
        hs_val = p.get("hs_percent", 0.0)
        fk = p.get("first_kills", 0)
        fd = p.get("first_deaths", 0)
        clutches = p.get("clutch_wins", 0)
        sid = clean_steamid(p.get("steam_id"))
        
        # Получение или расчет честных рейтингов HLTV 2.0 и 1-10
        hltv_val = p.get("hltv_rating")
        rating_10 = p.get("score_10")
        if hltv_val is None or rating_10 is None:
            rounds_cnt = max(1, len(m.get("rounds", [])))
            hltv_val, rating_10 = compute_hltv_rating(k, d, a, adr_val, kast_val, fk, fd, rounds_cnt)
            
        mmr_delta = p.get("mmr_delta", 0)
        mmr_breakdown = p.get("mmr_breakdown", "")
        mmr_after = p.get("mmr_after", STARTING_MMR)
        is_calibrating = p.get("is_calibrating", False)
        
        return {
            "steam_id": sid,
            "name": clean_name(p.get("name")),
            "kills": k,
            "deaths": d,
            "assists": a,
            "kd_diff": k - d,
            "adr": round(adr_val, 1),
            "kast": round(kast_val, 1),
            "hs": round(hs_val, 1),
            "fk": fk,
            "fd": fd,
            "clutches": clutches,
            "hltv": round(hltv_val, 2),
            "rating": round(rating_10, 1),
            "mmr_delta": mmr_delta,
            "mmr_delta_text": f"{mmr_delta:+d}" if mmr_delta != 0 else "0",
            "mmr_breakdown": mmr_breakdown,
            "mmr_after": mmr_after,
            "is_calibrating": is_calibrating,
            "is_mvp": sid == mvp_sid
        }

    t1_rows = [build_player_row(p) for p in raw_team1]
    t2_rows = [build_player_row(p) for p in raw_team2]

    def calc_totals(rows):
        return {
            "players": rows,
            "total_kills": sum(r["kills"] for r in rows),
            "total_deaths": sum(r["deaths"] for r in rows),
            "total_assists": sum(r["assists"] for r in rows),
            "total_fk": sum(r["fk"] for r in rows),
            "total_fd": sum(r["fd"] for r in rows)
        }

    # Ключевые лидеры
    def get_leader(key, fmt=lambda x: x):
        if not all_players:
            return {"name": "—", "value": "0"}
        best = max(all_players, key=lambda p: p.get(key, 0))
        return {"name": best.get("name", "Player"), "value": fmt(best.get(key, 0))}

    stats_leaders = {
        "fk_leader": get_leader("first_kills"),
        "adr_leader": get_leader("adr", lambda x: round(x, 1)),
        "hs_leader": get_leader("hs_percent", lambda x: round(x, 1)),
        "util_leader": get_leader("utility_damage"),
        "flash_leader": get_leader("flash_assists"),
        "clutch_leader": get_leader("clutch_wins")
    }

    t1_cap = m.get("team1_captain") or (max(t1_rows, key=lambda r: (r['hltv'], r['kills']))['name'] if t1_rows else "Команда 1")
    t2_cap = m.get("team2_captain") or (max(t2_rows, key=lambda r: (r['hltv'], r['kills']))['name'] if t2_rows else "Команда 2")
    t1_name = m.get("team1_name") or f"Команда 1 ({t1_cap})"
    t2_name = m.get("team2_name") or f"Команда 2 ({t2_cap})"

    # Раунды
    formatted_rounds = []
    kills_by_round = {}
    for k in m.get("kills", []):
        r_num = k.get("round_num", 1)
        kills_by_round.setdefault(r_num, []).append(k)

    raw_rounds = m.get("rounds", [])
    for idx, r in enumerate(raw_rounds, start=1):
        w = str(r.get("winner", "CT")).upper()
        reason = r.get("reason", "")
        
        icon = "💀"
        win_type = "Уничтожение"
        if "defus" in reason or "defuse" in reason:
            icon = "✂️"
            win_type = "Обезвреживание"
        elif "bomb" in reason or "exploded" in reason:
            icon = "💣"
            win_type = "Взрыв C4"
        elif "time" in reason:
            icon = "⏱️"
            win_type = "Время вышло"

        r_kills = kills_by_round.get(idx, [])
        killfeed = []
        for k in r_kills:
            att = k.get("attacker_name") or "World"
            vic = k.get("victim_name") or "Player"
            wpn_raw = str(k.get("weapon") or "weapon").strip().lower()
            hs = k.get("headshot", False)
            att_side = k.get("attacker_side", "")
            vic_side = k.get("victim_side", "")
            killfeed.append({
                "attacker": att,
                "victim": vic,
                "weapon_raw": wpn_raw,
                "weapon_display": get_weapon_display(wpn_raw),
                "weapon_icon": get_weapon_icon_url(wpn_raw),
                "headshot": hs,
                "attacker_side": att_side,
                "victim_side": vic_side,
            })

        # Первое убийство в раунде (First Blood)
        first_kill_str = ""
        if r_kills:
            first_k = r_kills[0]
            fk_att = first_k.get("attacker_name") or "World"
            fk_vic = first_k.get("victim_name") or "Player"
            fk_wpn_raw = str(first_k.get("weapon") or "weapon").strip().lower()
            fk_hs = " 🎯" if first_k.get("headshot") else ""
            fk_disp = get_weapon_display(fk_wpn_raw)
            first_kill_str = f"{fk_att} [{fk_disp}{fk_hs}] ➔ {fk_vic}"

        # Очистка шаблонного префикса из ai_analysis если он был сохранен ранее
        raw_ai = r.get("ai_analysis", "")
        clean_ai = re.sub(r"^🎙️\s*\*\*Комментарий[^*]+\*\*:\s*", "", raw_ai).strip()
        clean_ai_html = format_round_analysis(clean_ai)

        t1_side = r.get("t1_side") or ("ct" if idx <= 12 else "t")
        ct_t_name = t1_name if t1_side == "ct" else t2_name
        t_t_name = t2_name if t1_side == "ct" else t1_name

        ct_eco = r.get("ct_economy") or (r.get("team_a_economy") if t1_side == "ct" else r.get("team_b_economy")) or "Full Buy"
        t_eco = r.get("t_economy") or (r.get("team_b_economy") if t1_side == "ct" else r.get("team_a_economy")) or "Full Buy"
        ct_badge = r.get("ct_economy_badge") or (ct_eco.split("(")[0].strip() if "(" in str(ct_eco) else str(ct_eco))
        t_badge = r.get("t_economy_badge") or (t_eco.split("(")[0].strip() if "(" in str(t_eco) else str(t_eco))
        ct_val_disp = r.get("ct_economy_val_display") or ""
        t_val_disp = r.get("t_economy_val_display") or ""

        t1_val = r.get("ct_economy_val", 4000) if t1_side == "ct" else r.get("t_economy_val", 4000)
        t2_val = r.get("t_economy_val", 4000) if t1_side == "ct" else r.get("ct_economy_val", 4000)
        try:
            t1_val = int(t1_val)
        except Exception:
            t1_val = 4000
        try:
            t2_val = int(t2_val)
        except Exception:
            t2_val = 4000

        formatted_rounds.append({
            "number": idx,
            "winner": w,
            "winning_team": r.get("winning_team", "team1" if w == "CT" else "team2"),
            "win_type": win_type,
            "win_icon": icon,
            "ct_team_name": ct_t_name,
            "t_team_name": t_t_name,
            "team1_eco_val": t1_val,
            "team2_eco_val": t2_val,
            "ct_economy_badge": ct_badge,
            "ct_economy_val_display": ct_val_disp,
            "ct_economy": str(ct_eco),
            "t_economy_badge": t_badge,
            "t_economy_val_display": t_val_disp,
            "t_economy": str(t_eco),
            "eco_team1": str(r.get("team_a_economy", "Full Buy")),
            "eco_team2": str(r.get("team_b_economy", "Full Buy")),
            "killfeed": killfeed,
            "first_kill": first_kill_str,
            "utility_dmg_summary": "—",
            "ai_analysis": clean_ai_html
        })

    # Экономика по раундам
    economy_chart = {
        "labels": [f"R{fr['number']}" for fr in formatted_rounds],
        "rounds_meta": [{
            "number": fr["number"],
            "winner": fr["winner"],
            "winning_team": fr["winning_team"],
            "winning_side": fr["winner"]
        } for fr in formatted_rounds],
        "team1": [fr.get("team1_eco_val", 4000) for fr in formatted_rounds],
        "team2": [fr.get("team2_eco_val", 4000) for fr in formatted_rounds]
    }

    # Расчет дуэлей между игроками (Head-to-Head Duel Matrix)
    duel_counts = {}
    for k in m.get("kills", []):
        att = clean_name(k.get("attacker_name"))
        vic = clean_name(k.get("victim_name"))
        if att and vic and att != "World" and vic != "Player" and att != vic:
            pair = (att, vic)
            duel_counts[pair] = duel_counts.get(pair, 0) + 1

    duels_matrix = []
    for p1 in t1_rows:
        row = {"player": p1["name"], "vs": {}}
        for p2 in t2_rows:
            k_p1 = duel_counts.get((p1["name"], p2["name"]), 0)
            k_p2 = duel_counts.get((p2["name"], p1["name"]), 0)
            row["vs"][p2["name"]] = {"kills": k_p1, "deaths": k_p2}
        duels_matrix.append(row)


    # Настоящий счет первой половины
    h1_s1 = sum(1 for r in formatted_rounds if r.get("number", 0) <= 12 and r.get("winning_team") == "team1")
    h1_s2 = sum(1 for r in formatted_rounds if r.get("number", 0) <= 12 and r.get("winning_team") == "team2")
    half_scores_str = f"{h1_s1}:{h1_s2}"

    # Видеозапись матча и хайлайты (YouTube Embed & Deep-links)
    mid = m.get("match_id", "")
    video_url = ""
    video_offset_sec = 0
    try:
        vf = DATA_DIR / "match_videos.json"
        if vf.exists():
            with open(vf, "r", encoding="utf-8") as v_f:
                v_data = json.load(v_f)
                v_val = v_data.get(mid, "")
                if isinstance(v_val, dict):
                    video_url = (v_val.get("url", "") or "").strip()
                    video_offset_sec = int(v_val.get("offset_sec", 0) or 0)
                else:
                    video_url = (str(v_val) if v_val else "").strip()
                    video_offset_sec = 0
    except Exception:
        video_url = ""
        video_offset_sec = 0

    video_embed_url = extract_youtube_embed(video_url) if video_url else ""

    # Загрузка хайлайта матча из data/highlights.json
    match_highlight = None
    try:
        hl_file = DATA_DIR / "highlights.json"
        if hl_file.exists():
            with open(hl_file, "r", encoding="utf-8") as hf:
                hl_all = json.load(hf)
                hl_raw = hl_all.get("match_highlights", {}).get(mid)
                if hl_raw:
                    match_highlight = dict(hl_raw)
                    curr_offset = video_offset_sec or match_highlight.get("video_offset_sec", 0)
                    g_sec = match_highlight.get("game_sec", 0)
                    lead_in = 6
                    start_sec = max(0, curr_offset + g_sec - lead_in)
                    tc_disp = f"{start_sec // 60}:{start_sec % 60:02d}"
                    match_highlight["embed_start_sec"] = start_sec
                    match_highlight["timecode_display"] = tc_disp
                    match_highlight["video_url"] = video_url
                    match_highlight["video_offset_sec"] = curr_offset

                    hl_embed, hl_watch = build_highlight_embed_url(video_url, start_sec)
                    match_highlight["embed_url"] = hl_embed
                    match_highlight["watch_url"] = hl_watch

                    def get_p_data(s_id, p_nm):
                        for pk, pv in m.get("players", {}).items():
                            if pk == s_id or pv.get("steam_id") == s_id or (p_nm and pv.get("name", "").lower() == str(p_nm).lower()):
                                return pv
                        return {}

                    # Ранг игрока
                    p_sid = match_highlight.get("player_steamid", "")
                    p_stat = get_p_data(p_sid, match_highlight.get("player_name"))
                    p_mmr = p_stat.get("mmr_after", p_stat.get("mmr_before", STARTING_MMR))
                    match_highlight["rank_tier"] = get_player_rank_tier(p_mmr)
                    match_highlight["team"] = p_stat.get("team", "")

                    # Форматирование списка топ-хайлайтов карты
                    raw_top = match_highlight.get("top_highlights", [])
                    if not raw_top:
                        raw_top = [match_highlight]
                    formatted_top = []
                    for idx, th_item in enumerate(raw_top):
                        th = dict(th_item)
                        th_g_sec = th.get("game_sec", 0)
                        th_start = max(0, curr_offset + th_g_sec - lead_in)
                        th_tc = f"{th_start // 60}:{th_start % 60:02d}"
                        th_embed, th_watch = build_highlight_embed_url(video_url, th_start)
                        th["embed_url"] = th_embed
                        th["watch_url"] = th_watch
                        th["embed_start_sec"] = th_start
                        th["timecode_display"] = th_tc
                        th["video_offset_sec"] = curr_offset
                        th_sid = th.get("player_steamid", "")
                        th_p_stat = get_p_data(th_sid, th.get("player_name"))
                        th_mmr = th_p_stat.get("mmr_after", th_p_stat.get("mmr_before", STARTING_MMR))
                        th["rank_tier"] = get_player_rank_tier(th_mmr)
                        th["team"] = th_p_stat.get("team", "")
                        th["order"] = idx + 1
                        formatted_top.append(th)
                    match_highlight["top_highlights"] = formatted_top
    except Exception as e:
        logging.warning(f"Ошибка загрузки хайлайта для матча {mid}: {e}")
        match_highlight = None

    return {
        "match_id": m.get("match_id"),
        "map_name": m.get("map_display", m.get("map")),
        "score1": m.get("score_team1", 0),
        "score2": m.get("score_team2", 0),
        "half_scores": half_scores_str,
        "date_display": m.get("date_display", ""),
        "team1": calc_totals(t1_rows),
        "team2": calc_totals(t2_rows),
        "team1_name": t1_name,
        "team2_name": t2_name,
        "team1_captain": t1_cap,
        "team2_captain": t2_cap,
        "stats": stats_leaders,
        "rounds": formatted_rounds,
        "economy": economy_chart,
        "duels": duels_matrix,
        "video_url": video_url,
        "video_offset_sec": video_offset_sec,
        "video_embed_url": video_embed_url,
        "highlight": match_highlight,
        "ai_analysis": format_round_analysis(m.get("ai_analysis", "")),
        "summary_analysis": format_coach_summary(m.get("summary_analysis", "")),
        "recommendations": m.get("recommendations", [])
    }

ROLES_CATALOG = [
    {
        "role_id": "awp",
        "title": "🎯 Основной снайпер (Main AWP)",
        "icon": "🎯",
        "short_title": "Снайпер",
        "lore": "Хозяин дальних дистанций и создатель численного преимущества первым выстрелом. Контролирует ключевые лонги и мид-коннекторы, создавая постоянную угрозу одномоментного убийства через всю карту.",
        "metrics_rules": "Доля фрагов с AWP >= 20% от общих фрагов, ИЛИ 20+ убийств с AWP при доле >= 15%. Система анализирует оружейную статистику из демок.",
        "skills_formula": "Aim × 0.5 + Positioning × 0.3 + Economy × 0.2",
        "skills_weights": {"Aim": 0.5, "Positioning": 0.3, "Economy": 0.2},
        "affinity_threshold": 70,
        "accent_color": "amber",
        "factual_names": ["Снайпер"]
    },
    {
        "role_id": "entry",
        "title": "⚡ Главный энтри-фраггер (First Entry)",
        "icon": "⚡",
        "short_title": "Энтри",
        "lore": "Острие атаки команды, взломщик закрытых позиций и создатель спейса на плентах. Бежит первым, открывает карту и создаёт численное преимущество через агрессивные пики.",
        "metrics_rules": "First Kill Rate >= 14.0% ИЛИ вовлечённость в первые дуэли (FK+FD)/Rounds >= 15% при винрейте дуэлей >= 45%.",
        "skills_formula": "Entry × 0.6 + Aim × 0.3 + Game Sense × 0.1",
        "skills_weights": {"Entry": 0.6, "Aim": 0.3, "Game Sense": 0.1},
        "affinity_threshold": 65,
        "accent_color": "red",
        "factual_names": ["Энтри-фраггер"]
    },
    {
        "role_id": "refragger",
        "title": "🔄 Второй номер / Трейдер (Refragger)",
        "icon": "🔄",
        "short_title": "Трейдер",
        "lore": "Бежит вторым темпом за энтри, мгновенно разменивает союзников и добирает раненых. Гарантирует, что ни одна смерть тиммейта не пропадёт зря.",
        "metrics_rules": "Trade Rate >= 20.0% (размен союзника в течение 3–4 секунд после его гибели).",
        "skills_formula": "Trading × 0.6 + Clutch × 0.2 + Aim × 0.2",
        "skills_weights": {"Trading": 0.6, "Clutch": 0.2, "Aim": 0.2},
        "affinity_threshold": 65,
        "accent_color": "orange",
        "factual_names": ["Второй номер"]
    },
    {
        "role_id": "anchor",
        "title": "🛡️ Опорник плента (Site Anchor)",
        "icon": "🛡️",
        "short_title": "Опорник",
        "lore": "Столп обороны, охраняющий плент в одиночку до прихода ротации с минимальным риском. Ведёт позиционную игру, используя перекрёстный огонь и пассивные углы.",
        "metrics_rules": "KAST >= 68.0%, выживаемость >= 30%, First Death Rate <= 10%. Игроки с минимальной частотой первых смертей и стабильным участием в раундах.",
        "skills_formula": "Positioning × 0.5 + Discipline × 0.3 + Game Sense × 0.2",
        "skills_weights": {"Positioning": 0.5, "Discipline": 0.3, "Game Sense": 0.2},
        "affinity_threshold": 65,
        "accent_color": "emerald",
        "factual_names": ["Опорник"]
    },
    {
        "role_id": "support",
        "title": "💡 Координатор / Саппорт (Support)",
        "icon": "💡",
        "short_title": "Саппорт",
        "lore": "Мастер раскидок, подготавливает выходы идеальными моменталками и отрезает врагов огнём. Слаженная утилити-игра решает раунды до первого выстрела.",
        "metrics_rules": "Utility Damage >= 6.0 HP/раунд ИЛИ Flash Assists >= 0.35 за матч. Игроки, вносящие наибольший вклад гранатами.",
        "skills_formula": "Utility × 0.6 + Discipline × 0.2 + Game Sense × 0.2",
        "skills_weights": {"Utility": 0.6, "Discipline": 0.2, "Game Sense": 0.2},
        "affinity_threshold": 65,
        "accent_color": "blue",
        "factual_names": ["Саппорт"]
    },
    {
        "role_id": "lurker",
        "title": "🥷 Люркер / Одиночка (Lurker)",
        "icon": "🥷",
        "short_title": "Люркер",
        "lore": "Контролирует противоположный фланг, отрезает ротации врага и читает тайминги перетяжек. Играет автономно и наказывает за ошибки в позиционировании.",
        "metrics_rules": "First Kill Rate <= 8.5%, выживаемость >= 30%, фокус на поздних фрагах в раунде. Низкая вовлечённость в первые дуэли, высокая автономность.",
        "skills_formula": "Game Sense × 0.4 + Positioning × 0.3 + Clutch × 0.3",
        "skills_weights": {"Game Sense": 0.4, "Positioning": 0.3, "Clutch": 0.3},
        "affinity_threshold": 65,
        "accent_color": "purple",
        "factual_names": ["Люркер"]
    },
    {
        "role_id": "clutcher",
        "title": "👑 Клатч-мастер (Clutcher / Finisher)",
        "icon": "👑",
        "short_title": "Клатчер",
        "lore": "Хладнокровный доигровщик раундов в ситуациях 1v1 / 1v2 / 1v3. Когда вся команда мертва — он остаётся один и выносит весь остаток.",
        "metrics_rules": "Clutch Winrate >= 30.0% при минимум 3 ситуациях 1vX за карьеру. Только реальные клатч-исполнители.",
        "skills_formula": "Clutch × 0.6 + Game Sense × 0.2 + Discipline × 0.2",
        "skills_weights": {"Clutch": 0.6, "Game Sense": 0.2, "Discipline": 0.2},
        "affinity_threshold": 65,
        "accent_color": "cyan",
        "factual_names": ["Клатчер"]
    },
    {
        "role_id": "igl",
        "title": "🧠 Ин-гейм лидер / Тактик (IGL)",
        "icon": "🧠",
        "short_title": "IGL",
        "lore": "Мозг команды, следит за макро-экономикой, читает структуру соперника и координирует закуп. Высокий Game Sense и экономическая дисциплина — главные оружия.",
        "metrics_rules": "Высокий KAST (>= 68%), экономическая дисциплина закупов (Economy Rating >= 5.5), минимальное количество бессмысленных смертей.",
        "skills_formula": "Game Sense × 0.5 + Economy × 0.3 + Discipline × 0.2",
        "skills_weights": {"Game Sense": 0.5, "Economy": 0.3, "Discipline": 0.2},
        "affinity_threshold": 65,
        "accent_color": "yellow",
        "factual_names": []
    }
]

def calc_affinity_score(ratings: dict, weights: dict) -> float:
    """Рассчитывает индекс совместимости с ролью (0-100%) на основе взвешенного среднего рейтингов."""
    total = 0.0
    for skill, w in weights.items():
        total += ratings.get(skill, 5.0) * w
    return round(total * 10.0, 1)  # Нормализация: рейтинг 10.0 = 100%

def format_player_data(p: dict) -> dict:
    """Форматирование данных игрока для шаблона player.html."""
    ratings = p.get("ratings", {})
    ov_stats = p.get("overall_stats", {})
    st = p.get("stability", {})
    wep_data = p.get("weapons", {})
    m_perf = p.get("map_performance", {})
    p_stats = p.get("pistol_rounds", {})
    eco_stats = p.get("vs_economy", {})
    raw_recs = p.get("recommendations", {})
    matches = p.get("matches", [])

    # Рейтинги в определенном порядке для Радарного графика
    rating_keys = ['Aim', 'Positioning', 'Utility', 'Game Sense', 'Entry', 'Trading', 'Clutch', 'Discipline', 'Economy', 'Overall Impact']
    radar_values = [round(ratings.get(k, 5.0), 1) for k in rating_keys]
    
    ratings_dict = {k: round(ratings.get(k, 5.0), 1) for k in rating_keys}

    # Позиционирование ролей
    roles = p.get("play_style", ["Рифлер"])

    # Оружие
    weapons_list = []
    tot_w_kills = max(1, sum(wep_data.get("categories", {}).values()))
    for cat, k_count in wep_data.get("categories", {}).items():
        weapons_list.append({
            "name": cat,
            "kills": k_count,
            "hs": round(ov_stats.get("avg_hs", 40.0), 1),
            "usage": round((k_count / tot_w_kills) * 100, 1)
        })

    # Карты
    maps_list = []
    best_map_name = m_perf.get("best_map", "")
    for map_name, map_rating in m_perf.get("map_ratings", {}).items():
        maps_list.append({
            "name": map_name,
            "matches": len([m for m in matches if m.get("map") == map_name]),
            "win_rate": 50, # Заглушка винрейта
            "avg_rating": round(map_rating, 1),
            "avg_kd": round(ov_stats.get("kd_ratio", 1.0), 2),
            "is_best": map_name == best_map_name
        })

    # Извлечение MMR данных
    mmr_data = p.get("mmr", {})
    curr_mmr = mmr_data.get("current_mmr", STARTING_MMR)
    peak_mmr = mmr_data.get("peak_mmr", STARTING_MMR)
    last_delta = mmr_data.get("last_delta", 0)

    # Сессионная дельта за крайний игровой день (сумма по всем матчам сессии)
    sp = p.get("session_progress") or {}
    sp_curr = sp.get("current") or {}
    session_delta = sp_curr.get("mmr_delta", last_delta)
    session_matches_count = sp.get("matches_count", 1)
    session_date_disp = sp.get("date_display", "")

    is_inactive = mmr_data.get("is_inactive", False)
    form_dots = mmr_data.get("form_dots", [])
    sparkline = mmr_data.get("sparkline", [])
    wins = mmr_data.get("wins", 0)
    losses = mmr_data.get("losses", 0)
    ties = mmr_data.get("ties", 0)
    avg_hltv = mmr_data.get("avg_hltv", 1.00)

    # Сортируем матчи по дате (DDMMYYYY) — хронологически, старые первыми
    matches_sorted_chrono = sorted(matches, key=lambda m: parse_date_key(m.get("date", "")))
    total_matches_count = len(matches_sorted_chrono)

    # Калибровка = первые 5 матчей по хронологии, не по количеству всех матчей
    is_calibrating = mmr_data.get("is_calibrating", total_matches_count <= CALIBRATION_MATCH_LIMIT)

    win_rate = mmr_data.get("win_rate", round((wins / max(1, total_matches_count)) * 100, 1))

    # История матчей (для таблицы — от новых к старым, т.е. обратный порядок)
    matches_for_display = sorted(matches, key=lambda m: parse_date_key(m.get("date", "")), reverse=True)
    match_history_table = []
    session_matches_dict = {}
    labels = []
    hist_adr = []
    hist_kd = []
    hist_rating = []
    hist_hltv = []

    for idx, m in enumerate(matches_for_display, start=1):
        m_id = m.get("match_id", "")
        m_date = m.get("date", "10072026")
        date_disp = format_date_display(m_date)
        date_short = f"{m_date[:2]}.{m_date[2:4]}" if len(m_date) >= 4 else m_date
        map_n = m.get("map_display") or m.get("map", "")
        if map_n.startswith("de_"):
            map_n = map_n[3:].title()
            
        k = m.get("kills", 0)
        d = m.get("deaths", 0)
        a = m.get("assists", 0)
        adr_val = m.get("adr", 0.0)
        kast_val = m.get("kast", 0.0)
        hs_val = m.get("hs_percent", 0.0)
        fk = m.get("first_kills", 0)
        fd = m.get("first_deaths", 0)
        
        kd = round(k / max(1, d), 2)
        
        # Получение честного рейтинга HLTV и приведенного 1-10
        r_val = m.get("score_10")
        h_val = m.get("hltv_rating")
        if r_val is None or h_val is None:
            h_val, r_val = compute_hltv_rating(k, d, a, adr_val, kast_val, fk, fd, 24)
            
        m_delta = m.get("mmr_delta", 0)
        m_breakdown = m.get("mmr_breakdown", "")
        
        # Подпись точки графика для Chart.js: Карта и Дата (без номера матча)
        labels.append([f"{map_n}", f"📅 {date_short}"])
        hist_adr.append(round(adr_val, 1))
        hist_kd.append(kd)
        hist_rating.append(round(r_val, 1))
        hist_hltv.append(round(h_val, 2))

        team_res = m.get("team_result")
        if not team_res:
            if m.get("is_win") is True or m_delta > 0:
                team_res = "win"
            elif m.get("is_loss") is True or m_delta < 0:
                team_res = "loss"
            else:
                team_res = "tie"

        match_obj = {
            "date": m_date,
            "date_display": date_disp,
            "match_id": m_id,
            "match_url": f"../matches/{m_id}.html",
            "map": map_n,
            "kda": f"{k} / {d} / {a}",
            "kills": k,
            "deaths": d,
            "assists": a,
            "adr": round(adr_val, 1),
            "kast": round(kast_val, 1),
            "hs": round(hs_val, 1),
            "hltv": round(h_val, 2),
            "rating": round(r_val, 1),
            "mmr_delta": m_delta,
            "mmr_delta_text": f"{m_delta:+d}" if m_delta != 0 else "0",
            "mmr_breakdown": m_breakdown,
            "team_result": team_res,
            "is_win": team_res == "win",
            "is_loss": team_res == "loss",
            "is_tie": team_res == "tie"
        }

        match_history_table.append(match_obj)
        
        if m_date not in session_matches_dict:
            session_matches_dict[m_date] = []
        session_matches_dict[m_date].append(match_obj)

    # Сортируем дни сессий строго по реальной дате (самые свежие первыми)
    session_groups = []
    sorted_dates = sorted(session_matches_dict.keys(), key=parse_date_key, reverse=True)
    for d_key in sorted_dates:
        m_list = session_matches_dict[d_key]
        session_groups.append({
            "date": d_key,
            "date_display": format_date_display(d_key),
            "matches": m_list
        })

    # Сортируем историю матчей: самые недавние первыми
    match_history_table.sort(key=lambda x: parse_date_key(x.get("date", "")), reverse=True)

    train_items = raw_recs.get("training", [])
    if isinstance(train_items, str):
        train_items = [train_items]
    if not train_items:
        train_items = ["Тренируй прицеливание на Aim Botz", "Разминайся на FFA DM перед матчами"]

    habits_items = raw_recs.get("habits_to_remove", [])
    if isinstance(habits_items, str):
        habits_items = [habits_items]
    if not habits_items:
        habits_items = ["Избегай одиночных выходов без коммуникации"]

    exercises_items = raw_recs.get("exercises", [])
    if isinstance(exercises_items, str):
        exercises_items = [exercises_items]
    if not exercises_items:
        exercises_items = ["Используй yprac карты для изучения раскидок"]

    ROLE_SLUG_MAP = {
        "снайпер": "awp",
        "awp": "awp",
        "энтри": "entry",
        "entry": "entry",
        "второй номер": "refragger",
        "трейдер": "refragger",
        "refragger": "refragger",
        "опорник": "anchor",
        "anchor": "anchor",
        "саппорт": "support",
        "support": "support",
        "координатор": "support",
        "люркер": "lurker",
        "lurker": "lurker",
        "клатчер": "clutcher",
        "clutcher": "clutcher",
        "ин-гейм лидер": "igl",
        "igl": "igl",
        "капитан": "igl",
        "универсал": "refragger"
    }

    def resolve_role_slug(role_name_str: str) -> str:
        if not role_name_str:
            return "awp"
        r_lower = role_name_str.lower()
        for k, v in ROLE_SLUG_MAP.items():
            if k in r_lower:
                return v
        return "awp"

    role_text = raw_recs.get("best_role", "Универсал")
    current_role_text = raw_recs.get("current_role", roles[0] if roles else "Универсал")

    # Форматирование квестов с гарантированным id и quest_id
    formatted_quests = []
    for q in raw_recs.get("quests", []):
        q_copy = dict(q)
        q_id = q_copy.get("id") or q_copy.get("quest_id") or ""
        q_copy["id"] = q_id
        q_copy["quest_id"] = q_id
        formatted_quests.append(q_copy)
        
    tq_copy = None
    if raw_recs.get("target_quest"):
        tq_copy = dict(raw_recs.get("target_quest"))
        tq_id = tq_copy.get("id") or tq_copy.get("quest_id") or ""
        tq_copy["id"] = tq_id
        tq_copy["quest_id"] = tq_id

    # Расчет совместимости со всеми 8 ролями
    def get_rating_class(score: float) -> str:
        if score >= 8.0:
            return "text-amber-400 font-bold"
        elif score >= 7.0:
            return "text-emerald-400 font-bold"
        elif score >= 5.0:
            return "text-yellow-400 font-bold"
        return "text-red-400 font-bold"

    SKILL_ICONS = {
        "Aim": "🎯", "Positioning": "🗺️", "Utility": "🧨", "Game Sense": "🧠",
        "Entry": "⚡", "Trading": "🔄", "Clutch": "👑", "Discipline": "🧘", "Economy": "💰"
    }

    p_metrics = p.get("metrics", {})

    # Расчет совместимости со всеми 8 ролями
    player_role_affinities = []
    for rdef in ROLES_CATALOG:
        rid = rdef["role_id"]
        weights = rdef["skills_weights"]
        aff = calc_affinity_score(ratings_dict, weights)
        is_cur = any(fn in roles for fn in rdef["factual_names"])
        if rid == "igl" and ("Ин-гейм лидер" in role_text or "IGL" in role_text or "Капитан" in role_text):
            is_cur = True
        is_rec = (rid == resolve_role_slug(role_text))
        threshold = rdef["affinity_threshold"]
        
        if is_cur:
            badge_text = "Текущий стиль"
            badge_class = "bg-blue-950/80 text-blue-300 border border-blue-500/40"
        elif is_rec:
            badge_text = "Рекомендуется"
            badge_class = "bg-amber-950/80 text-amber-300 border border-amber-500/40"
        elif aff >= 80:
            badge_text = "Идеально"
            badge_class = "bg-amber-500/20 text-amber-300 border border-amber-500/40"
        elif aff >= 70:
            badge_text = "Высокий"
            badge_class = "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
        elif aff >= 50:
            badge_text = "Базовый"
            badge_class = "bg-sky-500/20 text-sky-300 border border-sky-500/40"
        else:
            badge_text = "Низкий"
            badge_class = "bg-slate-800 text-slate-400 border border-slate-700"

        # Цвета полосы прогресса по единой шкале
        if aff >= 80:
            bar_class = "bg-gradient-to-r from-amber-500 to-amber-300"
            text_class = "text-amber-400"
        elif aff >= 70:
            bar_class = "bg-gradient-to-r from-emerald-600 to-emerald-400"
            text_class = "text-emerald-400"
        elif aff >= 50:
            bar_class = "bg-gradient-to-r from-sky-600 to-cyan-400"
            text_class = "text-sky-400"
        else:
            bar_class = "bg-slate-500"
            text_class = "text-slate-400"

        # Детализация влияющих навыков с весами и иконками
        skills_breakdown = []
        for sk_name, w in weights.items():
            sk_val = ratings_dict.get(sk_name, 5.0)
            skills_breakdown.append({
                "name": sk_name,
                "icon": SKILL_ICONS.get(sk_name, "⭐"),
                "weight_pct": int(round(w * 100)),
                "rating": sk_val,
                "rating_class": get_rating_class(sk_val)
            })

        # Лучший и слабейший навык для анализа
        sorted_role_skills = sorted(weights.keys(), key=lambda k: ratings_dict.get(k, 5.0), reverse=True)
        best_skill = sorted_role_skills[0] if sorted_role_skills else "Aim"
        worst_skill = sorted_role_skills[-1] if sorted_role_skills else "Aim"
        best_val = ratings_dict.get(best_skill, 5.0)
        worst_val = ratings_dict.get(worst_skill, 5.0)

        # Фактическая статистика из демок для данной роли
        primary_metric = {}
        if rid == "awp":
            awp_pct = p_metrics.get("awp_kills_percent", 0.0)
            primary_metric = {
                "name": "Фраги с AWP",
                "value": f"{awp_pct:.1f}%",
                "norm": "Норматив ≥ 15%",
                "is_met": awp_pct >= 15.0
            }
        elif rid == "entry":
            fk_rate = p_metrics.get("first_kill_rate", 0.0)
            primary_metric = {
                "name": "First Kill Rate",
                "value": f"{fk_rate:.1f}%",
                "norm": "Норматив ≥ 14%",
                "is_met": fk_rate >= 14.0
            }
        elif rid == "refragger":
            tr_rate = p_metrics.get("trade_rate", 0.0)
            primary_metric = {
                "name": "Trade Rate (Размены)",
                "value": f"{tr_rate:.1f}%",
                "norm": "Норматив ≥ 20%",
                "is_met": tr_rate >= 20.0
            }
        elif rid == "anchor":
            kast_v = ov_stats.get("avg_kast", p_metrics.get("kast", 0.0))
            surv_v = ov_stats.get("survival_rate", p_metrics.get("survival_rate", 0.0))
            primary_metric = {
                "name": "KAST / Выживаемость",
                "value": f"{kast_v:.1f}% / {surv_v:.1f}%",
                "norm": "KAST ≥ 68% • Выж ≥ 30%",
                "is_met": kast_v >= 68.0 and surv_v >= 30.0
            }
        elif rid == "support":
            ud_val = p_metrics.get("utility_damage_per_round", 0.0)
            fa_val = p_metrics.get("flash_assists_per_match", p_metrics.get("flash_assists", 0.0))
            primary_metric = {
                "name": "Урон утилити / Flash",
                "value": f"{ud_val:.1f} HP / {fa_val:.1f} FA",
                "norm": "Урон ≥ 6 HP или FA ≥ 0.35",
                "is_met": ud_val >= 6.0 or fa_val >= 0.35
            }
        elif rid == "lurker":
            late_val = p_metrics.get("late_round_kills", 0.0)
            primary_metric = {
                "name": "Поздние фраги в раунде",
                "value": f"{late_val:.1f}%",
                "norm": "Норматив ≥ 15%",
                "is_met": late_val >= 15.0
            }
        elif rid == "clutcher":
            cl_wr = p_metrics.get("clutch_win_rate", 0.0)
            cl_w = int(p_metrics.get("clutch_wins", 0))
            primary_metric = {
                "name": "Клатчи 1vX (WR / Побед)",
                "value": f"{cl_wr:.1f}% ({cl_w} побед)",
                "norm": "WR ≥ 30% (от 3 ситуаций)",
                "is_met": cl_wr >= 30.0
            }
        elif rid == "igl":
            kast_v = ov_stats.get("avg_kast", p_metrics.get("kast", 0.0))
            eco_val = ratings_dict.get("Economy", 5.0)
            primary_metric = {
                "name": "KAST / Экономика",
                "value": f"{kast_v:.1f}% / {eco_val:.1f} R",
                "norm": "KAST ≥ 68% • Эко ≥ 5.5",
                "is_met": kast_v >= 68.0 and eco_val >= 5.5
            }

        # Текстовое обоснование оценки
        if is_cur:
            reasoning = f"Фактическое амплуа по демкам. Оценка {aff}% опирается на сильный навык {best_skill} ({best_val}/10)."
            if worst_val < 6.0:
                reasoning += f" Точка дальнейшего роста — подтянуть {worst_skill} ({worst_val}/10)."
        elif is_rec:
            reasoning = f"Главная рекомендация тренера: оптимальный баланс {best_skill} ({best_val}/10) и командной синергии для максимального импакта."
        elif aff >= 80:
            reasoning = f"Идеальный скрытый потенциал! Высокие показатели {best_skill} ({best_val}/10) и {worst_skill} ({worst_val}/10) позволяют уверенно претендовать на основу."
        elif aff >= 70:
            reasoning = f"Высокая квалификация: солидный уровень {best_skill} ({best_val}/10) уверенно перекрывает квалификационный норматив."
            if worst_val < 6.5:
                reasoning += f" Сдерживающий фактор — {worst_skill} ({worst_val}/10)."
        elif aff >= 50:
            reasoning = f"Базовое соответствие: игрок стабилен в {best_skill} ({best_val}/10), но отставание в {worst_skill} ({worst_val}/10) требует целевых тренировок."
        else:
            reasoning = f"Низкая совместимость: профиль игрока не ложится на модель роли из-за дефицита в {worst_skill} ({worst_val}/10)."

        # Краткий вердикт
        if is_cur:
            verdict = "В основе"
        elif is_rec:
            verdict = "Приоритет"
        elif aff >= threshold:
            verdict = "Квалифицирован"
        elif aff >= 55:
            verdict = "Резерв"
        else:
            verdict = "Не профиль"

        player_role_affinities.append({
            "role_id": rid,
            "title": rdef["title"],
            "short_title": rdef["short_title"],
            "icon": rdef["icon"],
            "lore": rdef["lore"],
            "affinity": aff,
            "threshold": threshold,
            "is_current": is_cur,
            "is_recommended": is_rec,
            "badge_text": badge_text,
            "badge_class": badge_class,
            "bar_class": bar_class,
            "text_class": text_class,
            "skills_breakdown": skills_breakdown,
            "primary_metric": primary_metric,
            "reasoning": reasoning,
            "verdict": verdict
        })

    # Сортируем: сначала текущая и рекомендуемая роль, затем по убыванию совместимости
    player_role_affinities.sort(key=lambda x: (x["is_current"] or x["is_recommended"], x["affinity"]), reverse=True)

    return {
        "steam_id": p.get("steam_id"),
        "name": clean_name(p.get("name")),
        "rank_tier": get_player_rank_tier(curr_mmr, is_calibrating=is_calibrating, is_inactive=is_inactive),
        "rating": round(ratings.get("Overall Impact", 5.0), 1),
        "ratings": radar_values,
        "ratings_dict": ratings_dict,
        "roles": roles,
        "role_slug": resolve_role_slug(roles[0] if roles else ""),
        "best_role_slug": resolve_role_slug(role_text),
        "total_matches": len(matches),
        "mmr": {
            "current_mmr": curr_mmr,
            "peak_mmr": peak_mmr,
            "last_delta": last_delta,
            "last_delta_text": f"{last_delta:+d}" if last_delta != 0 else "0",
            "session_delta": session_delta,
            "session_delta_text": f"{session_delta:+d}" if session_delta != 0 else "0",
            "session_matches_count": session_matches_count,
            "session_date_display": session_date_disp,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "win_rate": win_rate,
            "avg_hltv": avg_hltv,
            "is_calibrating": is_calibrating,
            "is_inactive": is_inactive,
            "form_dots": form_dots,
            "sparkline": sparkline
        },
        "stats": {
            "kd": round(ov_stats.get("kd_ratio", 1.0), 2),
            "adr": round(ov_stats.get("avg_adr", 70.0), 1),
            "kast": round(ov_stats.get("avg_kast", 65.0), 1),
            "hs": round(ov_stats.get("avg_hs", 40.0), 1),
            "win_rate": win_rate,
            "fk_rate": round(p.get("metrics", {}).get("first_kill_rate", 15.0), 1),
            "clutch_rate": round(p.get("metrics", {}).get("clutch_win_rate", 20.0), 1),
            "util_dmg": round(p.get("metrics", {}).get("utility_damage_per_round", 0.0), 1)
        },
        "strengths": p.get("strengths", []),
        "weaknesses": p.get("weaknesses", []),
        "stability": {
            "score": int(st.get("stability_score", 5.0) * 10),
            "most_stable": st.get("most_stable", "Аим"),
            "least_stable": st.get("least_stable", "Позиционирование"),
            "badge": "Высокая стабильность" if st.get("stability_score", 5.0) >= 6 else "Нестабильный"
        },
        "match_history": {
            "labels": labels,
            "adr": hist_adr,
            "kd": hist_kd,
            "rating": hist_rating,
            "hltv": hist_hltv
        },
        "session_groups": session_groups,
        "match_history_table": match_history_table,
        "weapons": weapons_list,
        "pistol_stats": {
            "win_rate": p_stats.get("win_rate", 50),
            "avg_kills": p_stats.get("avg_kills", 1.0),
            "effectiveness": f"{p_stats.get('effectiveness', 5.0):.1f} / 10"
        },
        "eco_stats": {
            "full_buy_kd": eco_stats.get("vs_full_buy_kd", 1.0),
            "force_buy_kd": eco_stats.get("vs_force_buy_kd", 1.2),
            "eco_kd": eco_stats.get("vs_eco_kd", 1.5)
        },
        "maps": maps_list,
        "recommendations": {
            "train": train_items,
            "habits": habits_items,
            "exercises": exercises_items,
            "role": role_text,
            "best_role": role_text,
            "current_role": current_role_text,
            "role_comparison": raw_recs.get("role_comparison", f"Текущий стиль: {current_role_text} ➔ Рекомендуется: {role_text}"),
            "quests": formatted_quests,
            "target_quest": tq_copy
        },
        "role_affinities": player_role_affinities,
        "session_progress": p.get("session_progress"),
        "map_performance": p.get("map_performance", {}),
        "faceit_map_performance": compute_faceit_map_performance(p.get("faceit")),
        "archetype": p.get("archetype", {}),
        "momentum": p.get("momentum", {}),
        "connections": p.get("connections", {}),
        "achievements": p.get("achievements", []),
        "achievements_summary": p.get("achievements_summary") or {
            "total_unlocked": sum(1 for a in p.get("achievements", []) if a.get("unlocked")),
            "total_count": len(p.get("achievements", [])),
            "tier1_count": sum(1 for a in p.get("achievements", []) if a.get("tier") == 1),
            "tier2_count": sum(1 for a in p.get("achievements", []) if a.get("tier") == 2),
            "tier3_count": sum(1 for a in p.get("achievements", []) if a.get("tier") == 3),
            "total_points": sum(a.get("points", 0) for a in p.get("achievements", [])),
            "max_points": max(1, len(p.get("achievements", [])) * 500),
            "points_pct": round(sum(a.get("points", 0) for a in p.get("achievements", [])) / max(1, len(p.get("achievements", [])) * 500) * 100, 1)
        },
        "ai_analysis": p.get("ai_analysis", ""),
        "overall_stats": ov_stats,
        "faceit": p.get("faceit")
    }

def format_session_data(s: dict) -> dict:
    """Форматирование данных сессии для шаблона session.html."""
    s_matches = s.get("matches", [])
    
    formatted_matches = []
    tot_rounds = 0
    
    player_stats_acc = {}

    for m in s_matches:
        formatted_m = format_match_data(m)
        formatted_matches.append({
            "match_id": m.get("match_id"),
            "map_name": formatted_m.get("map_name"),
            "score1": formatted_m.get("score1"),
            "score2": formatted_m.get("score2"),
            "team1_name": formatted_m.get("team1_name"),
            "team2_name": formatted_m.get("team2_name"),
            "duration": f"{len(formatted_m.get('rounds', []))} раундов"
        })
        tot_rounds += len(formatted_m.get("rounds", []))

        # Агрегация показателей игроков за сессию
        for p in m.get("players", {}).values():
            sid = clean_steamid(p.get("steam_id"))
            if not sid:
                continue
            p_name = clean_name(p.get("name"))
            if sid not in player_stats_acc:
                player_stats_acc[sid] = {
                    "steam_id": sid,
                    "name": p_name,
                    "matches_played": 0,
                    "kills": 0,
                    "deaths": 0,
                    "assists": 0,
                    "total_adr": 0.0,
                    "total_kast": 0.0,
                    "total_hs": 0.0,
                    "first_kills": 0,
                    "clutch_wins": 0,
                    "utility_damage": 0
                }
            acc = player_stats_acc[sid]
            acc["matches_played"] += 1
            acc["kills"] += p.get("kills", 0)
            acc["deaths"] += p.get("deaths", 0)
            acc["assists"] += p.get("assists", 0)
            acc["total_adr"] += p.get("adr", 0.0)
            acc["total_kast"] += p.get("kast", 0.0)
            acc["total_hs"] += p.get("hs_percent", 0.0)
            acc["first_kills"] += p.get("first_kills", 0)
            acc["clutch_wins"] += p.get("clutch_wins", 0)
            acc["utility_damage"] += p.get("utility_damage", 0)

    session_players = []
    for acc in player_stats_acc.values():
        m_cnt = max(1, acc["matches_played"])
        avg_adr = round(acc["total_adr"] / m_cnt, 1)
        avg_kast = round(acc["total_kast"] / m_cnt, 1)
        avg_hs = round(acc["total_hs"] / m_cnt, 1)
        
        # Честный расчет рейтингов HLTV и 1-10
        hltv_val, score_10 = compute_hltv_rating(
            acc["kills"], acc["deaths"], acc["assists"], avg_adr, avg_kast,
            acc["first_kills"], 0, max(1, m_cnt * 20)
        )
        
        session_players.append({
            "steam_id": acc["steam_id"],
            "name": acc["name"],
            "matches_played": acc["matches_played"],
            "kills": acc["kills"],
            "deaths": acc["deaths"],
            "assists": acc["assists"],
            "avg_adr": avg_adr,
            "avg_kast": avg_kast,
            "avg_hs": avg_hs,
            "hltv": round(hltv_val, 2),
            "rating": round(score_10, 1),
            "first_kills": acc["first_kills"],
            "clutch_wins": acc["clutch_wins"],
            "utility_damage": acc["utility_damage"]
        })

    def get_top_player(key):
        if not session_players:
            return {"name": "—", "value": "0"}
        best = max(session_players, key=lambda p: p.get(key, 0))
        return {"name": best.get("name"), "value": str(best.get(key, 0))}

    mvp_player = max(session_players, key=lambda p: p.get("rating", 0)) if session_players else None

    return {
        "date": s.get("date"),
        "date_display": s.get("date_display"),
        "total_matches": len(s_matches),
        "match_count": len(s_matches),
        "total_rounds": tot_rounds,
        "mvp": {"name": mvp_player.get("name"), "rating": mvp_player.get("rating")} if mvp_player else None,
        "matches": formatted_matches,
        "players": session_players,
        "stats": {
            "most_kills": get_top_player("kills"),
            "most_clutches": get_top_player("clutch_wins"),
            "best_entry": get_top_player("first_kills"),
            "most_util_dmg": get_top_player("utility_damage")
        }
    }

def generate_site():
    """Основная функция генерации всех HTML страниц сайта."""
    logging.info("Начинаем генерацию HTML сайта...")
    
    matches, players, sessions = load_data()
    
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    
    import shutil
    for sub in ["matches", "players", "sessions"]:
        d_path = SITE_DIR / sub
        if d_path.exists():
            shutil.rmtree(d_path)
        os.makedirs(d_path, exist_ok=True)
    os.makedirs(SITE_DIR / "css", exist_ok=True)

    generated_at = datetime.now().strftime("%d.%m.%Y %H:%M")

    stats_summary = {
        "total_matches": len(matches),
        "total_players": len(players),
        "total_sessions": len(sessions)
    }

    # Компактный список игроков для виджета персонализации профиля "Кто ты?"
    all_players_compact = []
    for p in players:
        sid = clean_steamid(p.get("steam_id"))
        if sid:
            all_players_compact.append({
                "steam_id": sid,
                "name": clean_name(p.get("name"))
            })
    all_players_compact.sort(key=lambda x: x["name"].lower())
    env.globals["all_players_compact"] = all_players_compact
    env.globals["render_faceit_svg"] = render_faceit_svg

    # Сборка непрерывного лидерборда игроков по MMR
    leaderboard_players = []
    for p in players:
        sid = clean_steamid(p.get("steam_id"))
        if not sid:
            continue
        p_name = clean_name(p.get("name"))
        mmr_data = p.get("mmr", {})
        curr_mmr = mmr_data.get("current_mmr", STARTING_MMR)
        peak_mmr = mmr_data.get("peak_mmr", STARTING_MMR)
        last_delta = mmr_data.get("last_delta", 0)

        # Сессионная дельта за крайний игровой день (сумма всех матчей сессии)
        sp = p.get("session_progress") or {}
        sp_curr = sp.get("current") or {}
        session_delta = sp_curr.get("mmr_delta", last_delta)
        session_matches_count = sp.get("matches_count", 1)
        session_date_disp = sp.get("date_display", "")

        overall_rating = p.get("ratings", {}).get("Overall Impact", 5.0)
        avg_hltv = mmr_data.get("avg_hltv", 1.00)
        tot_m = len(p.get("matches", []))
        wins = mmr_data.get("wins", 0)
        losses = mmr_data.get("losses", 0)
        ties = mmr_data.get("ties", 0)
        win_rate = mmr_data.get("win_rate", round((wins / max(1, tot_m)) * 100, 1))

        is_cal = mmr_data.get("is_calibrating", tot_m <= CALIBRATION_MATCH_LIMIT)
        is_inac = mmr_data.get("is_inactive", False)
        tier = get_player_rank_tier(curr_mmr, is_calibrating=is_cal, is_inactive=is_inac)

        leaderboard_players.append({
            "steam_id": sid,
            "name": p_name,
            "avatar_initials": p_name[:2].upper(),
            "rank_tier": tier,
            "current_mmr": curr_mmr,
            "peak_mmr": peak_mmr,
            "last_delta": session_delta,
            "last_delta_text": f"{session_delta:+d}" if session_delta != 0 else "0",
            "session_delta": session_delta,
            "session_delta_text": f"{session_delta:+d}" if session_delta != 0 else "0",
            "session_matches_count": session_matches_count,
            "session_date_display": session_date_disp,
            "rating": round(overall_rating, 1),
            "hltv_rating": avg_hltv,
            "kd_ratio": round(p.get("overall_stats", {}).get("kd_ratio", 1.0), 2),
            "adr": round(p.get("overall_stats", {}).get("avg_adr", 0.0), 1),
            "kast": round(p.get("overall_stats", {}).get("avg_kast", 65.0), 1),
            "total_matches": tot_m,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "win_rate": win_rate,
            "roles": p.get("play_style", ["Рифлер"]),
            "current_role": p.get("recommendations", {}).get("current_role", p.get("play_style", ["Рифлер"])[0] if p.get("play_style") else "Рифлер"),
            "best_role": p.get("recommendations", {}).get("best_role", p.get("play_style", ["Рифлер"])[0] if p.get("play_style") else "Рифлер"),
            "ratings": p.get("ratings", {}),
            "recommendations": p.get("recommendations", {}),
            "is_calibrating": is_cal,
            "is_inactive": is_inac,
            "form_dots": mmr_data.get("form_dots", []),
            "momentum": p.get("momentum", {}),
            "archetype": p.get("archetype", {}),
            "faceit": p.get("faceit")
        })

    # Разделение таблицы лидеров:
    # 1. Прошедшие калибровку (5+ матчей) - получают официальные места #1, #2, #3...
    calibrated_players = [p for p in leaderboard_players if not p["is_calibrating"]]
    calibrated_players.sort(key=lambda x: (x["current_mmr"], x["rating"]), reverse=True)
    for rank_idx, lp in enumerate(calibrated_players, start=1):
        lp["rank"] = rank_idx
        lp["is_ranked"] = True

    # 2. Игроки на калибровке (<5 матчей) - опущены вниз рейтинга, ранг "—"
    calibrating_players = [p for p in leaderboard_players if p["is_calibrating"]]
    calibrating_players.sort(key=lambda x: (x["current_mmr"], x["rating"]), reverse=True)
    for lp in calibrating_players:
        lp["rank"] = None
        lp["is_ranked"] = False

    leaderboard_players = calibrated_players + calibrating_players

    recent_matches = sorted(matches, key=lambda m: parse_date_key(m.get("date", "")), reverse=True)
    recent_matches_display = []
    for m in recent_matches:
        recent_matches_display.append({
            "match_id": m.get("match_id"),
            "map_name": m.get("map_display", m.get("map")),
            "team1_score": m.get("score_team1", 0),
            "team2_score": m.get("score_team2", 0),
            "team1_name": m.get("team1_name", "Команда 1"),
            "team2_name": m.get("team2_name", "Команда 2"),
            "date_display": m.get("date_display")
        })

    # Генерация статических Faceit SVG иконок
    generate_faceit_svg_files(SITE_DIR / "icons" / "faceit")

    # Конфигурация уровней Faceit для модального окна на главной
    faceit_levels_info = [
        {"level": 10, "mmr": "≥ 1180", "badge_svg": render_faceit_svg(10, 22), "classes": "bg-red-950/40 border-red-500/50 text-red-200"},
        {"level": 9,  "mmr": "1135 – 1179", "badge_svg": render_faceit_svg(9, 22), "classes": "bg-orange-950/40 border-orange-500/40 text-orange-200"},
        {"level": 8,  "mmr": "1090 – 1134", "badge_svg": render_faceit_svg(8, 22), "classes": "bg-orange-950/40 border-orange-500/40 text-orange-200"},
        {"level": 7,  "mmr": "1045 – 1089", "badge_svg": render_faceit_svg(7, 22), "classes": "bg-amber-950/40 border-amber-400/40 text-amber-200"},
        {"level": 6,  "mmr": "1000 – 1044", "badge_svg": render_faceit_svg(6, 22), "classes": "bg-amber-950/40 border-amber-400/40 text-amber-200"},
        {"level": 5,  "mmr": "955 – 999",   "badge_svg": render_faceit_svg(5, 22), "classes": "bg-amber-950/40 border-amber-400/40 text-amber-200"},
        {"level": 4,  "mmr": "910 – 954",   "badge_svg": render_faceit_svg(4, 22), "classes": "bg-amber-950/40 border-amber-400/40 text-amber-200"},
        {"level": 3,  "mmr": "865 – 909",   "badge_svg": render_faceit_svg(3, 22), "classes": "bg-emerald-950/40 border-emerald-500/40 text-emerald-200"},
        {"level": 2,  "mmr": "820 – 864",   "badge_svg": render_faceit_svg(2, 22), "classes": "bg-emerald-950/40 border-emerald-500/40 text-emerald-200"},
        {"level": 1,  "mmr": "< 820",       "badge_svg": render_faceit_svg(1, 22), "classes": "bg-slate-800/40 border-slate-500/40 text-slate-300"},
    ]

    # Форматирование игровых сессий для главной страницы и детальных страниц сессий
    formatted_sessions = [format_session_data(s) for s in sessions]

    # Загрузка сессионных наград для Зала славы (5 номинаций)
    session_awards = {}
    awards_path = DATA_DIR / "session_awards.json"
    if awards_path.exists():
        try:
            with open(awards_path, "r", encoding="utf-8") as f:
                session_awards = json.load(f)
        except Exception as e:
            logging.warning(f"Ошибка загрузки session_awards.json: {e}")

    # Расчет Барометра формы для главной страницы (Топ на подъеме vs Зона спада)
    active_players_with_mom = [
        p for p in leaderboard_players 
        if p.get("momentum") and p.get("momentum", {}).get("delta") is not None and not p.get("is_inactive")
    ]
    active_players_with_mom.sort(key=lambda x: x["momentum"]["delta"], reverse=True)
    top_gainers = [p for p in active_players_with_mom if p["momentum"]["delta"] > 0][:3]
    cooling_down = [p for p in active_players_with_mom if p["momentum"]["delta"] < 0]
    cooling_down.sort(key=lambda x: x["momentum"]["delta"])
    cooling_down = cooling_down[:3]

    def safe_dump(stream, target_path):
        import time
        t_path = Path(target_path)
        t_path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(5):
            try:
                with open(t_path, "wb") as f:
                    stream.dump(f, encoding="utf-8")
                return
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(0.1)

    # Загрузка хайлайта для главной страницы (выбор ИИ за крайнюю сессию)
    session_highlight = None
    try:
        hl_file = DATA_DIR / "highlights.json"
        if hl_file.exists():
            with open(hl_file, "r", encoding="utf-8") as hf:
                hl_data = json.load(hf)
                sess_hls = hl_data.get("session_highlights", {})
                if sess_hls:
                    # Выбираем хайлайт крайней сессии (по дате DDMMYYYY)
                    latest_date = sorted(sess_hls.keys(), key=lambda d: parse_date_key(d))[-1]
                    raw_shl = sess_hls[latest_date]
                    session_highlight = dict(raw_shl)

                    mid = session_highlight.get("match_id", "")
                    vf = DATA_DIR / "match_videos.json"
                    v_url = ""
                    v_offset = 0
                    if vf.exists():
                        try:
                            with open(vf, "r", encoding="utf-8") as v_f:
                                v_dict = json.load(v_f)
                                v_entry = v_dict.get(mid, "")
                                if isinstance(v_entry, dict):
                                    v_url = (v_entry.get("url", "") or "").strip()
                                    v_offset = int(v_entry.get("offset_sec", 0) or 0)
                                else:
                                    v_url = (str(v_entry) if v_entry else "").strip()
                                    v_offset = 0
                        except Exception:
                            pass

                    g_sec = session_highlight.get("game_sec", 0)
                    lead_in = 6
                    start_sec = max(0, v_offset + g_sec - lead_in)
                    session_highlight["video_url"] = v_url
                    session_highlight["video_offset_sec"] = v_offset
                    session_highlight["embed_start_sec"] = start_sec
                    session_highlight["timecode_display"] = f"{start_sec // 60}:{start_sec % 60:02d}"

                    hl_embed, hl_watch = build_highlight_embed_url(v_url, start_sec)
                    session_highlight["embed_url"] = hl_embed
                    session_highlight["watch_url"] = hl_watch
                    session_highlight["match_url"] = f"matches/{mid}.html"
                    session_highlight["date_display"] = format_date_display(latest_date)

                    # Ранг игрока
                    p_sid = session_highlight.get("player_steamid", "")
                    p_found = next((p for p in leaderboard_players if p.get("steam_id") == p_sid), None)
                    if p_found:
                        session_highlight["rank_tier"] = p_found.get("rank_tier")
                        session_highlight["current_mmr"] = p_found.get("current_mmr")
                    else:
                        session_highlight["rank_tier"] = get_player_rank_tier(STARTING_MMR)
                        session_highlight["current_mmr"] = STARTING_MMR
    except Exception as e:
        logging.warning(f"Ошибка загрузки session_highlight для главной: {e}")
        session_highlight = None

    # 1. Генерация index.html
    index_template = env.get_template("index.html")
    safe_dump(
        index_template.stream(
            active_page="index",
            css_path="css/style.css",
            js_path="js/app.js",
            root_path="",
            stats=stats_summary,
            players=leaderboard_players,
            faceit_levels_info=faceit_levels_info,
            sessions=formatted_sessions,
            recent_matches=recent_matches_display,
            session_awards=session_awards,
            session_highlight=session_highlight,
            top_gainers=top_gainers,
            cooling_down=cooling_down,
            generated_at=generated_at
        ),
        SITE_DIR / "index.html"
    )
    logging.info("Сгенерирована главная страница: site/index.html")

    # 2. Генерация страниц матчей matches/{match_id}.html
    all_match_ids = [m.get("match_id") for m in matches if m.get("match_id")]
    sync_match_videos(all_match_ids)
    match_template = env.get_template("match.html")
    for m in matches:
        match_id = m.get("match_id")
        formatted_m = format_match_data(m)
        safe_dump(
            match_template.stream(
                active_page="match",
                css_path="../css/style.css",
                js_path="../js/app.js",
                root_path="../",
                match=formatted_m,
                score1=formatted_m.get("score1", 0),
                score2=formatted_m.get("score2", 0),
                generated_at=generated_at
            ),
            SITE_DIR / "matches" / f"{match_id}.html"
        )
    logging.info(f"Сгенерированы страницы для {len(matches)} матчей")

    # 3. Генерация страниц игроков players/{steam_id}.html
    player_template = env.get_template("player.html")
    for p in players:
        sid = clean_steamid(p.get("steam_id"))
        if not sid:
            continue
        formatted_p = format_player_data(p)
        safe_dump(
            player_template.stream(
                active_page="player",
                css_path="../css/style.css",
                js_path="../js/app.js",
                root_path="../",
                player=formatted_p,
                generated_at=generated_at
            ),
            SITE_DIR / "players" / f"{sid}.html"
        )
    logging.info(f"Сгенерированы страницы для {len(players)} игроков")

    # 4. Генерация страниц сессий sessions/{date}.html
    session_template = env.get_template("session.html")
    for formatted_s in formatted_sessions:
        s_date = formatted_s.get("date")
        if not s_date:
            continue
        safe_dump(
            session_template.stream(
                active_page="session",
                css_path="../css/style.css",
                js_path="../js/app.js",
                root_path="../",
                session=formatted_s,
                generated_at=generated_at
            ),
            SITE_DIR / "sessions" / f"{s_date}.html"
        )
    logging.info(f"Сгенерированы страницы для {len(formatted_sessions)} игровых сессий")

    # 5. Генерация страницы рейтинга навыков site/skills.html
    skills_config = [
        ("aim", "Aim", "Аим и стрельба", "🎯", "Точность стрельбы, процент попадания в голову (HS%) и наносимый урон за раунд (ADR).", "HS% / ADR"),
        ("positioning", "Positioning", "Позиционирование", "🛡️", "Выживаемость, минимизация неоправданных смертей и грамотный выбор оборонительных углов.", "K/D / DPR"),
        ("utility", "Utility", "Гранаты и утилити", "💣", "Эффективность применения гранат: урон от осколочных и зажигательных, ослепление врагов.", "UD/раунд / Flash"),
        ("game-sense", "Game Sense", "Понимание игры", "🧠", "KAST% (вклад в каждый раунд), своевременность перетяжек и чтение таймингов оппонента.", "KAST%"),
        ("entry", "Entry", "Опенинг и первые дуэли", "⚔️", "Частота и результативность первого контакта в раунде, создание численного преимущества.", "FK% / Успех"),
        ("trading", "Trading", "Размены тиммейтов", "🤝", "Процент и скорость мгновенного размена погибших тиммейтов (re-frag) без потери преимущества.", "Размены"),
        ("clutch", "Clutch", "Клатчи и 1vX", "🏆", "Хладнокровие и процент выигранных раундов при численном меньшинстве (1v1, 1v2+).", "Клатчи (Винрейт)"),
        ("discipline", "Discipline", "Дисциплина и закуп", "⚖️", "Соблюдение общекомандного плана закупок, экономия средств и отказ от лишнего риска.", "Дисциплина"),
        ("economy", "Economy", "Экономическая игра", "💰", "Эффективность игры на форс-баях и эко-раундах, нанесение максимального финансового ущерба врагу.", "Эко-эффективность"),
        ("overall-impact", "Overall Impact", "Общий импакт", "⚡", "Комплексное совокупное влияние на исход каждого раунда и карты в целом.", "HLTV 2.0 / MMR"),
    ]

    skills_data = {}
    for s_id, s_key, s_title, s_icon, s_desc, s_stat_label in skills_config:
        sorted_p = []
        for p in players:
            sid = clean_steamid(p.get("steam_id"))
            if not sid:
                continue
            r_val = round(p.get("ratings", {}).get(s_key, 5.0), 1)
            mmr_d = p.get("mmr", {})
            curr_m = mmr_d.get("current_mmr", STARTING_MMR)
            is_cal_p = mmr_d.get("is_calibrating", len(p.get("matches", [])) <= CALIBRATION_MATCH_LIMIT)
            is_inac_p = mmr_d.get("is_inactive", False)
            rt = get_player_rank_tier(curr_m, is_calibrating=is_cal_p, is_inactive=is_inac_p)
            ov = p.get("overall_stats", {})
            met = p.get("metrics", {})

            if s_id == "aim":
                stat_text = f"{ov.get('avg_hs', 0):.1f}% HS • {ov.get('avg_adr', 0):.1f} ADR"
            elif s_id == "positioning":
                stat_text = f"{ov.get('kd_ratio', 1.0):.2f} K/D • {met.get('dpr', 0.6):.2f} DPR"
            elif s_id == "utility":
                stat_text = f"{met.get('utility_damage_per_round', 0):.1f} UD/rnd • {met.get('flash_assists_per_match', 0):.1f} Flash/m"
            elif s_id == "game-sense":
                stat_text = f"{ov.get('avg_kast', 0):.1f}% KAST"
            elif s_id == "entry":
                stat_text = f"{met.get('first_kill_rate', 0):.1f}% FK • {met.get('entry_success', 0):.0f}% Win"
            elif s_id == "trading":
                stat_text = f"{met.get('trade_rate', 0):.1f}% Trade Rate"
            elif s_id == "clutch":
                stat_text = f"{met.get('clutch_win_rate', 0):.0f}% WR ({met.get('clutch_attempts', 0):.0f} попыток)"
            elif s_id == "discipline":
                stat_text = f"Выживание: {met.get('won_round_survival', 50):.0f}% • Оценка {r_val}/10"
            elif s_id == "economy":
                stat_text = f"{met.get('eco_round_kills', 0):.2f} Eco KPR • {met.get('force_buy_eff', 1.0):.2f} Force K/D"
            else:
                stat_text = f"{mmr_d.get('avg_hltv', 1.0):.2f} HLTV • {curr_m} MMR"

            p_name = clean_name(p.get("name", f"Player_{sid[-4:]}"))
            sorted_p.append({
                "steam_id": sid,
                "name": p_name,
                "avatar_initials": p_name[:2].upper(),
                "rank_tier": rt,
                "roles": p.get("play_style", ["Универсал"]),
                "score": r_val,
                "stat_text": stat_text,
                "hltv_rating": mmr_d.get("avg_hltv", 1.0),
                "current_mmr": curr_m,
                "total_matches": ov.get("total_matches", len(p.get("matches", [])))
            })

        sorted_p.sort(key=lambda x: (x["score"], x["hltv_rating"], x["current_mmr"]), reverse=True)
        skills_data[s_id] = {
            "key": s_key,
            "title_ru": s_title,
            "icon": s_icon,
            "desc": s_desc,
            "stat_label": s_stat_label,
            "players": sorted_p
        }

    skills_template = env.get_template("skills.html")
    safe_dump(
        skills_template.stream(
            active_page="skills",
            css_path="css/style.css",
            js_path="js/app.js",
            root_path="",
            skills_data=skills_data,
            generated_at=generated_at
        ),
        SITE_DIR / "skills.html"
    )
    logging.info("Сгенерирована страница навыков: site/skills.html")

    # 6. Генерация страницы Зала славы (site/achievements.html) и 30 персональных страниц (site/achievements/<id>.html)
    glory_leaderboard = []

    for p in players:
        sid = clean_steamid(p.get("steam_id"))
        if not sid:
            continue
        p_name = clean_name(p.get("name", f"Player_{sid[-4:]}"))
        ach_list = p.get("achievements", [])
        ach_summary = p.get("achievements_summary", {})

        mmr_d = p.get("mmr", {})
        curr_m = mmr_d.get("current_mmr", STARTING_MMR)
        is_cal = mmr_d.get("is_calibrating", len(p.get("matches", [])) <= CALIBRATION_MATCH_LIMIT)
        is_inac = mmr_d.get("is_inactive", False)
        rt = get_player_rank_tier(curr_m, is_calibrating=is_cal, is_inactive=is_inac)

        glory_pts = ach_summary.get("total_points", 0)
        gold_c = ach_summary.get("tier3_count", ach_summary.get("gold_count", 0))
        silver_c = ach_summary.get("tier2_count", ach_summary.get("silver_count", 0))
        bronze_c = ach_summary.get("tier1_count", ach_summary.get("bronze_count", 0))
        unlocked_c = ach_summary.get("total_unlocked", 0)

        glory_leaderboard.append({
            "steam_id": sid,
            "name": p_name,
            "avatar_classes": rt.get("avatar_classes", ""),
            "rank_tier": rt,
            "current_mmr": curr_m,
            "glory_points": glory_pts,
            "gold_count": gold_c,
            "silver_count": silver_c,
            "bronze_count": bronze_c,
            "unlocked_count": unlocked_c,
            "total_count": len(ach_list) or 30,
            "completion_pct": round((unlocked_c / max(1, len(ach_list) or 30)) * 100, 1),
            "achievements": ach_list,
            "unlocked_achievements": [a for a in ach_list if a.get("tier", 0) > 0]
        })

    glory_leaderboard.sort(key=lambda x: (x["glory_points"], x["gold_count"], x["silver_count"], x["current_mmr"]), reverse=True)
    for idx, pl in enumerate(glory_leaderboard, start=1):
        pl["glory_rank"] = idx

    achievements_dir = SITE_DIR / "achievements"
    achievements_dir.mkdir(parents=True, exist_ok=True)
    ach_detail_template = env.get_template("achievement_detail.html")

    all_achievements_catalog = []

    for aid, meta in ACHIEVEMENTS_METADATA.items():
        gold_holders = []
        silver_holders = []
        bronze_holders = []
        in_progress = []

        for pl in glory_leaderboard:
            sid = pl["steam_id"]
            p_name = pl["name"]
            curr_m = pl["current_mmr"]
            rt = pl["rank_tier"]
            avatar_cls = pl["avatar_classes"]

            p_ach = next((a for a in pl.get("achievements", []) if a.get("id") == aid), None)
            if not p_ach:
                continue

            tier = p_ach.get("tier", 0)
            prog_val = p_ach.get("progress_val", 0)
            prog_max = p_ach.get("progress_max", 0)
            prog_pct = p_ach.get("progress_pct", 0.0)
            prog_text = p_ach.get("progress_text") or p_ach.get("progress", "")
            desc = p_ach.get("desc", "")
            next_goal = p_ach.get("next_goal", "")

            p_item = {
                "steam_id": sid,
                "name": p_name,
                "avatar_classes": avatar_cls,
                "rank_tier": rt,
                "current_mmr": curr_m,
                "tier": tier,
                "tier_name": p_ach.get("tier_name", ""),
                "progress_val": prog_val,
                "progress_max": prog_max,
                "progress_pct": prog_pct,
                "progress_text": prog_text,
                "desc": desc,
                "next_goal": next_goal,
                "points": p_ach.get("points", 0),
                "stars": p_ach.get("stars", "☆☆☆"),
                "stars_data": p_ach.get("stars_data", [])
            }

            if tier == 3:
                p_item["best_metric"] = "Выполнено на 100% 🥇"
                p_item["matches_completed"] = f"{prog_max} из {prog_max}" if prog_max else "5 из 5"
                gold_holders.append(p_item)
            elif tier == 2:
                p_item["best_metric"] = desc
                p_item["matches_completed"] = prog_text
                silver_holders.append(p_item)
            elif tier == 1:
                p_item["best_metric"] = desc
                p_item["matches_completed"] = prog_text
                bronze_holders.append(p_item)
            else:
                try:
                    remaining_val = max(0, float(prog_max) - float(prog_val))
                    if remaining_val == int(remaining_val):
                        remaining_val = int(remaining_val)
                    unit_str = meta.get("unit", "")
                    p_item["remaining_text"] = f"Осталось: {remaining_val} {unit_str}".strip()
                except Exception:
                    p_item["remaining_text"] = "В процессе выполнения"
                p_item["current_result"] = prog_text or f"{prog_val} / {prog_max}"
                in_progress.append(p_item)

        gold_holders.sort(key=lambda x: x["current_mmr"], reverse=True)
        silver_holders.sort(key=lambda x: x["current_mmr"], reverse=True)
        bronze_holders.sort(key=lambda x: x["current_mmr"], reverse=True)
        in_progress.sort(key=lambda x: (x["progress_pct"], x["current_mmr"]), reverse=True)

        tot_pl = len(glory_leaderboard)
        unlocked_cnt = len(gold_holders) + len(silver_holders) + len(bronze_holders)
        rarity_pct = round((unlocked_cnt / max(1, tot_pl)) * 100, 1)

        ach_data = {
            "id": aid,
            "title": meta["title"],
            "icon": meta["icon"],
            "category": meta["category"],
            "essence": meta["essence"],
            "conditions": meta["conditions"],
            "points": meta["points"],
            "unit": meta.get("unit", "матчей"),
            "unlocked_count": unlocked_cnt,
            "total_players": tot_pl,
            "rarity_pct": rarity_pct,
            "gold_count": len(gold_holders),
            "silver_count": len(silver_holders),
            "bronze_count": len(bronze_holders),
            "in_progress_count": len(in_progress),
            "holders": {
                1: bronze_holders,
                2: silver_holders,
                3: gold_holders
            },
            "desc": meta["essence"]
        }

        all_achievements_catalog.append(ach_data)

        # Генерация отдельной страницы достижения site/achievements/<aid>.html
        safe_dump(
            ach_detail_template.stream(
                active_page="achievements",
                ach=ach_data,
                gold_holders=gold_holders,
                silver_holders=silver_holders,
                bronze_holders=bronze_holders,
                in_progress=in_progress,
                root_path="../",
                css_path="../css/style.css",
                js_path="../js/app.js",
                generated_at=generated_at
            ),
            achievements_dir / f"{aid}.html"
        )

    # Генерация общей страницы Зала славы site/achievements.html
    achievements_template = env.get_template("achievements.html")
    safe_dump(
        achievements_template.stream(
            active_page="achievements",
            css_path="css/style.css",
            js_path="js/app.js",
            root_path="",
            glory_leaderboard=glory_leaderboard,
            all_achievements_catalog=all_achievements_catalog,
            generated_at=generated_at
        ),
        SITE_DIR / "achievements.html"
    )
    logging.info("Сгенерирована страница достижений: site/achievements.html и 30 персональных страниц в site/achievements/")

    # 7. Генерация страницы демок site/demos.html
    demos_template = env.get_template("demos.html")
    safe_dump(
        demos_template.stream(
            active_page="demos",
            css_path="css/style.css",
            js_path="js/app.js",
            root_path="",
            generated_at=generated_at
        ),
        SITE_DIR / "demos.html"
    )
    logging.info("Сгенерирована страница демок: site/demos.html")

    # 7. Генерация страницы дуэлей (Бойцовский клуб) site/compare.html
    h2h_path = DATA_DIR / "head_to_head.json"
    h2h_data = {}
    if h2h_path.exists():
        try:
            with open(h2h_path, "r", encoding="utf-8") as f:
                h2h_data = json.load(f)
        except Exception as e:
            logging.warning(f"Ошибка загрузки head_to_head.json: {e}")

    compare_template = env.get_template("compare.html")
    safe_dump(
        compare_template.stream(
            active_page="compare",
            css_path="css/style.css",
            js_path="js/app.js",
            root_path="",
            h2h_data=h2h_data,
            players=h2h_data.get("players", []),
            generated_at=generated_at
        ),
        SITE_DIR / "compare.html"
    )
    logging.info("Сгенерирована страница дуэлей: site/compare.html")

    # 8. Генерация страницы матчмейкера 5v5 site/matchmaker.html
    matchmaker_template = env.get_template("matchmaker.html")
    safe_dump(
        matchmaker_template.stream(
            active_page="matchmaker",
            css_path="css/style.css",
            js_path="js/app.js",
            root_path="",
            players=leaderboard_players,
            h2h_data=h2h_data,
            generated_at=generated_at
        ),
        SITE_DIR / "matchmaker.html"
    )
    logging.info("Сгенерирована страница матчмейкера: site/matchmaker.html")

    # 9. Генерация страницы тактических ролей site/roles.html
    roles_data = []
    for role_def in ROLES_CATALOG:
        role_id = role_def["role_id"]
        weights = role_def["skills_weights"]
        threshold = role_def["affinity_threshold"]
        factual_names = role_def["factual_names"]

        current_players = []
        potential_candidates = []

        for p in players:
            sid = clean_steamid(p.get("steam_id"))
            if not sid:
                continue

            p_name = clean_name(p.get("name", f"Player_{sid[-4:]}"))
            ratings = p.get("ratings", {})
            metrics = p.get("metrics", {})
            ov = p.get("overall_stats", {})
            mmr_d = p.get("mmr", {})
            curr_m = mmr_d.get("current_mmr", STARTING_MMR)
            is_cal = mmr_d.get("is_calibrating", len(p.get("matches", [])) <= CALIBRATION_MATCH_LIMIT)
            is_inac = mmr_d.get("is_inactive", False)
            rt = get_player_rank_tier(curr_m, is_calibrating=is_cal, is_inactive=is_inac)

            play_style = p.get("play_style", ["Универсал"])
            best_role = p.get("recommendations", {}).get("best_role", "Универсал")
            overall_r = round(ratings.get("Overall Impact", 5.0), 1)
            kd = round(ov.get("kd_ratio", 1.0), 2)
            adr = round(ov.get("avg_adr", 0.0), 1)
            kast = round(ov.get("avg_kast", 0.0), 1)
            tot_m = len(p.get("matches", []))
            affinity = calc_affinity_score(ratings, weights)

            player_obj = {
                "steam_id": sid,
                "name": p_name,
                "avatar_classes": rt.get("avatar_classes", ""),
                "rank_tier": rt,
                "current_mmr": curr_m,
                "total_matches": tot_m,
                "rating": overall_r,
                "kd": kd,
                "adr": adr,
                "kast": kast,
                "affinity_score": affinity,
                "play_style": play_style,
                "best_role": best_role
            }

            # Определяем, является ли игрок фактическим исполнителем данной роли
            is_current = any(fn in play_style for fn in factual_names)
            # Специальная логика для IGL: нет точного фактического маппинга, берём по best_role рекомендации
            if role_id == "igl" and ("Ин-гейм лидер" in best_role or "IGL" in best_role or "Капитан" in best_role):
                is_current = True

            if is_current:
                current_players.append(player_obj)
            elif affinity >= threshold:
                potential_candidates.append(player_obj)

        accent_styles = {
            "amber": {
                "border": "border-amber-500/40",
                "border_active": "border-amber-400",
                "bg_light": "bg-amber-500/10",
                "text": "text-amber-400",
                "glow": "shadow-amber-500/20",
                "badge_bg": "bg-amber-950/60",
                "badge_border": "border-amber-500/30",
                "badge_text": "text-amber-300",
                "bar": "bg-amber-400"
            },
            "red": {
                "border": "border-rose-500/40",
                "border_active": "border-rose-500",
                "bg_light": "bg-rose-500/10",
                "text": "text-rose-400",
                "glow": "shadow-rose-500/20",
                "badge_bg": "bg-rose-950/60",
                "badge_border": "border-rose-500/30",
                "badge_text": "text-rose-300",
                "bar": "bg-rose-500"
            },
            "orange": {
                "border": "border-orange-500/40",
                "border_active": "border-orange-500",
                "bg_light": "bg-orange-500/10",
                "text": "text-orange-400",
                "glow": "shadow-orange-500/20",
                "badge_bg": "bg-orange-950/60",
                "badge_border": "border-orange-500/30",
                "badge_text": "text-orange-300",
                "bar": "bg-orange-500"
            },
            "emerald": {
                "border": "border-emerald-500/40",
                "border_active": "border-emerald-500",
                "bg_light": "bg-emerald-500/10",
                "text": "text-emerald-400",
                "glow": "shadow-emerald-500/20",
                "badge_bg": "bg-emerald-950/60",
                "badge_border": "border-emerald-500/30",
                "badge_text": "text-emerald-300",
                "bar": "bg-emerald-500"
            },
            "blue": {
                "border": "border-sky-500/40",
                "border_active": "border-sky-500",
                "bg_light": "bg-sky-500/10",
                "text": "text-sky-400",
                "glow": "shadow-sky-500/20",
                "badge_bg": "bg-sky-950/60",
                "badge_border": "border-sky-500/30",
                "badge_text": "text-sky-300",
                "bar": "bg-sky-500"
            },
            "purple": {
                "border": "border-purple-500/40",
                "border_active": "border-purple-500",
                "bg_light": "bg-purple-500/10",
                "text": "text-purple-400",
                "glow": "shadow-purple-500/20",
                "badge_bg": "bg-purple-950/60",
                "badge_border": "border-purple-500/30",
                "badge_text": "text-purple-300",
                "bar": "bg-purple-500"
            },
            "cyan": {
                "border": "border-cyan-500/40",
                "border_active": "border-cyan-500",
                "bg_light": "bg-cyan-500/10",
                "text": "text-cyan-400",
                "glow": "shadow-cyan-500/20",
                "badge_bg": "bg-cyan-950/60",
                "badge_border": "border-cyan-500/30",
                "badge_text": "text-cyan-300",
                "bar": "bg-cyan-400"
            },
            "yellow": {
                "border": "border-amber-400/40",
                "border_active": "border-amber-400",
                "bg_light": "bg-amber-400/10",
                "text": "text-amber-300",
                "glow": "shadow-amber-400/20",
                "badge_bg": "bg-amber-950/60",
                "badge_border": "border-amber-400/30",
                "badge_text": "text-amber-200",
                "bar": "bg-amber-400"
            }
        }

        # Сортировка: фактические — по рейтингу, кандидаты — по affinity
        current_players.sort(key=lambda x: (x["affinity_score"], x["rating"], x["current_mmr"]), reverse=True)
        potential_candidates.sort(key=lambda x: (x["affinity_score"], x["rating"]), reverse=True)

        p_count = len(current_players)
        c_count = len(potential_candidates)
        top_cand = potential_candidates[0] if potential_candidates else None

        if p_count == 0:
            roster_status = "deficit"
            status_label = "Дефицит роли"
            status_color = "rose"
        elif p_count in (1, 2):
            roster_status = "optimal"
            status_label = f"{p_count} в основе"
            status_color = "emerald"
        else:
            roster_status = "surplus"
            status_label = f"{p_count} в основе"
            status_color = "amber"

        acc_key = role_def["accent_color"]
        role_style = accent_styles.get(acc_key, accent_styles["amber"])

        roles_data.append({
            "role_id": role_def["role_id"],
            "title": role_def["title"],
            "icon": role_def["icon"],
            "short_title": role_def["short_title"],
            "lore": role_def["lore"],
            "metrics_rules": role_def["metrics_rules"],
            "skills_formula": role_def["skills_formula"],
            "affinity_threshold": threshold,
            "accent_color": acc_key,
            "accent_style": role_style,
            "current_players": current_players,
            "potential_candidates": potential_candidates,
            "player_count": p_count,
            "candidate_count": c_count,
            "roster_status": roster_status,
            "status_label": status_label,
            "status_color": status_color,
            "top_candidate": top_cand
        })

    roster_overview = {
        "total_roles": len(roles_data),
        "covered_roles": sum(1 for r in roles_data if r["player_count"] > 0),
        "deficit_roles": sum(1 for r in roles_data if r["player_count"] == 0),
        "total_active_players": len({p["steam_id"] for r in roles_data for p in r["current_players"]}),
        "total_candidates": sum(r["candidate_count"] for r in roles_data)
    }

    roles_template = env.get_template("roles.html")
    safe_dump(
        roles_template.stream(
            active_page="roles",
            css_path="css/style.css",
            js_path="js/app.js",
            root_path="",
            roles=roles_data,
            roster_overview=roster_overview,
            generated_at=generated_at
        ),
        SITE_DIR / "roles.html"
    )
    logging.info("Сгенерирована страница тактических ролей: site/roles.html")

    logging.info("🔥 Генерация HTML-сайта успешно завершена!")

if __name__ == "__main__":
    generate_site()




