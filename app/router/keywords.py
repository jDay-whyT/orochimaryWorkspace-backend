"""Keywords mapping for intent detection."""

# Intent keywords mapping
INTENT_KEYWORDS = {
    # Orders intents
    "orders_new": {
        "keywords": ["новый заказ", "создать заказ", "добавить заказ", "new order", "create order"],
        "model": "orders",
    },
    "orders_list": {
        "keywords": ["заказы", "открытые", "список заказов", "orders", "list", "open orders"],
        "model": "orders",
    },
    "orders_view": {
        "keywords": ["показать заказ", "посмотреть", "view order", "show order"],
        "model": "orders",
    },
    "orders_search": {
        "keywords": ["найти заказ", "поиск", "поиск заказа", "search order", "find"],
        "model": "orders",
    },

    # Planner intents
    "planner_new": {
        "keywords": ["новый план", "создать план", "добавить в план", "новая стрельба", "new planner", "create plan"],
        "model": "planner",
    },
    "planner_list": {
        "keywords": ["планы", "плана", "стрельба", "список планов", "planner", "list plans", "shoots"],
        "model": "planner",
    },
    "planner_view": {
        "keywords": ["показать план", "посмотреть план", "view plan", "show plan"],
        "model": "planner",
    },
    "planner_search": {
        "keywords": ["найти план", "поиск плана", "search plan"],
        "model": "planner",
    },

    # Accounting intents
    "accounting_new": {
        "keywords": ["новая запись", "создать запись", "добавить запись", "new account", "create record"],
        "model": "accounting",
    },
    "accounting_list": {
        "keywords": ["учет", "записи", "финансы", "accounting", "records", "list records"],
        "model": "accounting",
    },
    "accounting_view": {
        "keywords": ["показать запись", "посмотреть запись", "view record"],
        "model": "accounting",
    },
    "accounting_search": {
        "keywords": ["поиск записи", "найти запись", "search record", "search accounting"],
        "model": "accounting",
    },

    # Summary intents
    "summary_view": {
        "keywords": ["сводка", "статистика", "summary", "dashboard", "overview"],
        "model": "summary",
    },
}

# Model names mapping
MODEL_KEYWORDS = {
    "orders": ["заказ", "заказы", "order", "orders"],
    "planner": ["план", "планы", "стрельба", "стрельбы", "planner", "plan", "plans", "shoot", "shoots"],
    "accounting": ["учет", "запись", "финансы", "accounting", "record", "records", "account"],
    "summary": ["сводка", "статистика", "summary", "dashboard"],
}

# Status keywords
STATUS_KEYWORDS = {
    "orders": {
        "open": ["открыт", "открытый", "новый", "open", "new"],
        "done": ["готов", "завершен", "done", "completed", "finished"],
        "canceled": ["отменен", "отменён", "canceled", "cancelled"],
    },
    "planner": {
        "planned": ["плано", "запланирован", "planned"],
        "scheduled": ["запланирован", "scheduled"],
        "rescheduled": ["перепланирован", "rescheduled"],
        "done": ["готов", "завершен", "done", "finished"],
        "stuck": ["застрял", "stuck", "blocked"],
        "cancelled": ["отменен", "cancelled"],
    },
    "accounting": {
        "new": ["новый", "new"],
        "work": ["работаю", "work", "in progress"],
        "inactive": ["неактивный", "inactive"],
        "stop": ["остановлен", "stopped"],
    },
}

# Action keywords
ACTION_KEYWORDS = {
    "create": ["создать", "добавить", "новый", "create", "new", "add"],
    "view": ["показать", "посмотреть", "view", "show", "display"],
    "search": ["найти", "поиск", "ищу", "search", "find", "look"],
    "list": ["список", "все", "list", "all", "show me"],
    "update": ["изменить", "обновить", "edit", "update", "change"],
    "comment": ["добавить комментарий", "comment", "note"],
}
