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

# Ручной маппинг профилей Faceit (Steam ID или никнейм в нижнем регистре -> Faceit Nickname или URL профиля)
# Используется, если Steam ID из демки не привязан к Faceit CS2 напрямую, профиль из эпохи CS:GO, или игрок играет со смурфа
FACEIT_CUSTOM_PLAYERS = {
    "alibonya": "ALIBONYA",
    "76561198431427139": "ALIBONYA",
    "76561198431427136": "ALIBONYA",
    "mbaliyev": "mbaliyev",
    "76561198686899454": "mbaliyev",
    "76561198686899456": "mbaliyev",
    "oceanmengo": "oceanskyi",
    "oceanskyi": "oceanskyi",
    "76561198254267961": "oceanskyi",
    "76561198254267968": "oceanskyi",
    "matadorra": "bemyskyy",
    "bemyskyy": "bemyskyy",
    "76561199153011354": "bemyskyy",
    "76561199153011360": "bemyskyy",
    "altairinthesky": "altairinthesky",
    "76561199339730968": "altairinthesky",
    "76561199339730976": "altairinthesky",
    "yesk0": "Yesk0",
    "76561198402746932": "Yesk0",
    "76561198402746928": "Yesk0",
    "c kaifom": "caelum_plenum",
    "76561198998095898": "caelum_plenum",
    "76561198998095904": "caelum_plenum",
}

# Настройки публикации сайта (GitHub Pages / Хостинг)
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "")

# Словарь имен игроков: Steam ID -> отображаемое имя (заполняется пользователями)
PLAYER_NAMES = {}

PLAYER_ALIASES = {
    # Domino / Dom1no1111 -> mbaliyev
    "76561198834472256": ("76561198686899454", "mbaliyev"),
    "dom1no1111": ("76561198686899454", "mbaliyev"),
    "domino": ("76561198686899454", "mbaliyev"),
    "dom1no": ("76561198686899454", "mbaliyev"),
    # Nay ball -> Saliend (same player, renamed profile)
    "76561198083546368": ("76561198083546367", "Saliend"),
    "nay ball": ("76561198083546367", "Saliend"),
    "saliend": ("76561198083546367", "Saliend"),
    # Маппинг всех float-округлений на истинные 64-битные Steam ID
    "76561198254267968": ("76561198254267961", "Oceanmengo"),
    "76561199153011360": ("76561199153011354", "matadorra"),
    "76561198431427136": ("76561198431427139", "ALIBONYA"),
    "76561198686899456": ("76561198686899454", "mbaliyev"),
    "76561198402746928": ("76561198402746932", "Yesk0"),
    "76561199339730976": ("76561199339730968", "altairinthesky"),
    "76561198998095904": ("76561198998095898", "c kaifom"),
    "76561198356069376": ("76561198356069369", "insta/Ne7er0cs"),
    "76561198010867824": ("76561198010867827", "Nakama_4"),
    "76561198243149328": ("76561198243149322", "Rayi"),
    "76561198125968240": ("76561198125968237", "qumashasyl"),
    "76561198885191520": ("76561198885191528", "taksist_3"),
    "76561199043039616": ("76561199043039622", "Zanoza59"),
    "76561199438131200": ("76561199438131194", "SGEM_7"),
    "sgem_7": ("76561199438131194", "SGEM_7"),
}

# Нормализованный маппинг канонических игроков (Имя в нижнем регистре -> Истинный Steam ID)
CANONICAL_PLAYERS = {
    "mbaliyev": "76561198686899454",
    "dom1no1111": "76561198686899454",
    "domino": "76561198686899454",
    "alibonya": "76561198431427139",
    "yesk0": "76561198402746932",
    "saliend": "76561198083546367",
    "nay ball": "76561198083546367",
    "folie_1": "76561198100478545",
    "zikayevg": "76561199413542223",
    "altairinthesky": "76561199339730968",
    "oceanmengo": "76561198254267961",
    "k--9": "76561199569491960",
    "resone west": "76561199508661466",
    "azki_1": "76561198234120608",
    "iamresplendent": "76561199478211872",
    "matadorra": "76561199153011354",
    "qumashasyl": "76561198125968237",
    "taksist_3": "76561198885191528",
    "rayi": "76561198243149322",
    "zanoza59": "76561199043039622",
    "chpokers": "76561199808571117",
    "gigabyte_kz": "76561197990475042",
    "__9503": "76561198357586856",
    "c kaifom": "76561198998095898",
    "insta/ne7er0cs": "76561198356069369",
    "darkatom": "76561198068831005",
    "nakama_4": "76561198010867827",
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
    "de_train": "Train",
    "de_cache": "Cache"
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
    "de_train": "map_icon_de_train.svg",
    "de_cache": "map_icon_de_cache.svg"
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

# Официальный реестр 30 соревновательных киберспортивных достижений (Часть А: 20 навыковых, Часть Б: 10 хайлайтов)
ACHIEVEMENTS_METADATA = {
    # 1. Aim
    "aim_onetap": {
        "id": "aim_onetap",
        "title": "One-Tap Хирург",
        "icon": "🎯",
        "category": "Aim (Стрельба)",
        "skill_code": "Aim",
        "essence": "Филигранная стрельба в голову (HS%) в соревновательных матчах при солидном количестве фрагов. Оценивает хладнокровие, точность первого патрона и способность стабильно ставить хедшоты на протяжении всей карты.",
        "conditions": {
            1: "1 матч с HS% >= 50.0% (при мин. 15 фрагах)",
            2: "3 матча с HS% >= 55.0% (при мин. 15 фрагах)",
            3: "5 матчей с HS% >= 60.0% (при мин. 15 фрагах)"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    "aim_damage_roller": {
        "id": "aim_damage_roller",
        "title": "Огневой каток",
        "icon": "💥",
        "category": "Aim (Стрельба)",
        "skill_code": "Aim",
        "essence": "Нанесение колоссального среднего урона за раунд (ADR). Доказывает огневую мощь и способность стабильно продавливать оборону или атаку противника на длинной дистанции раундов.",
        "conditions": {
            1: "1 матч со средним уроном ADR >= 85.0",
            2: "3 матча со средним уроном ADR >= 95.0",
            3: "5 матчей со средним уроном ADR >= 105.0"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    # 2. Positioning
    "pos_ghost": {
        "id": "pos_ghost",
        "title": "Призрак выживания",
        "icon": "👻",
        "category": "Positioning (Позиционирование)",
        "skill_code": "Positioning",
        "essence": "Мастерство позиционной живучести: высокая доля раундов с сохранением жизни (Survival Rate >= 40-50%) или минимальным числом смертей (<= 10 за полную карту). Оценивает умение не отдаваться попусту.",
        "conditions": {
            1: "1 матч с выживаемостью >= 40.0% (или <= 10 смертей)",
            2: "3 матча с выживаемостью >= 45.0% (или <= 10 смертей)",
            3: "5 матчей с выживаемостью >= 50.0% (или <= 10 смертей)"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    "pos_anchor": {
        "id": "pos_anchor",
        "title": "Непробиваемый якорь",
        "icon": "🛡️",
        "category": "Positioning (Позиционирование)",
        "skill_code": "Positioning",
        "essence": "Выступление в роли надежного опорника плента или ключевой позиции. Требует высокого индивидуального рейтинга позиционирования и стабильно положительного K/D.",
        "conditions": {
            1: "1 матч с Positioning rating >= 7.0 (при K/D >= 1.10)",
            2: "3 матча с Positioning rating >= 7.5 (при K/D >= 1.10)",
            3: "5 матчей с Positioning rating >= 8.0 (при K/D >= 1.10)"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    # 3. Utility
    "util_flash_duo": {
        "id": "util_flash_duo",
        "title": "Светошумовой дирижёр",
        "icon": "⚡",
        "category": "Utility (Гранаты)",
        "skill_code": "Utility",
        "essence": "Командная синергия светошумовых гранат. Оценивает количество флеш-ассистов (Flash Assists), когда ослепленные враги мгновенно уничтожаются напарниками.",
        "conditions": {
            1: "1 матч с >= 3 флеш-ассистами",
            2: "3 матча с >= 4 флеш-ассистами",
            3: "5 матчей с >= 5 флеш-ассистами"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    "util_artillery": {
        "id": "util_artillery",
        "title": "Тяжёлая артиллерия",
        "icon": "💣",
        "category": "Utility (Гранаты)",
        "skill_code": "Utility",
        "essence": "Разрушительный урон боевыми гранатами и коктейлями Молотова. Оценивает знание таймингов, позиций раскидки и умение срезать HP врагам до непосредственного стрелкового контакта.",
        "conditions": {
            1: "1 матч с >= 120 HP урона гранатами",
            2: "3 матча с >= 180 HP урона гранатами",
            3: "5 матчей с >= 250 HP урона гранатами"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    # 4. Game Sense
    "gs_iron_curtain": {
        "id": "gs_iron_curtain",
        "title": "Железный занавес",
        "icon": "🧠",
        "category": "Game Sense (Игровое мышление)",
        "skill_code": "Game Sense",
        "essence": "Ультимативный показатель надежности KAST% (убийство, ассист, выживание или размен). Оценивает, насколько регулярно игрок вносит полезный импакт в раунд и не выпадает из командной структуры.",
        "conditions": {
            1: "1 матч с KAST >= 75.0%",
            2: "3 матча с KAST >= 80.0%",
            3: "5 матчей с элитным KAST >= 85.0%"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    "gs_sixth_sense": {
        "id": "gs_sixth_sense",
        "title": "Шестое чувство",
        "icon": "👁️",
        "category": "Game Sense (Игровое мышление)",
        "skill_code": "Game Sense",
        "essence": "Тактическое чтение игры: убийства сквозь плотную дымовую завесу и уничтожение врагов будучи вслепую по звуку и позиционным таймингам.",
        "conditions": {
            1: "1 матч с >= 3 тактическими фрагами (в смок / вслепую)",
            2: "3 матча с >= 3 тактическими фрагами",
            3: "5 матчей с >= 3 тактическими фрагами"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    # 5. Entry
    "entry_thunder": {
        "id": "entry_thunder",
        "title": "Громовержец опенингов",
        "icon": "⚡",
        "category": "Entry (Первые дуэли)",
        "skill_code": "Entry",
        "essence": "Чистый перевес в первых дуэлях раунда (First Kills - First Deaths). Создает численное преимущество для команды на первых секундах раунда.",
        "conditions": {
            1: "1 матч с балансом первых дуэлей FK-FD >= +2 (мин. 3 FK)",
            2: "3 матча с балансом первых дуэлей FK-FD >= +3 (мин. 3 FK)",
            3: "5 матчей с балансом первых дуэлей FK-FD >= +4 (мин. 3 FK)"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    "entry_battering_ram": {
        "id": "entry_battering_ram",
        "title": "Стенобитное орудие",
        "icon": "🦏",
        "category": "Entry (Первые дуэли)",
        "skill_code": "Entry",
        "essence": "Высочайший процент побед в первых дуэлях раунда (Opening Duel Winrate) при солидном количестве попыток входа.",
        "conditions": {
            1: "1 матч с винрейтом энтри >= 55.0% (при мин. 4 дуэлях)",
            2: "3 матча с винрейтом энтри >= 62.0% (при мин. 4 дуэлях)",
            3: "5 матчей с винрейтом энтри >= 70.0% (при мин. 4 дуэлях)"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    # 6. Trading
    "trade_blood_revenge": {
        "id": "trade_blood_revenge",
        "title": "Кровная месть",
        "icon": "🤝",
        "category": "Trading (Размены)",
        "skill_code": "Trading",
        "essence": "Мгновенное возмездие за гибель товарищей по команде. Оценивает скорость реакции и умение быстро наказывать оппонента в течение 5 секунд после смерти напарника.",
        "conditions": {
            1: "1 матч с >= 3 разменами (trades)",
            2: "3 матча с >= 4 разменами",
            3: "5 матчей с >= 5 разменами"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    "trade_wingman": {
        "id": "trade_wingman",
        "title": "Идеальный напарник",
        "icon": "👥",
        "category": "Trading (Размены)",
        "skill_code": "Trading",
        "essence": "Доля разменных фрагов в общем объеме убийств (Trade Rate %). Отражает постоянное нахождение рядом с напарниками и слаженную парную работу.",
        "conditions": {
            1: "1 матч с долей разменов (Trade Rate) >= 25.0% (при мин. 10 фрагах)",
            2: "3 матча с долей разменов >= 32.0% (при мин. 10 фрагах)",
            3: "5 матчей с долей разменов >= 40.0% (при мин. 10 фрагах)"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    # 7. Clutch
    "clutch_minister": {
        "id": "clutch_minister",
        "title": "Министр клатчей",
        "icon": "⏱️",
        "category": "Clutch (Клатчи)",
        "skill_code": "Clutch",
        "essence": "Серийные победы в напряженных ситуациях 1vX, когда вся ответственность за судьбу раунда ложится на плечи одного игрока.",
        "conditions": {
            1: "1 матч с 2+ выигранными клатчами",
            2: "3 матча с 2+ выигранными клатчами",
            3: "5 матчей с 2+ выигранными клатчами (или 1 матч с 3+ клатчами 🥇)"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    "clutch_steel_nerves": {
        "id": "clutch_steel_nerves",
        "title": "Стальные нервы",
        "icon": "🧊",
        "category": "Clutch (Клатчи)",
        "skill_code": "Clutch",
        "essence": "Хладнокровие и высочайший процент выигрыша клатчей (Clutch Winrate %) на дистанции матчей.",
        "conditions": {
            1: "1 матч со 100% успехом в клатчах (мин. 2 из 2) или WR >= 30%",
            2: "Винрейт в клатчах >= 35.0% (при мин. 6 попытках)",
            3: "Винрейт в клатчах >= 50.0% (при мин. 10 попытках)"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    # 8. Discipline
    "disc_zen": {
        "id": "disc_zen",
        "title": "Дзен спецназа",
        "icon": "🧘",
        "category": "Discipline (Дисциплина)",
        "skill_code": "Discipline",
        "essence": "Идеальная игровая дисциплина: завершение полного матча (16+ раундов) без единой первой смерти (0 First Deaths). Демонстрирует осторожность и выдержку.",
        "conditions": {
            1: "1 матч без единой первой смерти (0 FD, мин. 16 раундов)",
            2: "3 матча без единой первой смерти (0 FD, мин. 16 раундов)",
            3: "5 матчей без единой первой смерти (0 FD, мин. 16 раундов)"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    "disc_frugal_fighter": {
        "id": "disc_frugal_fighter",
        "title": "Бережливый боец",
        "icon": "🎒",
        "category": "Discipline (Дисциплина)",
        "skill_code": "Discipline",
        "essence": "Умение сохранять девайс и броню в заведомо безнадежных раундах, предотвращая экономический кризис команды в следующем раунде.",
        "conditions": {
            1: "2 сохранения девайса в заведомо проигранных раундах (Saves)",
            2: "5 сохранений девайса в заведомо проигранных раундах (Saves)",
            3: "10 сохранений девайса в заведомо проигранных раундах (Saves)"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "сейвов"
    },
    # 9. Economy
    "eco_saboteur": {
        "id": "eco_saboteur",
        "title": "Экономический диверсант",
        "icon": "💰",
        "category": "Economy (Экономика)",
        "skill_code": "Economy",
        "essence": "Превосходство против фулл-баев оппонентов. Способность находить фраги и выигрывать дуэли против соперников с лучшим оружием и утилитой.",
        "conditions": {
            1: "1 матч с K/D >= 1.15 против полного закупа оппонентов",
            2: "3 матча с K/D >= 1.30 против полного закупа оппонентов",
            3: "5 матчей с K/D >= 1.50 против полного закупа оппонентов"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    "eco_pistol_maestro": {
        "id": "eco_pistol_maestro",
        "title": "Пистолетный маэстро",
        "icon": "🔫",
        "category": "Economy (Экономика)",
        "skill_code": "Economy",
        "essence": "Доминирование в фундаментальных пистолетных раундах (раунды 1 и 13), определяющих экономический фундамент обеих половин матча.",
        "conditions": {
            1: "1 матч с >= 3 фрагами в пистолетных раундах (1 и 13)",
            2: "3 матча с >= 3 фрагами в пистолетных раундах (1 и 13)",
            3: "5 матчей с >= 3 фрагами (или 1 матч с 5+ фрагами 🥇)"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    # 10. Overall Impact
    "impact_star_carry": {
        "id": "impact_star_carry",
        "title": "Звездный керри",
        "icon": "🌟",
        "category": "Overall Impact (Импакт)",
        "skill_code": "Overall Impact",
        "essence": "Элитный индивидуальный соревновательный рейтинг HLTV 2.0. Подтверждает способность вести команду за собой и переламывать ход игры.",
        "conditions": {
            1: "1 матч с соревновательным рейтингом HLTV 2.0 >= 1.35",
            2: "3 матча с соревновательным рейтингом HLTV 2.0 >= 1.45",
            3: "5 матчей с элитным рейтингом HLTV 2.0 >= 1.60"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    "impact_bombardier": {
        "id": "impact_bombardier",
        "title": "Бомбардир (25+ фрагов)",
        "icon": "🎩",
        "category": "Overall Impact (Импакт)",
        "skill_code": "Overall Impact",
        "essence": "Гроссмейстерская результативность: 25+ и 30+ фрагов за одну карту. Свидетельствует о неудержимой огневой мощи игрока.",
        "conditions": {
            1: "1 матч с 25+ фрагами на карте",
            2: "3 матча с 25+ фрагами на карте",
            3: "1 матч с 30-бомбой (30+ фрагов) или 5 матчей с 25+ фрагами 🥇"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    # 11. Highlight & Fun
    "fun_humiliation": {
        "id": "fun_humiliation",
        "title": "Мастер унижений",
        "icon": "🔪",
        "category": "Highlight & Fun (Хайлайты)",
        "skill_code": "Highlight",
        "essence": "Дерзкие фраги с ножа или электрошокера Zeus x27 в соревновательных матчах. Наносит максимальный психологический урон противнику.",
        "conditions": {
            1: "5 фрагов с ножа или Zeus суммарно",
            2: "10 фрагов с ножа или Zeus суммарно",
            3: "Дабл-килл (2+ фрага с ножа/Zeus) за одну карту"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "фрагов"
    },
    "fun_taser_therapy": {
        "id": "fun_taser_therapy",
        "title": "Шоковая терапия",
        "icon": "⚡",
        "category": "Highlight & Fun (Хайлайты)",
        "skill_code": "Highlight",
        "essence": "Убийства из контактного электрошокера Zeus x27 на поджимах в упоре и неожиданных засадах.",
        "conditions": {
            1: "1 фраг из электрошокера Zeus x27",
            2: "5 фрагов из электрошокера Zeus x27",
            3: "10 фрагов из электрошокера Zeus x27"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "фрагов"
    },
    "fun_wild_west": {
        "id": "fun_wild_west",
        "title": "Шериф Дикого Запада",
        "icon": "🤠",
        "category": "Highlight & Fun (Хайлайты)",
        "skill_code": "Highlight",
        "essence": "Смертоносные хедшоты из карманной пушки Desert Eagle или фраги из тяжелого Revolver R8.",
        "conditions": {
            1: "10 хедшотов из Desert Eagle или фрагов из Revolver",
            2: "20 хедшотов из Desert Eagle или фрагов из Revolver",
            3: "30 хедшотов из Desert Eagle или фрагов из Revolver"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "фрагов"
    },
    "fun_ninja_defuse": {
        "id": "fun_ninja_defuse",
        "title": "Ниндзя-сапер",
        "icon": "🥷",
        "category": "Highlight & Fun (Хайлайты)",
        "skill_code": "Highlight",
        "essence": "Хладнокровное разминирование бомбы под носом у живых террористов, выигрывающее раунд в защите.",
        "conditions": {
            1: "1 победный раунд с разминированием бомбы",
            2: "3 победных раунда с разминированием бомбы",
            3: "5 победных раундов с разминированием бомбы"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "дефьюзов"
    },
    "fun_doorbell_shotgun": {
        "id": "fun_doorbell_shotgun",
        "title": "Дверной звонок",
        "icon": "🚪",
        "category": "Highlight & Fun (Хайлайты)",
        "skill_code": "Highlight",
        "essence": "Встреча гостей в упор из тяжелых дробовиков (XM1014, MAG-7, Nova, Sawed-off) с получением солидного денежного бонуса.",
        "conditions": {
            1: "5 фрагов из дробовиков",
            2: "15 фрагов из дробовиков",
            3: "30 фрагов из дробовиков"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "фрагов"
    },
    "fun_blind_rage": {
        "id": "fun_blind_rage",
        "title": "Слепая ярость",
        "icon": "🕶️",
        "category": "Highlight & Fun (Хайлайты)",
        "skill_code": "Highlight",
        "essence": "Убийства беспомощных врагов, ослепленных флешкой напарника (Assisted Flash). Показатель командной синхронизации.",
        "conditions": {
            1: "1 фраг при содействии световой гранаты тиммейта",
            2: "3 фрага при содействии световой гранаты тиммейта",
            3: "6 фрагов при содействии световой гранаты тиммейта"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "фрагов"
    },
    "fun_wallbang_god": {
        "id": "fun_wallbang_god",
        "title": "ВХ без читов",
        "icon": "🧱",
        "category": "Highlight & Fun (Хайлайты)",
        "skill_code": "Highlight",
        "essence": "Прострелы сквозь деревянные двери, тонкие стены или сквозь сплошной дым на основе префаеров и интуиции.",
        "conditions": {
            1: "2 прострела сквозь стены или плотный дым",
            2: "5 прострелов сквозь стены или плотный дым",
            3: "10 прострелов сквозь стены или плотный дым"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "прострелов"
    },
    "fun_terminator_ace": {
        "id": "fun_terminator_ace",
        "title": "Терминатор (ACE!)",
        "icon": "💀",
        "category": "Highlight & Fun (Хайлайты)",
        "skill_code": "Highlight",
        "essence": "Величайший сольный хайлайт Counter-Strike — Эйс (ACE), уничтожение всей вражеской команды из 5 бойцов в одиночку за один раунд.",
        "conditions": {
            1: "1 эйс (уничтожение всех 5 соперников за раунд)",
            2: "2 эйса (уничтожение всех 5 соперников за раунд)",
            3: "4 эйса (уничтожение всех 5 соперников за раунд)"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "эйсов"
    },
    "fun_nemesis_hunter": {
        "id": "fun_nemesis_hunter",
        "title": "Кровная вендетта (Nemesis Hunter)",
        "icon": "🩸",
        "category": "Highlight & Fun (Хайлайты)",
        "skill_code": "Highlight",
        "essence": "Принципиальное доминирование над своим главным соперником (Nemesis): 5+ убийств заклятого врага в рамках одной карты.",
        "conditions": {
            1: "1 матч с 5+ убийствами своего Nemesis",
            2: "3 матча с 5+ убийствами своего Nemesis",
            3: "6 матчей с 5+ убийствами своего Nemesis"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "матчей"
    },
    "fun_comeback_master": {
        "id": "fun_comeback_master",
        "title": "Мастер камбэка",
        "icon": "🌪️",
        "category": "Highlight & Fun (Хайлайты)",
        "skill_code": "Highlight",
        "essence": "Волевой соревновательный дух: победы в матчах с камбэками после отставания, в овертаймах или на тоненького со счетом 13:11.",
        "conditions": {
            1: "1 волевая победа (камбэк, овертайм или разрыв <= 3)",
            2: "2 волевые победы (камбэк, овертайм или разрыв <= 3)",
            3: "4 волевые победы (камбэк, овертайм или разрыв <= 3)"
        },
        "points": {1: 100, 2: 250, 3: 500},
        "unit": "побед"
    }
}

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

