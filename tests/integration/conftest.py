import sentry_sdk

from job_scraper.config.settings import settings


def pytest_configure(config):
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=0.0,
    )
