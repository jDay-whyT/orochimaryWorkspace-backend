from app.utils.formatting import MAX_COMMENT_LENGTH, format_appended_comment


def test_appended_comment_keeps_new_text():
    out = format_appended_comment("a" * MAX_COMMENT_LENGTH, "NEW COMMENT")
    assert len(out) <= MAX_COMMENT_LENGTH and out.endswith("NEW COMMENT")
    assert format_appended_comment("a", "b" * 3000) == "b" * MAX_COMMENT_LENGTH
    assert format_appended_comment("a", "b") == "a\n---\nb"
