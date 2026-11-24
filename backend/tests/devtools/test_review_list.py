"""The professional review list (#93) is generated from the platform's data and kept current."""

from fcp.devtools.review_list import OUT, build


def test_the_review_list_is_current() -> None:
    assert OUT.read_text() == build(), (
        "docs/review/professional-review-list.md is out of date: run "
        "`python -m fcp.devtools.review_list` (make review-list)"
    )


def test_it_lists_every_code_and_rule() -> None:
    text = build()
    for needle in (
        "| ☐ | S19 |",
        "| ☐ | IMP3 |",
        "| ☐ | 11B |",
        "| ☐ | RC_EU_SERVICES | NET_PURCHASE",
        "| ☐ | EXEMPT |",
        "### CY:CIT:2026",
        "Already decided by you",
    ):
        assert needle in text, needle
