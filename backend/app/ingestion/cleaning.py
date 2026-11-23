"""Text normalisation for ATT&CK / CAPEC / CWE descriptions."""

import re
import unicodedata

_CITATION = re.compile(r"\s*\(Citation:[^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://|/)[^)]*\)")
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_SPACES = re.compile(r"[ \t   ]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


def clean_text(text: str | None) -> str:
    """Remove citation markers, markdown links and HTML tags; normalise whitespace."""
    if not text:
        return ""
    out = unicodedata.normalize("NFC", text)
    out = _CITATION.sub("", out)
    out = _MD_LINK.sub(r"\1", out)  # keep the anchor text ("WIRTE"), drop the URL
    out = _HTML_TAG.sub("", out)  # <code>Start-Process</code> -> Start-Process
    out = _SPACES.sub(" ", out)
    out = _BLANK_LINES.sub("\n\n", out)
    return "\n".join(line.strip() for line in out.strip().splitlines())


def word_count(text: str) -> int:
    return len(text.split())
