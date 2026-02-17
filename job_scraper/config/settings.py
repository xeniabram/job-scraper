"""Application settings and configuration."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScraperConfig(BaseModel):
    daily_limit: int
    fetch_interval: int

class Config(BaseModel):
    search: dict
    requirements: dict
    scraper: ScraperConfig
    output: dict


class Settings(BaseSettings):
    """Application settings loaded from environment and config files."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # Ollama configuration
    ollama_host: str = Field(default="http://localhost:11434", description="Ollama API host")
    ollama_model: str = Field(default="llama3.2:latest", description="Ollama model to use")

    # Paths
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
