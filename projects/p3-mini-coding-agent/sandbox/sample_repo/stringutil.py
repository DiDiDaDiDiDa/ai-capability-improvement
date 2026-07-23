"""String helpers — extra symbols so repo-map / retrieval have material."""


def slugify(text: str) -> str:
    """Lowercase, spaces to hyphens; naive slug for demo retrieval."""
    return "-".join(text.lower().split())


def truncate(text: str, limit: int = 20) -> str:
    """Clip text to limit chars with an ellipsis marker."""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


class TextStats:
    """Word/char counters — a class symbol for repo-map extraction."""

    def __init__(self, text: str) -> None:
        self.text = text

    def word_count(self) -> int:
        return len(self.text.split())

    def char_count(self) -> int:
        return len(self.text)
