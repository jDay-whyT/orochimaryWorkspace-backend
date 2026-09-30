"""Mapping content types to Accounting fields and Content tags."""

# Buttons in the "add files" flow -> Accounting number field
CONTENT_TYPE_TO_FIELD = {
    "of": "of_files",
    "reddit": "reddit_files",
    "twitter": "twitter_files",
    "fansly": "fansly_files",
    # everything else is a request; the exact kind goes into the Content tags
    "request": "request_files",
    "pornhub": "request_files",
    "instagram": "request_files",
    "snapchat": "request_files",
    "event": "request_files",
    "sfs": "request_files",
    "ad request": "request_files",
    # older values still met in records / other callers
    "main pack": "of_files",
    "new main": "of_files",
    "main_pack": "of_files",
    "new_main": "of_files",
    "basic": "of_files",
    "IG": "request_files",
    "no content": None,
}

# Content tag written for a type when it differs from the type name. Plain OF files are tagged new_main.
CONTENT_TAG = {"of": "new_main"}

LABELS = {
    "of": "OF",
    "reddit": "Reddit",
    "twitter": "Twitter",
    "fansly": "Fansly",
    "request": "Request",
    "pornhub": "Pornhub",
    "instagram": "Instagram",
    "snapchat": "Snapchat",
    "event": "Event",
    "sfs": "SFS",
    "ad request": "Ad request",
}


def get_field_for_content_type(content_type: str) -> str | None:
    """Get database field name for content type."""
    return CONTENT_TYPE_TO_FIELD.get(content_type)


def content_tag(content_type: str) -> str | None:
    """Value for the Accounting Content multi-select, or None."""
    if content_type == "no content":
        return None
    return CONTENT_TAG.get(content_type, content_type)


def label(content_type: str) -> str:
    return LABELS.get(content_type, content_type.replace("_", " ").title())
