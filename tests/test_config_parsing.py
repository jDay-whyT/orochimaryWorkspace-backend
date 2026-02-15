from app.config import _parse_user_ids


def test_parse_user_ids_accepts_commas_spaces_and_newlines() -> None:
    raw = "123, 456\n789\t101112,\n 131415"
    assert _parse_user_ids(raw) == {123, 456, 789, 101112, 131415}


def test_parse_user_ids_ignores_invalid_tokens() -> None:
    raw = "1, abc\n2 - 3"
    assert _parse_user_ids(raw) == {1, 2, 3}
