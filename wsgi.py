"""WSGI entry point for production-style hosting and Vercel's public demo."""

# AI-use disclosure: ChatGPT assisted with the optional deployment entry point.
# The project author should understand the Flask application factory it invokes.
from __future__ import annotations

import os
from pathlib import Path

if os.environ.get("VERCEL") == "1":
    # Vercel functions have a writable temporary directory but no durable local
    # disk. Use only fictional records and disable all write requests in public mode.
    demo_database = Path("/tmp/warungwise-demo.db")
    os.environ["WARUNGWISE_DATABASE"] = str(demo_database)
    os.environ["WARUNGWISE_DEMO_READ_ONLY"] = "true"

    from seed_demo import seed_demo_database

    seed_demo_database(demo_database)

from app import create_app

app = create_app()
