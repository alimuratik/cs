"""
Модуль генерации аутентичных Faceit Level 1-10 SVG иконок
на основе круговой геометрии с цветными сегментами.
"""
import os
import math
from pathlib import Path

FACEIT_LEVEL_CONFIGS = {
    1:  {"color": "#e2e8f0", "arc_pct": 0.08, "text_color": "#ffffff", "name": "Level 1", "badge": "Level 1"},
    2:  {"color": "#22c55e", "arc_pct": 0.16, "text_color": "#22c55e", "name": "Level 2", "badge": "Level 2"},
    3:  {"color": "#22c55e", "arc_pct": 0.30, "text_color": "#22c55e", "name": "Level 3", "badge": "Level 3"},
    4:  {"color": "#eab308", "arc_pct": 0.38, "text_color": "#eab308", "name": "Level 4", "badge": "Level 4"},
    5:  {"color": "#eab308", "arc_pct": 0.50, "text_color": "#eab308", "name": "Level 5", "badge": "Level 5"},
    6:  {"color": "#eab308", "arc_pct": 0.65, "text_color": "#eab308", "name": "Level 6", "badge": "Level 6"},
    7:  {"color": "#eab308", "arc_pct": 0.80, "text_color": "#eab308", "name": "Level 7", "badge": "Level 7"},
    8:  {"color": "#f97316", "arc_pct": 0.75, "text_color": "#f97316", "name": "Level 8", "badge": "Level 8"},
    9:  {"color": "#f97316", "arc_pct": 0.88, "text_color": "#f97316", "name": "Level 9", "badge": "Level 9"},
    10: {"color": "#ef4444", "arc_pct": 1.00, "text_color": "#ef4444", "name": "Level 10", "badge": "Level 10"},
}

def render_faceit_svg(level: int, size: int = 24, class_name: str = "") -> str:
    """Генерирует чистый inline SVG бейджа Faceit для указанного уровня (0=Unranked/Калибровка, 1-10)."""
    cls_attr = f' class="{class_name}"' if class_name else ""
    r = 11.5

    if level is None or int(level) <= 0:
        # Аутентичный Faceit Unranked значок (пунктирный серый круг со знаком вопроса)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="{size}" height="{size}"{cls_attr} style="vertical-align:middle;display:inline-block;flex-shrink:0;">'
            f'<circle cx="16" cy="16" r="15" fill="#141517" stroke="#2c2e33" stroke-width="1"/>'
            f'<circle cx="16" cy="16" r="{r}" fill="none" stroke="#475569" stroke-width="2.2" stroke-dasharray="4.5 3" />'
            f'<text x="16" y="21" text-anchor="middle" font-family="\'Rajdhani\', \'Inter\', sans-serif" font-weight="900" font-size="14" fill="#94a3b8">?</text>'
            f'</svg>'
        )

    level = max(1, min(10, int(level)))
    cfg = FACEIT_LEVEL_CONFIGS.get(level, FACEIT_LEVEL_CONFIGS[1])
    
    circ = 2 * math.pi * r  # ~72.25
    pct = cfg["arc_pct"]
    dash = round(circ * pct, 2)
    gap = round(circ - dash, 2)
    rot = 120
    
    font_size = 14 if level < 10 else 11
    y_pos = 21 if level < 10 else 20
    
    if pct >= 0.99:
        arc_element = f'<circle cx="16" cy="16" r="{r}" fill="none" stroke="{cfg["color"]}" stroke-width="2.6" />'
    else:
        arc_element = (
            f'<circle cx="16" cy="16" r="{r}" fill="none" stroke="{cfg["color"]}" '
            f'stroke-width="2.6" stroke-dasharray="{dash} {gap}" stroke-linecap="round" '
            f'transform="rotate({rot} 16 16)" />'
        )
        
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="{size}" height="{size}"{cls_attr} style="vertical-align:middle;display:inline-block;flex-shrink:0;">'
        f'<circle cx="16" cy="16" r="15" fill="#141517" stroke="#2c2e33" stroke-width="1"/>'
        f'<circle cx="16" cy="16" r="{r}" fill="none" stroke="#25272c" stroke-width="2.6"/>'
        f'{arc_element}'
        f'<text x="16" y="{y_pos}" text-anchor="middle" font-family="\'Rajdhani\', \'Inter\', sans-serif" font-weight="900" font-size="{font_size}" fill="{cfg["text_color"]}">{level}</text>'
        f'</svg>'
    )

def generate_faceit_svg_files(output_dir: Path | str):
    """Создает файлы level_0.svg ... level_10.svg в переданной директории."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    for lvl in range(0, 11):
        svg_content = render_faceit_svg(lvl, size=32)
        with open(out_path / f"level_{lvl}.svg", "w", encoding="utf-8") as f:
            f.write(svg_content)

