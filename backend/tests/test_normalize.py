import pytest

from app.services.normalize import NormalizationError, normalize, same_site


@pytest.mark.parametrize("raw,host,reg", [
    ("https://www.example.com/article/123", "example.com", "example.com"),
    ("EXAMPLE.com.", "example.com", "example.com"),
    ("example.com:8080/x?y=1", "example.com", "example.com"),
    ("news.bbc.co.uk", "news.bbc.co.uk", "bbc.co.uk"),
    ("www.bbc.co.uk", "bbc.co.uk", "bbc.co.uk"),
    ("sub.domain.example.co.uk", "sub.domain.example.co.uk", "example.co.uk"),
    ("münchen.de", "xn--mnchen-3ya.de", "xn--mnchen-3ya.de"),
    ("//cdn.example.org/lib.js", "cdn.example.org", "example.org"),
])
def test_normalize(raw, host, reg):
    n = normalize(raw)
    assert n.host == host
    assert n.registrable_domain == reg


def test_shared_platform_subdomains_are_not_merged():
    a, b = normalize("alice.blogspot.com"), normalize("bob.blogspot.com")
    assert a.registrable_domain != b.registrable_domain
    assert a.is_private_suffix
    c, d = normalize("one.github.io"), normalize("two.github.io")
    assert c.host != d.host and c.registrable_domain != d.registrable_domain


def test_distinct_subdomains_stay_distinct():
    assert normalize("news.example.com").host != normalize("sport.example.com").host
    assert normalize("www.example.com").host == normalize("example.com").host


@pytest.mark.parametrize("raw", ["", "1.2.3.4", "co.uk", "mailto:a@b.com", "ftp://example.com", "localhost", "exa mple.com", "-bad-.com"])
def test_rejects(raw):
    with pytest.raises(NormalizationError):
        normalize(raw)


def test_same_site():
    assert same_site("www.example.com", "m.example.com")
    assert not same_site("alice.blogspot.com", "bob.blogspot.com")
