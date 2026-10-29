"""
Installable-app plumbing only — a web app manifest and icons so the phone's
"Add to Home Screen" produces a proper standalone app icon. Deliberately NO
service worker: no offline caching of anything, authenticated pages least of
all. The manifest and icons are public, unauthenticated static-ish content
(same as any favicon), served before login — nothing household-specific
lives in them.
"""
from flask import Blueprint, jsonify

bp = Blueprint("pwa", __name__)

THEME_COLOR = "#0a5"  # matches app.css's button/accent green exactly


@bp.route("/manifest.webmanifest")
def manifest():
    resp = jsonify({
        "name": "Household",
        "short_name": "Household",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#fafafa",  # matches app.css's body background
        "theme_color": THEME_COLOR,
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    })
    resp.mimetype = "application/manifest+json"
    return resp
