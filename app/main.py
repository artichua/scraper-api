from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.endpoints import router
import logging

# Configuración central del logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scraper-inteligente")

app = FastAPI(title="AI Scraper", version="6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
