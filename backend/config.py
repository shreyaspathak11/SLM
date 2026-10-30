"""Centralized application configuration loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(PROJECT_ROOT / "backend" / "analytics.db"))).resolve()
MODEL_DIR = Path(os.getenv("MODEL_DIR", str(PROJECT_ROOT / "model"))).resolve()

MAX_QUERY_ROWS = 5000
QUERY_TIMEOUT_SECONDS = 5.0

WANDB_API_KEY = os.getenv("WANDB_API_KEY")
WANDB_PROJECT = os.getenv("WANDB_PROJECT", "Text-to-SQL")
