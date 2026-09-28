"""Text statistics used by the changelog summarizer."""
from collections import Counter
import re


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def top_words(text: str, n: int) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9']+", text)]
    counts = Counter(words)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[:n]]
