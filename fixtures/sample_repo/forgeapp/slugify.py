"""URL slug generation for release notes."""
import re


def slugify(text: str) -> str:
    """Lowercase, replace runs of non-alphanumerics with one dash, trim dashes."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")
