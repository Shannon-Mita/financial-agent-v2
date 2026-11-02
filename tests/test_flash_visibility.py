"""
A2: flash messages must be impossible to miss after the anchor scroll —
a sticky/fixed banner at the top of the viewport, AND the same message
shown inside the specific fact's card (the one the anchor scrolls to),
since the top banner can end up out of the way of where the user's eye
actually lands.
"""
import os
import re

from app.store import PostgresFactStore
from app.vendor_path import ensure_on_path

ensure_on_path()
from facts_layer import Fact, Source, Unit  # noqa: E402

TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def token(resp):
    m = TOKEN_RE.search(resp.data.decode())
    assert m
    return m.group(1)


def test_app_css_makes_the_flash_banner_fixed_to_the_viewport():
    css_path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "app.css")
    with open(css_path) as f:
        css = f.read()
    assert ".flashes" in css
    assert "position: fixed" in css or "position:fixed" in css


def _read_app_css():
    css_path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "app.css")
    with open(css_path) as f:
        return f.read()


def test_success_flash_has_a_css_only_fade_out_animation():
    """CSP forbids inline styles/scripts — the fade must be a CSS
    @keyframes animation applied via a class, nothing inline."""
    css = _read_app_css()
    assert "@keyframes" in css
    assert re.search(r"\.flash\.success\s*\{[^}]*animation:\s*\S*\s*2s", css, re.S)


def test_success_flash_fade_animation_ends_with_pointer_events_none():
    """Once faded, the fixed top banner must not keep intercepting clicks
    meant for the nav underneath it."""
    css = _read_app_css()
    keyframes_match = re.search(r"@keyframes\s+[\w-]+\s*\{(.*?)\}\s*\}", css, re.S)
    assert keyframes_match, "expected a @keyframes block"
    assert "pointer-events: none" in keyframes_match.group(0) or "pointer-events:none" in keyframes_match.group(0)
    assert "opacity: 0" in keyframes_match.group(0) or "opacity:0" in keyframes_match.group(0)


def test_error_flash_has_no_fade_animation():
    """Error banners persist until navigation — no animation at all."""
    css = _read_app_css()
    error_rule = re.search(r"\.flash\.error\s*\{([^}]*)\}", css, re.S)
    assert error_rule, "expected a .flash.error rule"
    assert "animation" not in error_rule.group(1)


def test_no_inline_script_tags_in_any_template():
    import glob

    templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    for path in glob.glob(os.path.join(templates_dir, "**", "*.html"), recursive=True):
        with open(path) as f:
            assert "<script" not in f.read(), f"inline <script> found in {path}"


def test_update_success_message_appears_inside_the_facts_own_card(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("property.main.mortgage_balance", 375000, Unit.GBP, Source.USER_STATED, "mortgage"),
        owner="joint", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/property.main.mortgage_balance/update",
        data={"value": "381150.09", "next": "/", "csrf_token": token(page)},
    )
    assert resp.status_code == 303
    followed = client.get(resp.headers["Location"])
    body = followed.data.decode()

    # Appears at the top (the global flashes block)...
    top_block = body.split("</nav>")[1].split("fact-property.main.mortgage_balance")[0]
    assert "Saved" in top_block

    # ...AND again inside this specific fact's card.
    card_start = body.find('id="fact-property.main.mortgage_balance"')
    assert card_start != -1
    card_end = body.find("</div>", body.find("</div>", body.find("</div>", card_start) + 1) + 1)
    card_html = body[card_start:card_end]
    assert "Saved" in card_html


def test_confirm_success_message_appears_inside_the_facts_own_card(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/income.shannon.paye_salary/confirm",
        data={"next": "/", "csrf_token": token(page)},
    )
    assert resp.status_code == 303
    followed = client.get(resp.headers["Location"])
    body = followed.data.decode()

    card_start = body.find('id="fact-income.shannon.paye_salary"')
    assert card_start != -1
    card_end = body.find("</div>", body.find("</div>", body.find("</div>", card_start) + 1) + 1)
    card_html = body[card_start:card_end]
    assert "Confirmed" in card_html


def test_error_message_appears_inside_the_facts_own_card_too(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("property.main.mortgage_balance", 375000, Unit.GBP, Source.USER_STATED, "mortgage"),
        owner="joint", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/property.main.mortgage_balance/update",
        data={"value": "not-a-number", "next": "/", "csrf_token": token(page)},
    )
    followed = client.get(resp.headers["Location"])
    body = followed.data.decode()

    card_start = body.find('id="fact-property.main.mortgage_balance"')
    card_end = body.find("</div>", body.find("</div>", body.find("</div>", card_start) + 1) + 1)
    card_html = body[card_start:card_end]
    assert "isn&#39;t a valid value" in card_html or "isn't a valid value" in card_html


def test_unrelated_facts_card_does_not_show_someone_elses_flash(client, pg_conn, owner_user_id):
    store = PostgresFactStore(pg_conn)
    store.set(
        Fact.create("property.main.mortgage_balance", 375000, Unit.GBP, Source.USER_STATED, "mortgage"),
        owner="joint", entered_by_user_id=owner_user_id,
    )
    store.set(
        Fact.create("income.shannon.paye_salary", 55000, Unit.GBP_PER_YEAR, Source.USER_STATED, "income"),
        owner="shannon", entered_by_user_id=owner_user_id,
    )
    login(client, owner_user_id)
    page = client.get("/")
    resp = client.post(
        "/facts/property.main.mortgage_balance/update",
        data={"value": "381150.09", "next": "/", "csrf_token": token(page)},
    )
    followed = client.get(resp.headers["Location"])
    body = followed.data.decode()

    card_start = body.find('id="fact-income.shannon.paye_salary"')
    card_end = body.find("</div>", body.find("</div>", body.find("</div>", card_start) + 1) + 1)
    card_html = body[card_start:card_end]
    assert "Saved" not in card_html
