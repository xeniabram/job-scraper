import urllib.parse
from typing import get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st

from job_scraper.exceptions import SourceParsingError
from job_scraper.scraper.justjoinit_scraper import (
    BASE_URL,
    ExperienceLevelLiteral,
    JustJoinItScraper,
    Params,
    WorkplaceLiteral,
    _join_list,
    _salary_range,
)

# Derive valid values directly from the Literal types so there's one source of truth.
EXPERIENCE_LEVELS = list(get_args(get_args(ExperienceLevelLiteral)[0]))
WORKPLACE_VALUES = list(get_args(get_args(WorkplaceLiteral)[0]))


def _parse_qs(url: str) -> dict[str, str]:
    """Parse query string into {key: value}."""
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))


# ── Serializers ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    (["a", "b"],  "a,b"),
    (["x"],       "x"),
    (["a", "b", "c"], "a,b,c"),
])
def test_join_list(inp, expected):
    assert _join_list(inp) == expected


@pytest.mark.parametrize("salary,expected", [
    (10_000, "10000,500000"),
    (5_000,  "5000,500000"),
])
def test_salary_range(salary, expected):
    assert _salary_range(salary) == expected


# ── Params / URL building ──────────────────────────────────────────────────────

def test_url_defaults():
    assert Params().build_listing_url() == f"{BASE_URL}/job-offers/all-locations"


def test_url_no_query_string_when_no_filters():
    assert "?" not in Params().build_listing_url()


def test_url_with_technology():
    assert Params(technology="python").build_listing_url() == f"{BASE_URL}/job-offers/all-locations/python"


def test_url_with_location():
    assert Params(location="remote").build_listing_url() == f"{BASE_URL}/job-offers/remote"


def test_url_with_filters():
    qs = _parse_qs(Params(experience_level=["senior", "mid"], workplace=["hybrid"]).build_listing_url())
    assert set(qs["experience-level"].split(",")) == {"senior", "mid"}
    assert qs["workplace"] == "hybrid"


def test_url_salary_range():
    qs = _parse_qs(Params(salary=10_000).build_listing_url())
    assert qs["salary"] == "10000,500000"


def test_location_defaults_when_empty():
    assert Params(location="").location == "all-locations"


@given(st.lists(st.sampled_from(EXPERIENCE_LEVELS), min_size=1, unique=True))
def test_experience_level_roundtrips(levels):
    qs = _parse_qs(Params(experience_level=levels).build_listing_url())
    assert set(qs["experience-level"].split(",")) == set(levels)


@given(st.lists(st.sampled_from(WORKPLACE_VALUES), min_size=1, unique=True))
def test_workplace_roundtrips(workplace):
    qs = _parse_qs(Params(workplace=workplace).build_listing_url())
    assert set(qs["workplace"].split(",")) == set(workplace)


def test_none_params_absent_from_url():
    """Params left as None must not appear in the query string."""
    qs = _parse_qs(Params().build_listing_url())
    assert "experience-level" not in qs
    assert "workplace" not in qs
    assert "salary" not in qs


# ── HTML parsing ───────────────────────────────────────────────────────────────

def test_extract_job_data_missing_json_ld():
    scraper = JustJoinItScraper.__new__(JustJoinItScraper)
    with pytest.raises(SourceParsingError):
        scraper._extract_job_data("https://justjoin.it/job/fake", "<html></html>")
