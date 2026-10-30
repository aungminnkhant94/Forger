import pytest
from forger.scrapers.doi_metadata import _normalize_doi, extract_doi_from_url


def test_chemrxiv_version_kept():
    url = "https://chemrxiv.org/doi/full/10.26434/chemrxiv.15011251/v1"
    assert extract_doi_from_url(url) == "10.26434/chemrxiv.15011251/v1"
    assert _normalize_doi("10.26434/chemrxiv.15011251/v1") == "10.26434/chemrxiv.15011251/v1"


@pytest.mark.parametrize("raw", [
    "10.1101/2024.01.01.002386v1",
    "10.1101/2024.01.01.002386v1.full",
    "10.1101/2024.01.01.002386v2.full.pdf",
    "10.1101/2024.01.01.002386.pdf",
    "10.1101/2024.01.01.002386/",
])
def test_biorxiv_suffixes_stripped(raw):
    assert _normalize_doi(raw) == "10.1101/2024.01.01.002386"


@pytest.mark.parametrize("raw", ["10.1021/jacs.5c01234", "10.1038/s41586-024-07000-1", "10.9999/foo.v2"])
def test_others_untouched(raw):
    assert _normalize_doi(raw) == raw


def test_no_trailing_slash():
    assert not _normalize_doi("10.26434/chemrxiv.15011251/").endswith("/")
