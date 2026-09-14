import os
from pathlib import Path

# Основные директории проекта (динамический корень проекта для Windows и Linux)
BASE_DIR = Path(__file__).resolve().parent.parent
DEMOS_DIR = BASE_DIR / "demos"
DATA_DIR = BASE_DIR / "data"
SITE_DIR = BASE_DIR / "site"
TEMPLATES_DIR = BASE_DIR / "templates"
INSTRUCTION_DIR = BASE_DIR / "instruction"
ROUNDS_INSTRUCTION_PATH = INSTRUCTION_DIR / "rounds.txt"

# Автоматическая загрузка .env файла (если он существует)
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k not in os.environ:
                        os.environ[k] = v
    except Exception:
        pass

# Настройки AI API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AI_PROVIDER = "gemini"  # Может быть "gemini" или "openai"
AI_MODEL = os.getenv("AI_MODEL", "gemini-3.5-flash-lite")

# Настройки FACEIT API
FACEIT_API_KEY = os.getenv("FACEIT_API_KEY", "")
FACEIT_DIR = DATA_DIR / "faceit"
FACEIT_DIR.mkdir(parents=True, exist_ok=True)

# Настройки публикации сайта (GitHub Pages / Хостинг)
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "")

# Словарь имен игроков: Steam ID -> отображаемое имя (заполняется пользователями)
PLAYER_NAMES = {}

PLAYER_ALIASES = {
    # Domino / Dom1no1111 -> mbaliyev
    "76561198834472256": ("76561198686899456", "mbaliyev"),
    "dom1no1111": ("76561198686899456", "mbaliyev"),
    "domino": ("76561198686899456", "mbaliyev"),
    "dom1no": ("76561198686899456", "mbaliyev"),
    # Nay ball -> Saliend (same player, renamed profile)
    "76561198083546368": ("76561198083546367", "Saliend"),
    "nay ball": ("76561198083546367", "Saliend"),
    "saliend": ("76561198083546367", "Saliend"),
    # Float precision variant aliases
    "76561198125968237": ("76561198125968240", "qumashasyl"),
    "76561198885191520": ("76561198885191528", "taksist_3"),
    "76561198243149322": ("76561198243149328", "Rayi"),
    "76561199043039616": ("76561199043039622", "Zanoza59"),
    "76561199438131200": ("76561199438131194", "SGEM_7"),
    "sgem_7": ("76561199438131194", "SGEM_7"),
}

# Нормализованный маппинг канонических игроков (Имя в нижнем регистре -> Канонический Steam ID)
CANONICAL_PLAYERS = {
    "mbaliyev": "76561198686899456",
    "dom1no1111": "76561198686899456",
    "domino": "76561198686899456",
    "alibonya": "76561198431427136",
    "yesk0": "76561198402746928",
    "saliend": "76561198083546367",
    "nay ball": "76561198083546367",
    "folie_1": "76561198100478545",
    "zikayevg": "76561199413542223",
    "altairinthesky": "76561199339730976",
    "oceanmengo": "76561198254267968",
    "k--9": "76561199569491960",
    "resone west": "76561199508661466",
    "azki_1": "76561198234120608",
    "iamresplendent": "76561199478211872",
    "matadorra": "76561199153011360",
    "qumashasyl": "76561198125968240",
    "taksist_3": "76561198885191528",
    "rayi": "76561198243149328",
    "zanoza59": "76561199043039622",
    "chpokers": "76561199808571117",
    "gigabyte_kz": "76561197990475042",
    "__9503": "76561198357586856",
    "c kaifom": "76561198998095904",
    "insta/ne7er0cs": "76561198356069376",
    "darkatom": "76561198068831005",
    "nakama_4": "76561198010867824",
    "sgem_7": "76561199438131194"
}

# Переводы названий позиций на русский сленг (Active Duty карты)
MAP_CALLOUTS = {
    "de_mirage": {
        "mid": "Мид",
        "underpass": "Андерик",
        "connector": "Коннектор",
        "palace": "Ковры",
        "apartments": "Апы",
        "jungle": "Джангл",
        "stairs": "Ступеньки",
        "ticketbox": "Тикет",
        "bench": "Скамейка",
        "catwalk": "Шорт",
        "b_apartments": "Б апы"
    },
    "de_inferno": {
        "banana": "Банан",
        "apartments": "Апы",
        "mid": "Мид",
        "boiler": "Бойлер",
        "pit": "Яма",
        "graveyard": "Кладбище",
        "ruins": "Руины",
        "top_mid": "Топ мид",
        "apps": "Апы"
    },
    "de_dust2": {
        "mid": "Мид",
        "catwalk": "Шорт",
        "long": "Длина",
        "lower tunnels": "Нижняя темка",
        "upper tunnels": "Верхняя темка",
        "pit": "Яма",
        "b_doors": "Б двери",
        "a_doors": "А двери"
    },
    "de_nuke": {
        "outside": "Улица",
        "lobby": "Лобби",
        "ramp": "Рампа",
        "hut": "Будка",
        "secret": "Сикрет",
        "garage": "Гараж",
        "heaven": "Хевен",
        "hell": "Хелл"
    },
    "de_ancient": {
        "mid": "Мид",
        "cave": "Пещера",
        "donut": "Пончик",
        "ruins": "Руины",
        "main": "Мейн",
        "temple": "Храм"
    },
    "de_anubis": {
        "mid": "Мид",
        "water": "Вода",
        "bridge": "Мост",
        "connector": "Коннектор",
        "canal": "Канал",
        "palace": "Дворец",
        "ruins": "Руины"
    },
    "de_vertigo": {
        "mid": "Мид",
        "ramp": "Рампа",
        "stairs": "Лестница",
        "elevator": "Лифт",
        "sandbags": "Мешки",
        "scaffolding": "Леса"
    }
}

# Универсальный словарь переводов игровых зон CS2 (awpy raw -> русский сленг)
COMMON_CALLOUTS = {
    "bombsitea": "Плент A",
    "bombsiteb": "Плент B",
    "snipersnest": "Окно",
    "kitchen": "Маркет / Кухня",
    "market": "Маркет",
    "apartments": "Апарты / Ковры",
    "palace": "Ковры",
    "palacealley": "Выход из ковров",
    "underpass": "Андерик / Метро",
    "connector": "Коннектор",
    "jungle": "Джангл",
    "stairs": "Ступеньки",
    "ticketbox": "Тикет",
    "bench": "Форест / Скамейка",
    "van": "Фургон / Машина",
    "catwalk": "Шорт",
    "short": "Шорт",
    "mid": "Мид",
    "middle": "Мид",
    "topmid": "Топ мид",
    "topofmid": "Топ мид",
    "banana": "Банан",
    "boiler": "Бойлер",
    "pit": "Яма",
    "graveyard": "Кладбище",
    "ruins": "Руины / Гроб",
    "arch": "Арка",
    "speedway": "Библиотека / Ребро",
    "long": "Длина",
    "longdoors": "Коробка / Двери длины",
    "lowertunnels": "Нижняя темка",
    "uppertunnels": "Верхняя темка",
    "tunnels": "Темка",
    "outside": "Улица",
    "lobby": "Лобби",
    "ramp": "Рампа",
    "hut": "Будка",
    "secret": "Сикрет",
    "garage": "Гараж",
    "heaven": "Хевен / Девять",
    "hell": "Хелл",
    "cave": "Пещера",
    "donut": "Пончик",
    "temple": "Храм",
    "main": "Мейн",
    "water": "Вода",
    "bridge": "Мост",
    "canal": "Канал",
    "alley": "Аллея / Шорт",
    "ctspawn": "КТ-Спавн",
    "tspawn": "Т-Спавн"
}

def translate_callout(map_name: str, place_name: str) -> str:
    """Переводит raw-название зоны CS2 из демки в общепринятый русский сленг карты."""
    if not place_name or str(place_name) == "nan" or str(place_name).strip() == "":
        return "Зона карты"
    
    clean_p = str(place_name).strip()
    norm_p = clean_p.lower().replace(" ", "").replace("_", "")
    
    # 1. Поиск по конкретной карте
    map_clean = str(map_name or "").lower()
    if not map_clean.startswith("de_"):
        map_clean = f"de_{map_clean}"
    
    if map_clean in MAP_CALLOUTS:
        for k, v in MAP_CALLOUTS[map_clean].items():
            if k.lower().replace(" ", "").replace("_", "") == norm_p:
                return v
                
    # 2. Поиск по общему словарю CS2
    if norm_p in COMMON_CALLOUTS:
        return COMMON_CALLOUTS[norm_p]
        
    for k, v in COMMON_CALLOUTS.items():
        if k in norm_p:
            return v
            
    return clean_p

# Номера раундов, которые являются пистолетными
PISTOL_ROUNDS = [1, 13]

MAP_DISPLAY_NAMES = {
    "de_mirage": "Mirage",
    "de_inferno": "Inferno",
    "de_dust2": "Dust2",
    "de_ancient": "Ancient",
    "de_anubis": "Anubis",
    "de_nuke": "Nuke",
    "de_vertigo": "Vertigo",
    "de_overpass": "Overpass",
    "de_train": "Train"
}

MAP_ICONS = {
    "de_mirage": "map_icon_de_mirage.svg",
    "de_inferno": "map_icon_de_inferno.svg",
    "de_dust2": "map_icon_de_dust2.svg",
    "de_ancient": "map_icon_de_ancient.svg",
    "de_anubis": "map_icon_de_anubis.svg",
    "de_nuke": "map_icon_de_nuke.svg",
    "de_vertigo": "map_icon_de_vertigo.svg",
    "de_overpass": "map_icon_de_overpass.svg",
    "de_train": "map_icon_de_train.svg"
}

# Константы для порогов рейтинга
RATING_THRESHOLDS = {
    "excellent": 1.2,
    "good": 1.05,
    "average": 0.95,
    "poor": 0.8
}

# Константы непрерывной системы MMR
STARTING_MMR = 1000
BASE_TEAM_DELTA = 15
MAX_IMPACT_MODIFIER = 8
MAX_REGULAR_DELTA = 25
CALIBRATION_MATCH_LIMIT = 5
CALIBRATION_VOLATILITY = 1.5
MAX_CALIBRATION_DELTA = 37
INACTIVITY_DAYS_THRESHOLD = 30

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

def compute_hltv_rating(k: int, d: int, a: int, adr: float, kast: float, fk: int, fd: int, rounds_cnt: int) -> tuple[float, float]:
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

