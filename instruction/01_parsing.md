# Спецификация и регламент парсинга демок CS2 (01_parsing.md)

## 📌 Назначение модуля
Модуль `scripts/parse_demos.py` отвечает за автоматическое обнаружение, синтаксический анализ и извлечение структурированных игровых событий из бинарных файлов демок Counter-Strike 2 (`.dem`), формируемых сервером.

---

## 🛠 Технологический стек парсинга
- **Парсер**: Библиотека `awpy` (версия `>= 2.0`)
- **Обработка данных**: `Polars` и `Pandas`
- **Сериализация**: JSON (`data/matches/`, `data/players_db.json`) и Apache Parquet (`data/ticks/`)

---

## 📁 Структура входных и выходных файлов

```text
demos/
└── DDMMYYYY/                    # Папка игрового дня (например, 10072026)
    ├── match1.dem
    └── match2.dem

data/
├── registry.json               # Реестр уже обработанных файлов демок
├── players_db.json             # Глобальная база истории всех игроков
├── matches/
│   └── {match_id}.json         # Извлеченные события матча
└── ticks/
    └── {match_id}_ticks.parquet # Пространственно-временные тики игроков
```

---

## 🔑 Критические правила обработки данных

### 1. Санитизация и дедупликация Steam ID
В библиотеке `awpy` и Polars Steam ID 64-бит иногда могут считываться как тип `float64` (превращаясь в научную нотацию вроде `7.65611989980959e+16`).
**СТРОГОЕ ПРАВИЛО**: Все идентификаторы Steam ID обязательно пропускаются через функцию нормализации:
```python
def clean_steamid(val) -> str:
    if val is None or val == "" or str(val).lower() in ("nan", "none", "0"):
        return ""
    try:
        # Удаление дробной части от float-представления
        return str(int(float(str(val).strip())))
    except (ValueError, TypeError):
        return str(val).strip()
```
Один физический игрок всегда имеет ровно один постоянный `clean_steamid`.

### 2. Идентификатор матча (`match_id`)
Формируется детерминированно:
`{date_folder}_{map_shortname}_{demo_name_sanitized}` (например: `10072026_ancient_game1`).

### 3. Реестр обработанных демок (`data/registry.json`)
Чтобы избежать повторного дорогостоящего парсинга уже разобранных файлов, скрипт сверяется с `registry.json`:
```json
{
  "parsed_demos": {
    "10072026/match1.dem": {
      "match_id": "10072026_ancient_game1",
      "parsed_at": "2026-07-10T22:30:00",
      "map": "de_ancient",
      "rounds": 23
    }
  }
}
```
Флаг CLI `--force` принудительно игнорирует реестр и пересобирает базу заново.

---

## 📊 Извлекаемые сущности матча (`data/matches/{match_id}.json`)

Каждый JSON-файл матча содержит исчерпывающий срез данных:
1. **Header**: Карта (`de_ancient`), счет команд (`13:10`), длительность, дата сессии.
2. **Players (10 игроков)**:
   - `steam_id`, `name`, `team` (team1 / team2).
   - Базовые показатели: `kills`, `deaths`, `assists`, `headshot_pct`, `adr`, `kast`.
   - Специальные показатели: `first_kills`, `first_deaths`, `clutches_won`, `clutches_lost`, `utility_damage`, `flash_assists`, `trades_given`, `trades_received`.
   - Использованное оружие: распределение фрагов по типам (`ak47`, `m4a1_silencer`, `awp` и др.).
3. **Rounds Timeline**:
   - Номер раунда (1..N).
   - Победитель раунда и тип победы (`ct_killed`, `t_killed`, `bomb_defused`, `target_bombed`, `time_ran_out`).
   - Экономическая классификация команд (Team Equipment Value: Pistol, Full Buy, Force Buy, Semi-Eco, Full Eco).
   - Лента событий (Kill Feed) с таймстампами тиков и локациями.
4. **Damages & Grenades**:
   - Точные цифры нанесенного урона гранатами (HE, коктейли Молотова/инферно).
   - Ослепления союзников и соперников.

---

## ⚡ Оптимизация производительности (Memory & I/O)
- Данные тиков (`ticks`) могут занимать до 200–500 МБ в JSON. Они сохраняются **исключительно** в формате `parquet` с компрессией `zstd` / `snappy` в директорию `data/ticks/`.
- Модули `awpy` и `polars` импортируются **лениво** (lazy import) только при вызове этапа `--stage parse` или `--stage all`, что позволяет другим модулям запускаться за доли секунды без оверхеда.
