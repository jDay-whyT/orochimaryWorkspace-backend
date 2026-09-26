"""Mapping content types to database fields."""

CONTENT_TYPE_TO_FIELD = {
    "main pack": "of_files",
    "new main": "of_files",
    "main_pack": "of_files",
    "new_main": "of_files",
    "of": "of_files",
    "basic": "of_files",
    "event": "of_files",
    "reddit": "reddit_files",
    "twitter": "twitter_files",
    "fansly": "fansly_files",
    # Social platforms are counted as requests (social_files is being retired)
    "instagram": "request_files",
    "snapchat": "request_files",
    "IG": "request_files",
    "ad request": "request_files",
    "request": "request_files",
    "no content": None,
}


def get_field_for_content_type(content_type: str) -> str | None:
    """Get database field name for content type."""
    return CONTENT_TYPE_TO_FIELD.get(content_type)
