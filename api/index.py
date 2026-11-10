# Vercel serverless entry point: exposes the FastAPI ASGI app for /api/* requests.
# The React frontend is served separately as static files from frontend/dist.
from app.main import app  # noqa: F401
