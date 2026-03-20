# dashboard/auth.py — Аутентификация дашборда по ключу
#
# Доступ: /dashboard?key=SECRET → cookie, дальше ключ не нужен.

import os

from aiohttp import web

DASHBOARD_KEY = os.getenv("DASHBOARD_KEY", "")
COOKIE_NAME = "dashboard_key"
COOKIE_MAX_AGE = 86400 * 30  # 30 дней


def check_auth(request: web.Request) -> bool:
    """Проверяет аутентификацию через параметр ?key= или cookie."""
    if not DASHBOARD_KEY:
        return False

    key_param = request.query.get("key", "")
    if key_param == DASHBOARD_KEY:
        return True

    cookie_val = request.cookies.get(COOKIE_NAME, "")
    return cookie_val == DASHBOARD_KEY


def set_auth_cookie(response: web.Response) -> None:
    """Устанавливает cookie после успешной аутентификации."""
    if DASHBOARD_KEY:
        response.set_cookie(
            COOKIE_NAME,
            DASHBOARD_KEY,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="Lax",
        )
