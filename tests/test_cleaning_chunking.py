from app.ingestion.chunking import chunk_document, split_body
from app.ingestion.cleaning import clean_text
from app.ingestion.models import SourceDocument


def _doc(text: str) -> SourceDocument:
    return SourceDocument(
        doc_id="attack-pattern--x",
        external_id="T1059.001",
        name="PowerShell",
        category="technique",
        source="mitre-attack-enterprise v20.1",
        tactics=["execution"],
        text=text,
    )


def test_clean_text_removes_citations_links_and_html() -> None:
    raw = (
        "[WIRTE](https://attack.mitre.org/groups/G0090) has used PowerShell."
        "(Citation: Lab52 WIRTE Apr 2019) Uses <code>Start-Process</code>. Done"
    )
    assert clean_text(raw) == "WIRTE has used PowerShell. Uses Start-Process. Done"


def test_clean_text_handles_empty() -> None:
    assert clean_text(None) == ""


def test_split_body_never_cuts_a_sentence() -> None:
    text = " ".join(f"Sentence number {i} ends here." for i in range(50))
    slices = split_body(text, max_words=30)
    assert len(slices) > 1
    assert all(s.endswith(".") for s in slices)
    assert " ".join(slices) == text


def test_chunk_ids_are_deterministic_and_header_repeated() -> None:
    text = " ".join(f"Sentence {i} is here." for i in range(200))
    first, second = chunk_document(_doc(text), 50), chunk_document(_doc(text), 50)
    assert [c.point_id for c in first] == [c.point_id for c in second]
    assert all(c.content.startswith("[technique] T1059.001 PowerShell") for c in first)
    assert [c.page for c in first] == list(range(1, len(first) + 1))
    assert first[0].payload["total_pages"] == len(first)


def test_payload_has_required_metadata() -> None:
    payload = chunk_document(_doc("Short text."))[0].payload
    for key in ("doc_id", "source", "page", "category", "content", "date", "external_id", "url"):
        assert key in payload
