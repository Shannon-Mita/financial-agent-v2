"""Local dev entrypoint. Render runs gunicorn (see Procfile) instead."""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
