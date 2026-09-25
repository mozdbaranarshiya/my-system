import os
import sys

from dotenv import load_dotenv

load_dotenv()

from school_system import create_app, db
from school_system.services import ensure_initial_admin

app = create_app()


def initialize():
    with app.app_context():
        db.create_all()
        ensure_initial_admin()


if __name__ == "__main__":
    initialize()
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0").lower() in {"1", "true", "yes", "on"}
    app.run(host=host, port=port, debug=debug)
