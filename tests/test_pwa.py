"""
PWA installability — manifest, icons, iOS meta tags, and (critically) NO
service worker / no offline caching of anything. Manifest and icons are
public, unauthenticated content (same as a favicon) — no login needed.
"""
import glob
import os
import struct

import pytest

APP_DIR = os.path.join(os.path.dirname(__file__), "..", "app")


def test_manifest_is_served_with_correct_content_type_and_fields(client):
    resp = client.get("/manifest.webmanifest")
    assert resp.status_code == 200
    assert resp.content_type == "application/manifest+json"
    data = resp.get_json()
    assert data["name"] == "Household"
    assert data["display"] == "standalone"
    assert data["start_url"] == "/"
    assert data["theme_color"] == "#0a5"
    icon_sizes = {icon["sizes"] for icon in data["icons"]}
    assert icon_sizes == {"192x192", "512x512"}


def test_manifest_accessible_without_login(client):
    """Manifest/icons must be fetchable before auth — that's how "Add to
    Home Screen" works even from the login screen. `client` here has no
    session cookie set at all (no login() call) — this is a genuinely
    anonymous request, not just an unchecked one."""
    with client.session_transaction() as sess:
        assert "_user_id" not in sess
    resp = client.get("/manifest.webmanifest")
    assert resp.status_code == 200


@pytest.mark.parametrize("size", [192, 512])
def test_icon_accessible_without_login(client, size):
    with client.session_transaction() as sess:
        assert "_user_id" not in sess
    resp = client.get(f"/static/icons/icon-{size}.png")
    assert resp.status_code == 200


def test_manifest_contains_nothing_household_specific(client):
    """The manifest is public — it must never carry a user's email, a fact
    value, or anything else that would identify or expose the household.
    Pin the exact key set so a future addition can't sneak something in
    without this test being updated (and someone noticing why)."""
    data = client.get("/manifest.webmanifest").get_json()
    assert set(data.keys()) == {
        "name", "short_name", "start_url", "display", "background_color",
        "theme_color", "icons",
    }
    for forbidden in ("shannon", "partner", "@", "£", "paye", "pension", "isa"):
        assert forbidden not in str(data).lower()


@pytest.mark.parametrize("size", [192, 512])
def test_icon_is_a_real_png_of_the_right_dimensions(client, size):
    resp = client.get(f"/static/icons/icon-{size}.png")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"
    assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", resp.data[16:24])
    assert (width, height) == (size, size)


def test_base_template_has_pwa_tags():
    with open(os.path.join(APP_DIR, "templates", "base.html")) as f:
        html = f.read()
    assert 'rel="manifest"' in html
    assert 'name="theme-color" content="#0a5"' in html
    assert 'rel="apple-touch-icon"' in html
    assert 'name="apple-mobile-web-app-capable" content="yes"' in html


def test_no_service_worker_registration_anywhere_in_templates():
    for path in glob.glob(os.path.join(APP_DIR, "templates", "**", "*.html"), recursive=True):
        with open(path) as f:
            assert "serviceWorker" not in f.read(), f"found serviceWorker reference in {path}"


def test_no_service_worker_file_exists():
    for name in ("sw.js", "service-worker.js", "serviceworker.js"):
        assert not os.path.exists(os.path.join(APP_DIR, "static", name))


def test_no_javascript_files_in_static_at_all():
    """Belt-and-suspenders: no JS at all means no possible offline-caching
    mechanism, not just no file named sw.js specifically."""
    js_files = glob.glob(os.path.join(APP_DIR, "static", "**", "*.js"), recursive=True)
    assert js_files == []
