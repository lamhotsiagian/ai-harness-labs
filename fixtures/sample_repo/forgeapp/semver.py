"""Minimal semantic-version utilities used by the release pipeline."""


def parse(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.lstrip("v").split(".")
    return int(major), int(minor), int(patch)


def bump(version: str, part: str) -> str:
    major, minor, patch = parse(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unknown part: {part}")


def compare(a: str, b: str) -> int:
    """Return -1, 0, or 1 like a classic comparator."""
    pa, pb = parse(a), parse(b)
    return (pa > pb) - (pa < pb)
