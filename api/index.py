"""
Vercel serverless entrypoint.

Vercel's Python runtime looks for a module-level `app` (ASGI) object in the
file it builds. The actual app lives in backend/app/main.py as a package
(backend/app/__init__.py exists; backend/ itself is an implicit namespace
package), so we just need the repo root on sys.path before importing it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.main import app  # noqa: E402,F401
