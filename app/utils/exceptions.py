"""Custom exceptions for Notion API integration."""


class NotionAPIError(Exception):
    """Base Notion API exception with user-facing message and retryability flag."""

    def __init__(self, message: str, user_message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.user_message = user_message
        self.retryable = retryable


class NotionUnavailableError(NotionAPIError):
    def __init__(self, message: str = "Notion API временно недоступен.") -> None:
        super().__init__(message, "⚠️ Notion временно недоступен. Попробуй ещё раз через минуту.", retryable=True)


class NotionNotFoundError(NotionAPIError):
    def __init__(self, message: str = "Запись Notion не найдена.") -> None:
        super().__init__(message, "⚠️ Не удалось найти данные в Notion. Проверь, что запись существует.", retryable=False)


class NotionValidationError(NotionAPIError):
    def __init__(self, message: str = "Некорректный запрос к Notion.") -> None:
        super().__init__(message, "⚠️ Notion отклонил запрос: проверь введённые данные.", retryable=False)


class NotionRateLimitError(NotionAPIError):
    def __init__(self, message: str = "Превышен лимит запросов к Notion.") -> None:
        super().__init__(message, "⏳ Слишком много запросов к Notion. Попробуй через несколько секунд.", retryable=True)


class NotionAuthError(NotionAPIError):
    def __init__(self, message: str = "Ошибка авторизации Notion.") -> None:
        super().__init__(message, "🔐 Нет доступа к Notion. Проверь интеграцию и права доступа.", retryable=False)
