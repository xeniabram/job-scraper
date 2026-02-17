"""Application settings and configuration."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment and config files."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # Ollama configuration
    ollama_host: str = Field(default="http://localhost:11434", description="Ollama API host")
    ollama_model: str = Field(default="llama3.2:latest", description="Ollama model to use")

    # Scraper settings
    daily_job_limit: int = Field(default=100, description="Maximum jobs to view per day")
    view_duration_seconds: int = Field(default=20, description="Time to view each job posting")
    headless: bool = Field(default=False, description="Run browser in headless mode")
    mock_mode: bool = Field(default=False, description="Use mock data instead of real scraping")

    # Paths
    config_file: Path = Field(default=Path("config.yaml"), description="Path to config file")
    data_dir: Path = Field(default=Path("data"), description="Directory for output data")
    logs_dir: Path = Field(default=Path("logs"), description="Directory for log files")

    def load_config(self) -> dict[str, Any]:
        """Load additional configuration from YAML file."""
        if not self.config_file.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_file}")

        with open(self.config_file) as f:
            return yaml.safe_load(f)


settings = Settings()  # type: ignore
