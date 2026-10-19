"""WSGI entry point for production-style hosting."""

# AI-use disclosure: ChatGPT assisted with the optional deployment entry point.
# The project author should understand the Flask application factory it invokes.
from app import create_app

app = create_app()
