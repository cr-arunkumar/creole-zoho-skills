import pytest

from zoho_skills import mcp_config as m

URL = "https://example.invalid/mcp?key=SECRET"


@pytest.mark.parametrize("bad", ["", "ftp://x", "http://example.com/mcp", "not a url"])
def test_url_validation(bad):
    with pytest.raises(m.McpError):
        m.validate_url(bad)


def test_mask_url_hides_key():
    assert "SECRET" not in m.mask_url(URL)


def test_console_urls_default_to_india_and_reject_unknown():
    assert m.console_url(m.DEFAULT_REGION) == "https://mcp.zoho.in/"
    assert m.console_url("com") == "https://mcp.zoho.com/"
    with pytest.raises(m.McpError):
        m.console_url("mars")
