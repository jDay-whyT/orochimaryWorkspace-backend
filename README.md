# OROCHIMARY Telegram Bot

Telegram-бот (aiogram v3) и Telegram Mini App для работы с моделями агентства. Источник данных — Notion (базы **Models**, **Orders**, **Planner**, **Accounting**, **Notes**). Бот работает через webhook на **Google Cloud Run**, состояние хранит в **Redis** (Upstash).

## Что умеет

**Менеджерам** (интерфейс на простом английском):
- написать имя модели → карточка модели → кнопками заказы, съёмки, файлы, заметки;
- поиск прощает опечатку (1 буква, для длинных имён 2), не различает регистр, ё/е и ударения; латинские варианты имён — через алиасы в Models;
- напоминания в 12:00: долго открытые заказы и мало контента, только по своим моделям;
- Mini App: только свои модели (по `assist` в Accounting).

**Владельцу** (на русском):
- заявки на доступ: новый человек пишет боту /start → кнопка с менеджером (`assist`) → доступ, напоминания и дайджест; `/access` — список и «убрать»;
- дайджест действий менеджеров в 23:55;
- `/reports` — зарплатный отчёт в Google Sheets, `/rename_month` — закрытие месяца, `/tango` — расписание стримов;
- уведомления о новых профилях WML, датах Fansly, новых анкетах, дублях в Accounting;
- выгрузка в WML CRM дважды в день со сводкой.

**Доскам в группе:** `/shoots` — съёмки на 7 дней, `/reddit` — Reddit-модели. Обновляются по расписанию.

## Выгрузка в WML CRM

Notion — источник, CRM только получает. Задача `wml-export` в 01:00 и 16:00 (Europe/Brussels):
- заказы: новые создаются, у отправленных обновляются `out` / `count` / `received`, отменённые и удалённые открытые — `cancelled`; CRM id хранится в Orders `wml_id`;
- файлы: цифры модели за месяц (апсерт по модели и месяцу), только если изменились;
- Танго не выгружается;
- проверки: уменьшение или скачок файлов (>300) задерживаются на одну выгрузку; дубли в Accounting и один CRM id у нескольких заказов не отправляются; неизвестный профиль сообщается один раз;
- без `WML_EXPORT_APPLY=1` только присылает отчёт; во время `/rename_month` пропускается; одновременно идёт одна выгрузка.

Разовые команды владельца: `/wml_test_orders` (до 100 неотправленных заказов за сентябрь), `/wml_test_files [N]` (файлы, топ N по Total).

## Настройки

Все настройки — переменные окружения Cloud Run (секреты — в GitHub Secrets и Secret Manager). Полный список с значениями по умолчанию — в `app/config.py`. Менеджеров в env больше добавлять не нужно: они одобряются через бота и хранятся в Redis.

## Архитектура: что важно не сломать

1. **Один lock на пользователя для текста и кнопок.** `route_message` и `handle_nlp_callback` работают с одним `memory_state`; оба оборачивают тело в `async with get_user_lock(chat_id, user_id)`.
2. **После записи в Notion — сброс кэша.** `orders.py` / `planner.py` / `accounting.py` держат TTL-кэш на модель: после `create_/update_/close_*` вызывай `*_cache.clear_cache(...)`. Карточка модели сама видит записи бота: `NotionClient` 2 минуты помнит страницы, которые создал или изменил (поиск по базе Notion отстаёт от записи на несколько секунд).
3. **Новая клавиатура — гаси старую.** Перед новым экраном вызывай `_clear_previous_screen_keyboard(...)`, иначе старые кнопки ведут в «Session expired».
4. **Список моделей для поиска** (`app/handlers/models.py`) кэшируется: память 5 минут + копия в Redis + прогрев при старте. Новую модель из WML кэш видит сразу, правку в Notion — в течение 5 минут.

## Структура

```
app/
├── server.py            # aiohttp: webhook, internal endpoints, Mini App API и статика
├── bot.py               # роутеры aiogram
├── config.py            # настройки из env
├── api/                 # Mini App: initData-проверка, модели, карточка
├── handlers/            # access, nlp_callbacks (карточка и шаги), start, отчёты, WML, доски, Танго
├── router/              # разбор текста: имя модели, поиск с опечатками (model_resolver)
├── services/            # Notion-клиент, карточки, выгрузка в CRM, напоминания, дайджест, синхронизации
├── keyboards/           # inline-клавиатуры
├── state/               # Redis / in-memory состояние диалогов и недавние модели
└── utils/               # форматирование, локи, Telegram-помощники
frontend/                # Mini App (React/Vite)
tests/                   # pytest
```

## Расписание (Cloud Scheduler, europe-west1)

| Задача | Когда | Endpoint |
|---|---|---|
| `update-shoots-board` | каждые 3 ч | `/internal/update-board` |
| `update-reddit-board` (us-central1) | каждые 3 ч | `/internal/update-reddit-board` |
| `wml-scraper` | каждый час | `/internal/scrape-wml` — новые профили WML, даты Fansly, анкеты, статусы Accounting |
| `daily-reminders` | 12:00 | `/internal/daily-reminders` |
| `activity-digest` | 23:55 | `/internal/activity-digest` |
| `wml-export` | 01:00 и 16:00 | `/internal/wml-export` |

Все `/internal/*` требуют заголовок `X-Internal-Secret`. Новую задачу проще всего создать по образцу существующей (`gcloud scheduler jobs describe daily-reminders --location europe-west1`).

## Деплой

Push в `main` не деплоит. Деплой — вручную: GitHub → Actions → **Deploy TG Bot (Cloud Run)** → Run workflow. Workflow задаёт только свои переменные, остальные (таймаут, доступ, флаги) сохраняются в сервисе.

Разовое изменение переменной без деплоя кода:
```bash
gcloud run services update orochimary-bot --region europe-west1 --update-env-vars KEY=value
```
Значение с запятыми: `--update-env-vars '^;^KEY=a,b,c'`.

## Локально

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest            # тесты
python -m app.server        # сервер на :8080, проверка: curl localhost:8080/healthz
```

## Если что-то не так

- **Бот молчит** — логи Cloud Run; человек есть в доступе (`/access`)? webhook на месте?
- **«Session expired»** — нажата кнопка со старого экрана, открой модель заново.
- **Модель не находится** — проверь имя/алиас в Models; правка в Notion видна боту в течение 5 минут.
- **Ошибка выгрузки в CRM** — текст приходит в сводке; «Profile not found» = профиля нет в WML, «Out must be ≥ In» = опечатка в датах заказа.
- **401/403 Notion** — токен и доступ интеграции ко всем базам.

## License

[GNU General Public License v3.0](LICENSE)
