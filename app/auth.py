"""Optional password gate — `APP_PASSWORD` set ho tabhi lagta hai.

App public URL par jaate hi koi bhi search chala kar tumhare Apify credits aur
OpenRouter tokens jala sakta hai. HTTP Basic auth sabse chhota tala hai: browser
khud prompt dikha deta hai, frontend me ek line badalne ki zaroorat nahi.

Ye raw ASGI middleware hai, `BaseHTTPMiddleware` nahi — wo response ko wrap karta
hai aur `/api/search` ka lamba NDJSON stream (1-3 minute) usme atak sakta hai.
"""
import base64
import hmac

from starlette.responses import JSONResponse, PlainTextResponse


class BasicAuth:
    def __init__(self, app, username: str, password: str):
        self.app = app
        self._expected = base64.b64encode(f"{username}:{password}".encode()).decode()

    def _ok(self, scope) -> bool:
        header = dict(scope.get("headers") or {}).get(b"authorization", b"").decode()
        if not header.startswith("Basic "):
            return False
        # compare_digest taaki galat password ka jawab hamesha ek jitna time le.
        return hmac.compare_digest(header[6:].strip(), self._expected)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self._ok(scope):
            await self.app(scope, receive, send)
            return

        # Host ka uptime check bina password ke pass hona chahiye, par usme
        # keys/DB ki koi detail nahi jaani chahiye.
        if scope.get("path") == "/api/health":
            await JSONResponse({"ok": True})(scope, receive, send)
            return

        response = PlainTextResponse(
            "Password chahiye.",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Hiring Agent"'},
        )
        await response(scope, receive, send)
