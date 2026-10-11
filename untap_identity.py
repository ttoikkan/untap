"""Shared logical report-title identity, without runtime or publishing imports."""


def report_identity(title: str) -> str:
    """Normalize whitespace and case; retain accents as identity distinctions."""
    return " ".join(title.split()).casefold()
