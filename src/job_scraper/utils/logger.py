"""Logging configuration."""
import sys

import sentry_sdk
from loguru import logger

from job_scraper.config.settings import settings


def setup_logger(log_level: str = "INFO") -> None:
    logger.remove()

    # Console / journalctl
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
        level=log_level,
        colorize=True,
    )

    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
        )

        def sentry_sink(message):
            if message.record["exception"]:
                sentry_sdk.capture_exception(message.record["exception"].value)
            else:
                with sentry_sdk.new_scope() as scope:
                    scope.set_extra("name", message.record["name"])
                    scope.set_extra("line", message.record["line"])
                    sentry_sdk.capture_message(message.record["message"], level="error", scope=scope)
        logger.add(sentry_sink, level="ERROR")

    logger.debug("Logger initialized")