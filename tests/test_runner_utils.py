"""Tests for pipeline/runner.py — pure utility functions."""

from pipeline.runner import _extract_keywords, _shorten_note, _format_rules_block


# ── _extract_keywords ──────────────────────────────────────────────────────────

def test_extracts_camelcase_tokens():
    keywords = _extract_keywords("ConvertPdfToDocx")
    assert "convert" in keywords
    assert "docx" in keywords


def test_splits_hyphens_and_underscores():
    keywords = _extract_keywords("pdf-to-word_conversion")
    assert "word" in keywords
    assert "conversion" in keywords


def test_filters_stop_words():
    keywords = _extract_keywords("add the document page")
    # "add", "the", "document", "page" are all stop words
    assert len(keywords) == 0


def test_returns_set():
    result = _extract_keywords("PdfDocument PdfDocument")
    assert isinstance(result, set)


def test_empty_string_returns_empty_set():
    assert _extract_keywords("") == set()


# ── _shorten_note ──────────────────────────────────────────────────────────────

def test_short_note_unchanged():
    note = "Use Document.Save() to save the file."
    assert _shorten_note(note) == note


def test_truncates_at_max_len():
    note = "x" * 300
    result = _shorten_note(note, max_len=100)
    assert len(result) == 100


def test_keeps_two_sentences_if_short_enough():
    note = "First sentence. Second sentence. Third sentence."
    result = _shorten_note(note, max_len=200)
    assert "First sentence." in result
    assert "Second sentence." in result
    assert "Third sentence." not in result


def test_single_sentence():
    note = "Only one sentence here."
    assert _shorten_note(note) == note


# ── _format_rules_block ────────────────────────────────────────────────────────

def test_always_include_rules_appear_in_mandatory_section():
    rules = {
        "limit-collections-to-four-elements-evaluation-mode": {
            "note": "Max 4 elements in any collection."
        },
        "some-other-rule": {
            "note": "Some other guidance."
        },
    }
    result = _format_rules_block(rules, task="add annotation to pdf", category="annotations")
    assert "MANDATORY RULES" in result
    assert "limit-collections-to-four-elements-evaluation-mode" in result


def test_task_keywords_match_relevant_rules():
    rules = {
        "annotation-rect-coordinates": {
            "note": "Use Aspose.Pdf.Rectangle for annotation coordinates."
        },
        "signature-field-creation": {
            "note": "Use SignatureField for digital signatures."
        },
    }
    result = _format_rules_block(rules, task="add rectangle annotation", category="annotations")
    assert "annotation-rect-coordinates" in result


def test_empty_rules_returns_empty_string():
    assert _format_rules_block({}) == ""


def test_skips_metadata_keys():
    rules = {
        "__version": {"note": "internal"},
        "valid-rule": {"note": "A valid rule note."},
    }
    result = _format_rules_block(rules)
    assert "__version" not in result
    assert "valid-rule" in result


def test_rules_without_note_are_skipped():
    rules = {
        "rule-no-note": {},
        "rule-with-note": {"note": "Has a note."},
    }
    result = _format_rules_block(rules)
    assert "rule-no-note" not in result
    assert "rule-with-note" in result


def test_respects_max_chars():
    rules = {f"rule-{i}": {"note": "x" * 500} for i in range(100)}
    result = _format_rules_block(rules, max_chars=1000)
    assert len(result) < 2000  # truncation kept it bounded
