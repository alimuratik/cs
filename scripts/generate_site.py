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

        formatted_rounds.append({
            "number": idx,
            "winner": w,
            "winning_team": r.get("winning_team", "team1" if w == "CT" else "team2"),
            "win_type": win_type,
            "win_icon": icon,
            "ct_team_name": ct_t_name,
            "t_team_name": t_t_name,
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

    # Экономика (заглушка графиков)
    round_nums = list(range(1, len(formatted_rounds) + 1))
    economy_chart = {
        "labels": round_nums,
        "team1": [4200 + (i % 3) * 2000 for i in round_nums],
        "team2": [3800 + ((i + 1) % 4) * 1800 for i in round_nums]
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
        "ai_analysis": format_round_analysis(m.get("ai_analysis", "")),
        "summary_analysis": format_coach_summary(m.get("summary_analysis", "")),
        "recommendations": m.get("recommendations", [])
    }

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
        
        # Двухуровневая подпись для Chart.js (Матч X, 📅 DD.MM) для объединения в игровые дни
        labels.append([f"Матч {idx} ({map_n})", f"📅 {date_short}"])
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

    role_text = raw_recs.get("best_role", "Универсал")

    return {
        "steam_id": p.get("steam_id"),
        "name": clean_name(p.get("name")),
        "rank_tier": get_player_rank_tier(curr_mmr, is_calibrating=is_calibrating, is_inactive=is_inactive),
        "rating": round(ratings.get("Overall Impact", 5.0), 1),
        "ratings": radar_values,
        "ratings_dict": ratings_dict,
        "roles": roles,
        "total_matches": len(matches),
        "mmr": {
            "current_mmr": curr_mmr,
            "peak_mmr": peak_mmr,
            "last_delta": last_delta,
            "last_delta_text": f"{last_delta:+d}" if last_delta != 0 else "0",
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
            "role": role_text
        },
        "session_progress": p.get("session_progress"),
        "map_performance": p.get("map_performance", {}),
        "archetype": p.get("archetype", {}),
        "momentum": p.get("momentum", {}),
        "connections": p.get("connections", {}),
        "achievements": p.get("achievements", []),
        "ai_analysis": p.get("ai_analysis", ""),
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
            "last_delta": last_delta,
            "last_delta_text": f"{last_delta:+d}" if last_delta != 0 else "0",
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

    # 1. Генерация index.html
    index_template = env.get_template("index.html")
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
        top_gainers=top_gainers,
        cooling_down=cooling_down,
        generated_at=generated_at
    ).dump(str(SITE_DIR / "index.html"), encoding="utf-8")
    logging.info("Сгенерирована главная страница: site/index.html")

    # 2. Генерация страниц матчей matches/{match_id}.html
    match_template = env.get_template("match.html")
    for m in matches:
        match_id = m.get("match_id")
        formatted_m = format_match_data(m)
        match_template.stream(
            active_page="match",
            css_path="../css/style.css",
            js_path="../js/app.js",
            root_path="../",
            match=formatted_m,
            score1=formatted_m.get("score1", 0),
            score2=formatted_m.get("score2", 0),
            generated_at=generated_at
        ).dump(str(SITE_DIR / "matches" / f"{match_id}.html"), encoding="utf-8")
    logging.info(f"Сгенерированы страницы для {len(matches)} матчей")

    # 3. Генерация страниц игроков players/{steam_id}.html
    player_template = env.get_template("player.html")
    for p in players:
        sid = clean_steamid(p.get("steam_id"))
        if not sid:
            continue
        formatted_p = format_player_data(p)
        player_template.stream(
            active_page="player",
            css_path="../css/style.css",
            js_path="../js/app.js",
            root_path="../",
            player=formatted_p,
            generated_at=generated_at
        ).dump(str(SITE_DIR / "players" / f"{sid}.html"), encoding="utf-8")
    logging.info(f"Сгенерированы страницы для {len(players)} игроков")

    # 4. Генерация страниц сессий sessions/{date}.html
    session_template = env.get_template("session.html")
    for formatted_s in formatted_sessions:
        s_date = formatted_s.get("date")
        if not s_date:
            continue
        session_template.stream(
            active_page="session",
            css_path="../css/style.css",
            js_path="../js/app.js",
            root_path="../",
            session=formatted_s,
            generated_at=generated_at
        ).dump(str(SITE_DIR / "sessions" / f"{s_date}.html"), encoding="utf-8")
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
    skills_template.stream(
        active_page="skills",
        css_path="css/style.css",
        js_path="js/app.js",
        root_path="",
        skills_data=skills_data,
        generated_at=generated_at
    ).dump(str(SITE_DIR / "skills.html"), encoding="utf-8")
    logging.info("Сгенерирована страница навыков: site/skills.html")

    # 6. Генерация страницы демок site/demos.html
    demos_template = env.get_template("demos.html")
    demos_template.stream(
        active_page="demos",
        css_path="css/style.css",
        js_path="js/app.js",
        root_path="",
        generated_at=generated_at
    ).dump(str(SITE_DIR / "demos.html"), encoding="utf-8")
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
    compare_template.stream(
        active_page="compare",
        css_path="css/style.css",
        js_path="js/app.js",
        root_path="",
        h2h_data=h2h_data,
        players=h2h_data.get("players", []),
        generated_at=generated_at
    ).dump(str(SITE_DIR / "compare.html"), encoding="utf-8")
    logging.info("Сгенерирована страница дуэлей: site/compare.html")

    # 8. Генерация страницы матчмейкера 5v5 site/matchmaker.html
    matchmaker_template = env.get_template("matchmaker.html")
    matchmaker_template.stream(
        active_page="matchmaker",
        css_path="css/style.css",
        js_path="js/app.js",
        root_path="",
        players=leaderboard_players,
        h2h_data=h2h_data,
        generated_at=generated_at
    ).dump(str(SITE_DIR / "matchmaker.html"), encoding="utf-8")
    logging.info("Сгенерирована страница матчмейкера: site/matchmaker.html")

    logging.info("🔥 Генерация HTML-сайта успешно завершена!")

if __name__ == "__main__":
    generate_site()




