"""FastAPI main application entry point."""
import sys
import os

# Add parent directory to path so imports work when running `python main.py` from app folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import platform
import logging
import asyncio

from app.config import get_settings
from app.database import create_tables
from app.routers import auth, users, posts, stories, chat, notifications
from app.websocket.chat import router as ws_router
from app.utils.tasks import run_periodic_cleanup

# Get settings first
settings = get_settings()

# Configure logging - single handler to avoid duplicates
log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.StreamHandler(),  # Console only
    ]
)

# Silence noisy loggers
logging.getLogger("watchfiles").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)  # Reduce SQL noise

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    # Startup
    logger.info("Starting up Nexa backend...")
    
    # Create database tables
    await create_tables()
    logger.info("Database tables created")
    
    # Create uploads directory
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    logger.info(f"Uploads directory: {settings.UPLOAD_DIR}")
    
    # Start background tasks
    cleanup_task = asyncio.create_task(run_periodic_cleanup())
    logger.info("Background tasks started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="Nexa - A modern social media platform API",
    version=settings.VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if settings.IS_PROD else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for uploads
if not os.path.exists(settings.UPLOAD_DIR):
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# Include routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(posts.router)
app.include_router(stories.router)
app.include_router(chat.router)
app.include_router(notifications.router)
app.include_router(ws_router)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "name": settings.APP_NAME,
        "status": "running",
        "version": settings.VERSION
    }


@app.get("/api/health")
async def health_check():
    """API health check."""
    return {"status": "healthy"}


if __name__ == "__main__":
    logger.info(f"Starting {settings.APP_NAME} on port {settings.PORT}")
    
    if platform.system() != "Linux" and settings.IS_PROD:
        # Use Gunicorn for production on non-Linux systems
        try:
            from gunicorn.app.wsgiapp import WSGIApplication

            class StandaloneApplication(WSGIApplication):
                def __init__(self, app_uri, options=None):
                    self.options = options or {}
                    self.app_uri = app_uri
                    super().__init__()

                def load_config(self):
                    config = {
                        key: value
                        for key, value in self.options.items()
                        if key in self.cfg.settings and value is not None
                    }
                    for key, value in config.items():
                        self.cfg.set(key.lower(), value)

            options = {
                "bind": f"0.0.0.0:{settings.PORT}",
                "workers": 8,
                "threads": 2,
                "worker_class": "uvicorn.workers.UvicornH11Worker",
                "timeout": 120,
                "keepalive": 10,
                "max_requests": 1000,
                "max_requests_jitter": 200,
                "graceful_timeout": 30,
                "limit_request_line": 8190,
            }
            logger.info("Starting with Gunicorn...")
            StandaloneApplication("app.main:app", options).run()
        except ImportError:
            logger.warning("Gunicorn not available, falling back to uvicorn")
            uvicorn.run(
                app="app.main:app",
                host="0.0.0.0",
                port=settings.PORT,
                reload=not settings.IS_PROD,
            )
    else:
        # Use uvicorn for development with auto-reload
        uvicorn.run(
            app="app.main:app",
            host="0.0.0.0",
            port=settings.PORT,
            reload=not settings.IS_PROD,
            reload_excludes=["*.log", "*.db", "uploads/*", "__pycache__/*"],
            log_level="info" if not settings.IS_PROD else "warning",
        )

