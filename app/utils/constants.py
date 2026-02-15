# Order types
ORDER_TYPES = ["short", "ad request", "call", "custom"]

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
    "basic",
    "event",
    "new main",
    "posting",
    "main pack",
    "sfs",
    "twitter",
    "snapchat",
    "fansly",
    "reddit",
    "main",
]

# Planner location options
PLANNER_LOCATION_OPTIONS = ["home", "rent"]

# Accounting content options
ACCOUNTING_CONTENT_OPTIONS = [
    "basic",
    "main",
    "new main",
    "twitter",
    "reddit",
    "fansly",
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
]

# NLP content types for accounting (canonical values for Content multi-select)
NLP_ACCOUNTING_CONTENT_TYPES = [
    "basic",
    "main",
    "new main",
    "twitter",
    "reddit",
    "fansly",
    "ad request",
    "no content",
]
