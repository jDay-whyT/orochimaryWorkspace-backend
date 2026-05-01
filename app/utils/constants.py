# Order types
ORDER_TYPES = ["short", "verif reddit", "ad request", "call", "custom"]

# Order statuses
ORDER_STATUS_OPEN = "Open"
ORDER_STATUS_DONE = "Done"
ORDER_STATUS_CANCELED = "Canceled"

# Planner statuses
PLANNER_STATUS_PLANNED = "planned"
PLANNER_STATUS_SCHEDULED = "scheduled"
PLANNER_STATUS_RESCHEDULED = "rescheduled"
PLANNER_STATUS_DONE = "done"
PLANNER_STATUS_STUCK = "stuck"
PLANNER_STATUS_CANCELLED = "cancelled"

# Active planner statuses (for upcoming list)
PLANNER_ACTIVE_STATUSES = [
    PLANNER_STATUS_PLANNED,
    PLANNER_STATUS_SCHEDULED,
    PLANNER_STATUS_RESCHEDULED,
]

# Planner content options
PLANNER_CONTENT_OPTIONS = [
    "new main",
    "posting",
    "main pack",
    "sfs",
    "twitter",
    "snapchat",
    "fansly",
    "reddit",
    "event",
]

# Planner location options
PLANNER_LOCATION_OPTIONS = ["home", "rent"]

# Accounting content options
ACCOUNTING_CONTENT_OPTIONS = [
    "basic",
    "main pack",
    "new main",
    "twitter",
    "reddit",
    "fansly",
    "snapchat",
    "IG",
    "event",
    "ad request",
    "no content",
]

# Accounting statuses
ACCOUNTING_STATUS_NEW = "new"
ACCOUNTING_STATUS_WORK = "work"
ACCOUNTING_STATUS_INACTIVE = "inactive"
ACCOUNTING_STATUS_STOP = "stop"

# Model statuses
MODEL_STATUS_NEW = "new"
MODEL_STATUS_WORK = "work"
MODEL_STATUS_INACTIVE = "inactive"
MODEL_STATUS_STOP = "stop"
MODEL_STATUS_LOOTED = "looted"

# Pagination
PAGE_SIZE = 8

# Files per month limit (for accounting percentage calculation)
FILES_MONTH_LIMIT = 200

# NLP content types for shoots (canonical values for Planner multi-select)
NLP_SHOOT_CONTENT_TYPES = [
    "twitter",
    "reddit",
    "main",
    "SFS",
    "posting",
    "fansly",
    "event",
    "basic",
    "new main",
]

# NLP content types for accounting (canonical values for Content multi-select)
NLP_ACCOUNTING_CONTENT_TYPES = [
    "basic",
    "main pack",
    "new main",
    "twitter",
    "reddit",
    "fansly",
    "snapchat",
    "IG",
    "event",
    "ad request",
    "no content",
]

# Analytics/scout defaults
DB_FORMS_DEFAULT = "22932beee7a0802492b2fd8b16ece74b"
ARCHIVE_ORDERS_DBS = [
    "2fd32bee-e7a0-80d6-b8a5-ee7bd1001052",  # Jan
    "31632bee-e7a0-8038-ba59-c2ef293fb1c4",  # Feb
    "33532bee-e7a0-80eb-bc7e-d80aff13e400",  # Mar
]

ARCHIVE_ACCOUNTING_DBS = {
    "2026-04": "35332bee-e7a0-81c2-b2c7-000b9d28c599",
}
