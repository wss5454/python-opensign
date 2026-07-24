from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.api import api_router
from app.auth import ensure_admin_user
from app.config import ensure_directories, settings
from app.database import init_db
from app.web import web_router
from app.ws import ws_router

BASE_DIR = Path(__file__).resolve().parent


def create_app() -> FastAPI:
    ensure_directories()
    init_db()
    ensure_admin_user()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            f"{settings.app_name} e-signature API. "
            "Manage documents, signers, widgets, and signing sessions. "
            "API routes are open (no cookie/token). Admin login is required only for the web UI. "
            "Connect to WebSocket `/ws` to receive `document.finished` events "
            "(includes `document_id`) when all signers complete a document."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="wallacesign_session",
        same_site="lax",
        https_only=False,
        max_age=60 * 60 * 24 * 7,
    )

    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(api_router)
    app.include_router(ws_router)
    app.include_router(web_router)

    @app.get("/docs-ui")
    def redirect_api_docs():
        return RedirectResponse("/docs")

    return app


app = create_app()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return templates.TemplateResponse(
        "404.html",
        {"request": request, "app_name": settings.app_name},
        status_code=404,
    )
