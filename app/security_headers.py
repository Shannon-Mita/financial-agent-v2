"""
Security response headers applied to every response, plus Cache-Control:
no-store while a session is authenticated (household financial data must
never be cached by the browser, a shared device, or an intermediate proxy).

CSP is strict (no 'unsafe-inline' anywhere) because there is no JS in this
app at all (see the PWA tests asserting zero .js files) and every inline
style attribute was moved into app.css — a strict policy costs nothing here
and blocks the entire class of injected-script/injected-style XSS outright.
"""
from flask_login import current_user

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self'; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def init_app(app):
    @app.after_request
    def _add_security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = CSP
        # current_user is always available via Flask-Login's request-bound
        # proxy, even for routes with no @login_required — checking it here
        # (rather than per-view) means every page a signed-in user happens to
        # be looking at is covered, including ones added later with no
        # explicit opt-in required.
        if current_user.is_authenticated:
            resp.headers["Cache-Control"] = "no-store"
        return resp
