"""
Модуль генерации соревновательных 3D-векторных SVG медальонов для системы достижений Зала Славы
на основе аутентичной металлической геометрии монет (Gold / Silver / Bronze).
"""

def render_achievement_badge_svg(tier: int, icon: str, size: int = 44, class_name: str = "") -> str:
    """
    Генерирует 3D векторный SVG-медальон награды (из концепта Зала Славы):
    - Внешний металлический безель (ободок) с градиентом
    - Внутренний темный диск монеты с радиальной глубиной и монетной насечкой
    - Центральная иконка с объемной тенью
    - Векторные звезды мастерства у основания монеты (3 для золота, 2 для серебра, 1 для бронзы)
    """
    try:
        tier = int(tier)
    except (ValueError, TypeError):
        tier = 1

    safe_icon = str(icon).strip() if icon else "🎖️"
    cls_attr = f' class="{class_name}"' if class_name else ' class="shrink-0 drop-shadow-md"'

    if tier >= 3:
        # 🥇 Золото: 3 полигональных звезды, богатое золотое сияние
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{size}" height="{size}"{cls_attr}>'
            f'<defs>'
            f'<linearGradient id="goldRim" x1="0%" y1="0%" x2="100%" y2="100%">'
            f'<stop offset="0%" stop-color="#fef08a"/>'
            f'<stop offset="50%" stop-color="#eab308"/>'
            f'<stop offset="100%" stop-color="#92400e"/>'
            f'</linearGradient>'
            f'<radialGradient id="goldCore" cx="50%" cy="40%" r="60%">'
            f'<stop offset="0%" stop-color="#1e293b"/>'
            f'<stop offset="100%" stop-color="#090d16"/>'
            f'</radialGradient>'
            f'</defs>'
            f'<circle cx="32" cy="30" r="28" fill="#b45309"/>'
            f'<circle cx="32" cy="30" r="26.5" fill="url(#goldRim)"/>'
            f'<circle cx="32" cy="30" r="24.5" fill="#0f172a" opacity="0.3"/>'
            f'<circle cx="32" cy="30" r="22" fill="url(#goldCore)"/>'
            f'<circle cx="32" cy="30" r="23" fill="none" stroke="#fef08a" stroke-width="1.5" stroke-dasharray="3 2" opacity="0.8"/>'
            f'<text x="32" y="36" text-anchor="middle" font-size="20" style="filter: drop-shadow(0 2px 4px rgba(0,0,0,0.6));">{safe_icon}</text>'
            f'<polygon points="24,53 25.5,56 29,56 26,58 27.5,61 24,59 20.5,61 22,58 19,56 22.5,56" fill="#fef08a" stroke="#78350f" stroke-width="0.5"/>'
            f'<polygon points="32,51 33.8,54.5 38,54.5 34.5,57 36,60.5 32,58 28,60.5 29.5,57 26,54.5 30.2,54.5" fill="#fef08a" stroke="#78350f" stroke-width="0.5"/>'
            f'<polygon points="40,53 41.5,56 45,56 42,58 43.5,61 40,59 36.5,61 38,58 35,56 38.5,56" fill="#fef08a" stroke="#78350f" stroke-width="0.5"/>'
            f'</svg>'
        )
    elif tier == 2:
        # 🥈 Серебро: 2 полигональных звезды, холодный платиновый блеск
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{size}" height="{size}"{cls_attr}>'
            f'<defs>'
            f'<linearGradient id="silverRim" x1="0%" y1="0%" x2="100%" y2="100%">'
            f'<stop offset="0%" stop-color="#ffffff"/>'
            f'<stop offset="50%" stop-color="#cbd5e1"/>'
            f'<stop offset="100%" stop-color="#475569"/>'
            f'</linearGradient>'
            f'<radialGradient id="silverCore" cx="50%" cy="40%" r="60%">'
            f'<stop offset="0%" stop-color="#1e293b"/>'
            f'<stop offset="100%" stop-color="#0b1120"/>'
            f'</radialGradient>'
            f'</defs>'
            f'<circle cx="32" cy="30" r="28" fill="#475569"/>'
            f'<circle cx="32" cy="30" r="26.5" fill="url(#silverRim)"/>'
            f'<circle cx="32" cy="30" r="24.5" fill="#0f172a" opacity="0.3"/>'
            f'<circle cx="32" cy="30" r="22" fill="url(#silverCore)"/>'
            f'<circle cx="32" cy="30" r="23" fill="none" stroke="#e2e8f0" stroke-width="1.5" stroke-dasharray="3 2" opacity="0.7"/>'
            f'<text x="32" y="36" text-anchor="middle" font-size="20" style="filter: drop-shadow(0 2px 4px rgba(0,0,0,0.6));">{safe_icon}</text>'
            f'<polygon points="26,52 27.5,55 31,55 28,57 29.5,60 26,58 22.5,60 24,57 21,55 24.5,55" fill="#ffffff" stroke="#334155" stroke-width="0.5"/>'
            f'<polygon points="38,52 39.5,55 43,55 40,57 41.5,60 38,58 34.5,60 36,57 33,55 36.5,55" fill="#ffffff" stroke="#334155" stroke-width="0.5"/>'
            f'</svg>'
        )
    elif tier == 1:
        # 🥉 Бронза: 1 полигональная звезда, сдержанная благородная темная бронза
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{size}" height="{size}"{cls_attr}>'
            f'<defs>'
            f'<linearGradient id="bronzeRim" x1="0%" y1="0%" x2="100%" y2="100%">'
            f'<stop offset="0%" stop-color="#fed7aa"/>'
            f'<stop offset="50%" stop-color="#ea580c"/>'
            f'<stop offset="100%" stop-color="#7c2d12"/>'
            f'</linearGradient>'
            f'<radialGradient id="bronzeCore" cx="50%" cy="40%" r="60%">'
            f'<stop offset="0%" stop-color="#1c1917"/>'
            f'<stop offset="100%" stop-color="#0c0a09"/>'
            f'</radialGradient>'
            f'</defs>'
            f'<circle cx="32" cy="30" r="28" fill="#78350f"/>'
            f'<circle cx="32" cy="30" r="26.5" fill="url(#bronzeRim)"/>'
            f'<circle cx="32" cy="30" r="24.5" fill="#0f172a" opacity="0.3"/>'
            f'<circle cx="32" cy="30" r="22" fill="url(#bronzeCore)"/>'
            f'<circle cx="32" cy="30" r="23" fill="none" stroke="#fdba74" stroke-width="1" opacity="0.6"/>'
            f'<text x="32" y="36" text-anchor="middle" font-size="20" style="filter: drop-shadow(0 2px 4px rgba(0,0,0,0.6));">{safe_icon}</text>'
            f'<polygon points="32,52 33.5,55 37,55 34,57 35.5,60 32,58 28.5,60 30,57 27,55 30.5,55" fill="#ffedd5" stroke="#431407" stroke-width="0.5"/>'
            f'</svg>'
        )
    else:
        # 🔒 Заблокировано
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{size}" height="{size}"{cls_attr} style="opacity:0.4;filter:grayscale(1);">'
            f'<circle cx="32" cy="30" r="28" fill="#1e293b"/>'
            f'<circle cx="32" cy="30" r="26.5" fill="#334155"/>'
            f'<circle cx="32" cy="30" r="24.5" fill="#0f172a" opacity="0.5"/>'
            f'<circle cx="32" cy="30" r="22" fill="#090d16"/>'
            f'<circle cx="32" cy="30" r="23" fill="none" stroke="#475569" stroke-width="1.5" stroke-dasharray="3 2" opacity="0.5"/>'
            f'<text x="32" y="36" text-anchor="middle" font-size="20" style="filter: drop-shadow(0 2px 4px rgba(0,0,0,0.6));">🔒</text>'
            f'</svg>'
        )
