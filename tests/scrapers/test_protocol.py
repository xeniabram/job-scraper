import urllib.parse
from typing import get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st

from job_scraper.exceptions import SourceParsingError
from job_scraper.scraper.protocol_scraper import (
    BASE_URL,
    Params,
    ProtocolScraper,
    TechLiteral,
    _with_suffix,
)

# Derive valid values directly from the Literal type so there's one source of truth.
TECH_VALUES = list(get_args(get_args(TechLiteral)[0]))


def _parse_segments(url: str) -> dict[str, set[str]]:
    """Parse protocol path segments like 'python,go;t/backend;sp' into {suffix: {values}}.

    Note: cannot use urlparse here — it treats ';' in URL paths as a path-parameter
    separator (RFC 1808), which breaks segment parsing.
    """
    raw = url.split("/filtry/", 1)[-1].split("?")[0]
    result = {}
    for segment in filter(None, raw.split("/")):
        value, _, suffix = segment.rpartition(";")
        result[suffix] = set(value.split(","))
    return result


def _parse_qs(url: str) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


# ── _with_suffix serializer ────────────────────────────────────────────────────

def test_with_suffix_single_value():
    assert _with_suffix(";t")({"python"}) == "python;t"


def test_with_suffix_string_input():
    assert _with_suffix(";t")("python") == "python;t"


def test_with_suffix_empty_set():
    assert _with_suffix(";t")(set()) == ""


def test_with_suffix_multiple_values():
    result = _with_suffix(";t")({"go", "rust"})
    assert result.endswith(";t")
    assert set(result.removesuffix(";t").split(",")) == {"go", "rust"}


# ── Params / URL building ──────────────────────────────────────────────────────

def test_url_defaults():
    assert Params().build_listing_url() == f"{BASE_URL}/filtry/"


def test_url_no_query_string_when_no_extras():
    assert "?" not in Params(technologies_must={"python"}).build_listing_url()


def test_url_with_tech_must():
    segments = _parse_segments(Params(technologies_must={"python"}).build_listing_url())
    assert segments["t"] == {"python"}


def test_url_with_tech_nice():
    segments = _parse_segments(Params(technologies_nice={"go"}).build_listing_url())
    assert segments["nt"] == {"go"}


def test_url_with_specialization():
    segments = _parse_segments(Params(specializations={"backend"}).build_listing_url())
    assert segments["sp"] == {"backend"}


def test_url_with_query_params():
    qs = _parse_qs(Params(technologies_not={"java"}, project_description_present=True).build_listing_url())
    assert qs["et"] == ["java"]
    assert qs["context"] == ["projects"]


@given(st.sets(st.sampled_from(TECH_VALUES), min_size=1))
def test_tech_must_roundtrips(techs):
    segments = _parse_segments(Params(technologies_must=techs).build_listing_url())
    assert segments["t"] == techs


@given(st.sets(st.sampled_from(TECH_VALUES), min_size=1))
def test_tech_nice_roundtrips(techs):
    segments = _parse_segments(Params(technologies_nice=techs).build_listing_url())
    assert segments["nt"] == techs


def test_none_params_absent_from_url():
    segments = _parse_segments(Params().build_listing_url())
    assert not segments  # no segments at all for default params


# ── Overlap validation ─────────────────────────────────────────────────────────

def test_overlapping_must_and_nice_raises():
    with pytest.raises(ValueError, match=r"must.*nice"):
        Params(technologies_must={"python"}, technologies_nice={"python"})


def test_overlapping_must_and_not_raises():
    with pytest.raises(ValueError, match=r"must.*not"):
        Params(technologies_must={"python"}, technologies_not={"python"})


def test_overlapping_nice_and_not_raises():
    with pytest.raises(ValueError, match=r"nice.*not"):
        Params(technologies_nice={"python"}, technologies_not={"python"})


# ── HTML parsing ───────────────────────────────────────────────────────────────

def test_extract_job_data_empty_page():
    scraper = ProtocolScraper.__new__(ProtocolScraper)
    with pytest.raises(SourceParsingError):
        scraper._extract_job_data("https://theprotocol.it/job/fake", "<html></html>")