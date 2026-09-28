"""own-chrome is a generic Chrome-CDP tool. LinkedIn automation lives in
linkedin-mcp (github.com/ml-lubich/linkedin-mcp) now, not here.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "own_chrome"


def test_no_li_console_script():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "li" not in data["project"]["scripts"]
    assert data["project"]["scripts"]["own-chrome"] == "own_chrome.cli:main"


@pytest.mark.parametrize("module", ["own_chrome.linkedin", "own_chrome.li_app"])
def test_linkedin_modules_are_gone(module):
    with pytest.raises(ImportError):
        __import__(module)


def test_no_module_mentions_linkedin():
    offenders = []
    for path in SRC.rglob("*.py"):
        if "linkedin" in path.read_text(encoding="utf-8").lower():
            offenders.append(path.name)
    assert offenders == []


def test_public_cdp_api_is_unchanged():
    from own_chrome.cdp import (
        DEFAULT_PORT,
        ChromeError,
        describe,
        evaluate,
        filter_pages,
        navigate,
        open_tab,
        pages,
        pick_page,
    )

    assert DEFAULT_PORT == 9222
    assert issubclass(ChromeError, RuntimeError)
    for fn in (describe, evaluate, filter_pages, navigate, open_tab, pages, pick_page):
        assert callable(fn)
