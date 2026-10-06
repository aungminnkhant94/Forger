from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
REPORT_HISTORY_DIR = REPORTS_DIR / "history"
TEMPLATES_DIR = BASE_DIR / "templates"

BOOKMARKS_RAW_PATH = DATA_DIR / "bookmarks_raw.json"
SEEN_BOOKMARKS_PATH = DATA_DIR / "seen_bookmarks.json"
ANALYSIS_RESULTS_PATH = DATA_DIR / "analysis_results.json"
LATEST_REPORT_PATH = REPORTS_DIR / "latest_report.html"
REPORT_TEMPLATE_PATH = TEMPLATES_DIR / "report.html.j2"


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    project_name: str
    pipeline_stage: str
    x_bookmarks_source_file: str | None
    x_api_base_url: str
    x_user_access_token: str | None
    x_user_id: str | None
    x_max_results: int
    x_max_pages: int
    x_user_agent: str


def get_settings() -> Settings:
    return Settings(
        project_name="RolloForge",
        pipeline_stage=os.getenv("PIPELINE_STAGE", "idea_validation"),
        x_bookmarks_source_file=os.getenv("X_BOOKMARKS_SOURCE_FILE") or None,
        x_api_base_url=os.getenv("X_API_BASE_URL", "https://api.x.com/2").rstrip("/"),
        x_user_access_token=os.getenv("X_USER_ACCESS_TOKEN") or None,
        x_user_id=os.getenv("X_USER_ID") or None,
        x_max_results=max(5, min(100, _int_env("X_MAX_RESULTS", 100))),
        x_max_pages=max(1, _int_env("X_MAX_PAGES", 50)),
        x_user_agent=os.getenv(
            "X_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        ),
    )