"""The guidance a skill cites by section name, and whether each name heads exactly one
section beneath a guidance directory: unit tests of `change_workflow.sections`."""

from __future__ import annotations

from pathlib import Path

from change_workflow import sections


def test_a_citation_names_one_section_or_several() -> None:
    text = ('Follow the engineering guidance\'s section "Imports go at module level", and '
            'the engineering guidance\'s sections "Test levels", "Test seams", and "Where a '
            'test goes"; the workflow guidance\'s sections "Comment hygiene" or\n'
            '   "Import placement".\n')

    assert sections.cited(text, sections.ENGINEERING) == {
        "Imports go at module level", "Test levels", "Test seams", "Where a test goes"}
    assert sections.cited(text, sections.WORKFLOW) == {"Comment hygiene", "Import placement"}


def test_a_name_wrapped_across_lines_is_read_whole() -> None:
    text = ('see the engineering\n  guidance\'s section "Permanent documents describe\n'
            '  the current state".')

    assert sections.cited(text, sections.ENGINEERING) == {
        "Permanent documents describe the current state"}


def test_a_quotation_outside_a_citation_is_no_citation() -> None:
    text = 'The owner said "Test levels"; the guidance\'s section "Test seams" names no layer.'

    assert sections.cited(text, sections.ENGINEERING) == set()


def test_citing_gathers_each_name_with_its_sources() -> None:
    texts = {"change-plan": 'the engineering guidance\'s section "Test levels"',
             "change-review": 'the engineering guidance\'s sections "Test levels" and "Comments"'}

    assert sections.citing(texts, sections.ENGINEERING) == {
        "Test levels": {"change-plan", "change-review"}, "Comments": {"change-review"}}


def test_headings_skip_fenced_blocks() -> None:
    text = "# Title\n\n```markdown\n## Not a heading\n```\n\n## A section ##\n"

    assert sections.headings(text) == ["Title", "A section"]


def test_a_name_resolves_when_exactly_one_section_heads_it(tmp_path: Path) -> None:
    (tmp_path / "testing").mkdir()
    (tmp_path / "test-levels.md").write_text("# Test levels\n\n## Integration tests\n", "utf-8")
    (tmp_path / "testing/integration.md").write_text("# Integration tests\n", "utf-8")

    found = sections.heads(tmp_path)

    assert sections.unresolved({"Test levels", "Integration tests", "Test seams"}, found) == {
        "Integration tests": [Path("test-levels.md"), Path("testing/integration.md")],
        "Test seams": []}
