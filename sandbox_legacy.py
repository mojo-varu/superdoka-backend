"""
app/api/v1/endpoints/demo.py

Serves the capability demo UI at GET /demo.
No auth — this is a public demo endpoint.
"""
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()
_DEMO_HTML = Path(__file__).parents[4] / "static" / "demo.html"


@router.get("/demo", include_in_schema=False)
async def demo_ui():
    if _DEMO_HTML.exists():
        return HTMLResponse(_DEMO_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>demo.html not found</h1>", status_code=404)
