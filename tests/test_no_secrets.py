import re
from pathlib import Path

KEY = re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}")


def test_package_has_no_api_key_literal():
    root = Path(__file__).resolve().parents[1]
    for path in list(root.rglob("*.py")) + list(root.rglob("*.md")) + list(root.rglob("*.json")):
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert KEY.search(text) is None, path
