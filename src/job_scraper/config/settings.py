"""Application settings and configuration."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScraperConfig(BaseModel):
    session_limit_per_board: int
    fetch_interval: int


class CvSection(BaseModel):
    about_me: str = ""
    keywords: str = ""


class CvOptimizationConfig(BaseModel):
    en: CvSection = Field(default_factory=CvSection)
    pl: CvSection = Field(default_factory=CvSection)


class Config(BaseModel):
    search: dict[str, list[dict[str, Any]]]
    requirements: dict
    scraper: ScraperConfig
    cv_optimization: CvOptimizationConfig

    @field_validator("search", mode="before")
    @classmethod
    def listify_search_values(cls, v: Any) -> Any:
        if isinstance(v, dict):
            for key, value in v.items():
                if isinstance(value, dict):
                    v[key] = [value]
        return v


class Settings(BaseSettings):
    """Application settings loaded from environment and config files."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # OpenAI configuration
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_model: str = Field(default="gpt-4o-mini", description="OpenAI model to use")

    # Sentry
    sentry_dsn: str = Field(default="", description="Sentry DSN — empty string disables Sentry")
    sentry_environment: str = Field(default="development", description="Sentry environment tag (e.g. production, development)")

    # Paths
    saved_jobs_dir: Path
    config_file: Path = Field(default=Path("config.yaml"), description="Path to config file")
    data_dir: Path = Field(default=Path("data"), description="Directory for output data")
    logs_dir: Path = Field(default=Path("logs"), description="Directory for log files")

    def load_config(self) -> Config:
        """Load additional configuration from YAML file."""
        if not self.config_file.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_file}")

        with open(self.config_file) as f:
            data = yaml.safe_load(f)
            return Config.model_validate(data)


settings = Settings()  # type: ignore
