import urllib.parse
from typing import get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st

from job_scraper.exceptions import SourceParsingError
from job_scraper.scraper.nofluff_scraper import (
    CategoryLiteral,
    NoFluffScraper,
    Params,
    SeniorityLiteral,
    _join_items,
)

# Derive valid values directly from the Literal types so there's one source of truth.
SENIORITY_VALUES = list(get_args(get_args(SeniorityLiteral)[0]))
CATEGORY_VALUES = list(get_args(get_args(CategoryLiteral)[0]))


def _parse_criteria(url: str) -> dict[str, set[str]]:
    """Decode and parse the criteria query param into {key: {values}}."""
    raw = urllib.parse.unquote(urllib.parse.urlparse(url).query)
    criteria = raw.removeprefix("criteria=")
    result = {}
    for part in criteria.split(" "):
        k, _, v = part.partition("=")
        result[k] = set(v.split(","))
    return result


# ── _join_items serializer ─────────────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    ({"a", "b"},   {"a", "b"}),
    (["x", "y"],   {"x", "y"}),
    ("raw",        {"raw"}),
    ({"solo"},     {"solo"}),
])
def test_join_items(inp, expected):
    assert set(_join_items(inp).split(",")) == expected


# ── Params / URL building ──────────────────────────────────────────────────────

def test_url_defaults():
    criteria = _parse_criteria(Params().build_listing_url())
    assert criteria == {"city": {"praca-zdalna"}}


def test_url_all_params_present():
    criteria = _parse_criteria(
        Params(category={"backend"}, seniority={"senior"}, requirement={"Python"}).build_listing_url()
    )
    assert criteria["category"] == {"backend"}
    assert criteria["seniority"] == {"senior"}
    assert criteria["requirement"] == {"Python"}


@given(st.sets(st.sampled_from(SENIORITY_VALUES), min_size=1))
def test_seniority_roundtrips(seniority):
    criteria = _parse_criteria(Params(seniority=seniority).build_listing_url())
    assert criteria["seniority"] == seniority


@given(st.sets(st.sampled_from(CATEGORY_VALUES), min_size=1))
def test_category_roundtrips(category):
    criteria = _parse_criteria(Params(category=category).build_listing_url())
    assert criteria["category"] == category


def test_none_params_absent_from_url():
    """Params left as None must not appear in the criteria string."""
    decoded = urllib.parse.unquote(Params().build_listing_url())
    assert "requirement=" not in decoded
    assert "employment=" not in decoded


# ── HTML parsing ───────────────────────────────────────────────────────────────

def test_extract_job_data_empty_page():
    scraper = NoFluffScraper.__new__(NoFluffScraper)
    with pytest.raises(SourceParsingError):
        scraper._extract_job_data("https://nofluffjobs.com/pl/job/fake", "<html></html>")
    