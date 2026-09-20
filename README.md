# Городской помощник — Phase 2: Real AI Integration

Локальный end-to-end прототип: текст → mock или OpenRouter → validated AIAnalysis → существующий deterministic scoring → одна карточка оператора. Phase 2 добавляет реальный AI adapter; duplicate detection, embeddings, SQLite и deployment не реализованы.

## Problem / Target users / Value

Оператор городской службы вручную читает жалобы, определяет категорию и приоритет. Прототип показывает структуру будущего рабочего процесса и объяснение расчёта. Эффективность на реальных обращениях пока не измерена.

## Solution / Key features

- Форма обращения и кнопка Analyze, валидация 1–5 000 символов после trim.
- Pydantic-контракт: category, summary, location, event_time_text, ongoing, safety_risk, critical_outage, persists_multiple_days, review_reasons.
- Признаки содержат value yes/no/unknown и evidence — точные цитаты входного текста.
- Карточка: категория, краткое извлечение из текста, место, score, priority, reasons с баллами/цитатами и раскрываемый structured analysis.
- Шесть синтетических примеров; явная ошибка пустого ввода; API для того же сценария.

## AI role / Provider architecture

main.py зависит от общего AnalysisProvider, а выбор находится в app/providers/__init__.py:

- `AI_PROVIDER=mock` — сохранённый regex mock из Phase 1, без сети и ключей. Используется по умолчанию, если AI_PROVIDER не задан. Summary — фрагмент исходника; отсутствие шаблона означает no только для этой демонстрации.
- `AI_PROVIDER=openrouter` — реальный OpenRouter Chat Completions через HTTPX. Ключ берётся только из OPENROUTER_API_KEY; модель — только из OPENROUTER_MODEL. Отсутствующая модель считается ошибкой конфигурации, не заменяется неявным default.

AI возвращает только признаки, category/summary, nullable location/event_time_text, ongoing/unknown, evidence и review_reasons. Score/priority/итоговое решение запрещены схемой. app/scoring.py не изменён относительно Phase 1.

System prompt отделён от JSON DATA с обращением: инструкции внутри обращения игнорируются, отсутствующие факты не придумываются, цитаты точные, недостаточные сведения → null/unknown. Structured Outputs JSON Schema используется вместе с локальной строгой Pydantic-валидацией: все поля обязательны, лишние поля запрещены, category проверяется enum, каждая цитата должна точно присутствовать в исходнике (регистр/пробелы не нормализуются). Positive и explicit negative признаки реального AI требуют evidence.

Real AI не подменяет отсутствие сведений значением no: если сведения о критической услуге отсутствуют, возможен unknown и карточка без итогового priority, с subtotal. Поэтому результаты реального AI не обязаны совпадать с упрощёнными mock-примерами.

Один Analyze → один POST, без автоматических retry, fallback на mock, fallback-моделей или paid fallback. Model передаётся из environment без замены. В запросе require_parameters=true, allow_fallbacks=false; HTTP redirects отключены. Таймаут подключения 10 секунд, чтения 45 секунд. Это сетевые таймауты HTTPX, не гарантия времени обработки всей страницы.

Ошибки missing key/model, timeout, 429, network, API, empty/malformed response, неверная category/evidence выводятся понятным сообщением. Текст остаётся в форме; невалидные данные не доходят до scoring. Raw response и текст исключений провайдера не выводятся в UI/логи, API-ключ хранится в памяти как SecretStr и передаётся только в Authorization header.

Официальные источники API: [Chat Completions](https://openrouter.ai/docs/api_reference/overview), [Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [Free Router](https://openrouter.ai/docs/guides/routing/routers/free-router).

## Priority — demo rules

Это демонстрационная модель, **не реальные нормативы городской службы**.

| Признак | Баллы |
|---|---:|
| Safety risk | +40 |
| Critical infrastructure/service outage | +30 |
| Три и более probable duplicate reports | +20 |
| Проблема длится минимум два дня | +10 |

Каждый вклад начисляется один раз. 0–29 LOW; 30–59 MEDIUM; 60+ HIGH. Причины включают только сработавшие правила.

**Граница Phase 1–2:** поиска дублей нет. Backend явно передаёт в engine count=0, а UI предупреждает, что вклад отключён. В API probable_duplicate_count=null (не измерен), duplicate_count_for_scoring=0, duplicate_detection_status=disabled_phase1 (сохранённое имя поля/значения API Phase 1; поиск остаётся отключённым и в Phase 2). Это не утверждение «дублей нет». Правило +20 реализовано в том же engine и проверяется unit-тестами на синтетическом count; API не принимает count от пользователя.

При неизвестном scoring-признаке engine возвращает score/priority=null, subtotal известных вкладов и unresolved. Для будущего поиска неизвестный count=None также блокирует итог, а не подменяется нулём. Подсчёт уникальных кандидатов и их ID будет ответственностью будущего duplicate detection, а не mock или scoring.

## Architecture / Tech stack

Python 3.12+, FastAPI, Pydantic 2, Jinja2, Uvicorn, HTML/CSS; анализ работает без JavaScript; небольшой script автоматически отправляет изменения признаков, без него есть кнопка пересчёта.

```text
HTML form / JSON API
    → AnalyzeRequest validation
    → AnalysisProvider (mock / OpenRouter)
    → AIAnalysis + evidence validation
    → scoring.calculate_priority
    → OperatorCard → Jinja2 HTML / JSON
```

- app/models.py — контракты.
- app/mock_ai.py — сохранённый mock; app/providers/ — общий интерфейс, factory, adapters, prompt и безопасные ошибки.
- app/scoring.py — независимый engine всех четырёх правил.
- app/main.py — общая сборка карточки для формы и API.
- app/examples.py — синтетические тексты.
- app/templates/index.html и app/static/style.css — UI.

## How to run locally

Python 3.12+, bash. Установка:

```bash
cd /home/batyr/projects/hackathon-training
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

Mock (ключ не нужен):

```bash
cd /home/batyr/projects/hackathon-training
AI_PROVIDER=mock .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Real OpenRouter (OPENROUTER_API_KEY уже экспортирован в environment сервера):

```bash
cd /home/batyr/projects/hackathon-training
AI_PROVIDER=openrouter OPENROUTER_MODEL=openrouter/free .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Открыть http://127.0.0.1:8001, OpenAPI — http://127.0.0.1:8001/docs. Это альтернативные режимы: остановить предыдущий процесс Ctrl+C перед запуском другого на том же порту. Смена environment требует перезапуска процесса. Без тестов достаточно requirements.txt; HTTPX теперь runtime dependency. Установленные версии остаются зафиксированными в requirements.lock.txt.

## Environment variables

| Переменная | Значение |
|---|---|
| AI_PROVIDER | mock (default) либо openrouter |
| OPENROUTER_API_KEY | Секрет из environment, требуется только для openrouter |
| OPENROUTER_MODEL | Требуется для openrouter; для этой тренировки openrouter/free |

.env.example содержит пустое поле ключа, без секретов. .env и локальные .env.* исключены из Git, .env.example разрешён. Приложение **не читает .env автоматически**: либо экспортировать переменные штатным способом, либо создать локальный .env из примера, заполнить его в редакторе и загрузить перед запуском:

```bash
set -a
source .env
set +a
```

Не вставляйте реальный ключ в исходники, README, команды с буквальным ключом или Git. Ключ не требуется для pytest; fixture изолирует AI environment и блокирует настоящий HTTP.

## Main scenario / Demo data (mock)

1. Открыть главную страницу.
2. Выбрать «Фонарь и искрение», затем Analyze.
3. Увидеть Освещение, score 50, MEDIUM, причины +40 за риск и +10 за длительность.
4. Проверить исходные цитаты и structured analysis.
5. Отправить пустое поле — получить понятную ошибку, а не карточку с LOW.

| Пример | Ожидаемый результат в mock |
|---|---|
| Фонарь и искрение | 50 / MEDIUM |
| Нет воды второй день | 40 / MEDIUM |
| Искрение + нет воды второй день | 80 / HIGH |
| Мусор во дворе | 0 / LOW |
| Отрицание искрения и оголённых проводов | 0 / LOW |
| «Возможно провод искрит» | Требует проверки, score/priority=null |

В примерах хранятся только тексты, результаты вычисляются при каждом запросе.

JSON API:

```bash
curl -s http://127.0.0.1:8001/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"text":"Провод искрит второй день."}'
```

## Tests

```bash
cd /home/batyr/projects/hackathon-training
.venv/bin/python -m pytest -q
```

Unit: все 16 комбинаций правил, границы score, порог 2/3 дубля и однократное начисление, неизвестные признаки, неверные аргументы, пересчёт без мутации. Integration: общая цепочка для HTML и API, все demo-классы, пустой/длинный ввод, неизвестность, проверка цитат, экранирование HTML и ошибки анализа.

Историческая проверка Phase 1 на Python 3.12.3: **61 passed**; pip check — без конфликтов. На живом Uvicorn проверены HTML/API, LOW/MEDIUM/HIGH, unknown и пустой ввод 422. В Chrome проверены выбор примера → Analyze → 50/MEDIUM и две причины, structured analysis, мобильная ширина 390px и пустой ввод. Два предупреждения deprecation относятся к Starlette TestClient (HTTPX/AnyIO), не к сбоям приложения.

Phase 2: новый provider test suite использует только httpx.MockTransport; проверяет selection, success, schema, отсутствующие поля, ошибки авторизации/лимита/сети, timeout, пустой/повреждённый ответ, точные evidence, prompt/data separation и запрет прямого priority. Все исходные 61 тест сохранены.

Историческая проверка интеграции до UX-доработки: 142 tests passed (61 исходный + 81 новый), 2 прежних deprecation warnings Starlette TestClient. pip check и git diff --check — без ошибок. Живой mock HTTP flow проверен: 50/MEDIUM, evidence, пустой ввод 422. Реальный manual OpenRouter test пропущен: OPENROUTER_API_KEY отсутствует в environment; реальных запросов не было. Новый браузерный прогон Phase 2 не выполнен: автоматическая проверка разрешений отклонила запуск Chrome из-за лимита использования. HTML/API и UI-содержимое проверены тестами и HTTP.

## Deployment / Limitations

Публичного deployment нет. Только локальный запуск, без authentication, roles, embeddings, duplicate detection, SQLite, карт и интеграций. Карточки и scoring-overrides временно хранятся в памяти одного процесса; постоянного хранения и подтверждения дублей нет. В mock режиме результаты синтетические; в openrouter режиме запрос уходит реальному AI. Проверка структуры и вхождения цитат не доказывает смысловую правильность признаков; оператор проверяет результат. Реальную точность/производительность на датасете не оценивали.

## External materials

- Исходные AGENTS.md и docs/HACKATHON_PLAYBOOK.txt существовали до реализации; требования и CASE/PLAN предоставлены/одобрены пользователем.
- Код, HTML/CSS, тесты и синтетические примеры подготовлены с AI-помощью Codex; внешние UI-шаблоны/датасеты не использованы.
- Прямые зависимости: FastAPI (MIT), Pydantic (MIT), Jinja2 (BSD-3-Clause), Uvicorn (BSD-3-Clause), python-multipart (Apache-2.0); HTTP-клиент: HTTPX (BSD-3-Clause); тесты: pytest (MIT). Источники — одноимённые пакеты PyPI; точные установленные версии, включая транзитивные, в requirements.lock.txt.
- Добавлен OpenRouter adapter. Запрашиваемая модель задаётся OPENROUTER_MODEL; для тренировки — openrouter/free. Факт успешного живого вызова указывается отдельно от unit-тестов с mock HTTP.

## Future development / Project documents

CASE.md и PLAN.md описывают целевой MVP шире Phase 2. Следующие этапы требуют отдельного запроса: semantic duplicate detection, embeddings, подтверждение оператором, история и deployment. Текущая остановка — review после Phase 2. Commit и push не выполняются.

### Исправление обрезанного ответа OpenRouter

На demo-тексте воспроизведён HTTP 200 с finish_reason=length: лимит 1800 токенов обрезал JSON. Лимит увеличен до 4096, prompt требует компактный JSON и короткие непрерывные цитаты. Для invalid_response добавлены безопасные причины (truncated/json/fields/feature_shape/schema/negative_without_evidence/envelope/incomplete); в логах только code/reason, без ключа, обращения и сырого ответа. Автоматические retry/fallback не добавлены, строгая проверка evidence сохранена.

Проверка после исправления: 148 tests passed. Один реальный запрос с двухстрочным примером про фонарь успешно прошёл Pydantic и exact evidence validation: category=Освещение, subtotal=50, critical_outage=unknown, итоговые score/priority=null. Это ожидаемый результат при недостатке данных, а не ошибка. Ключ прочитан только для запроса из локального .env и не выведен. Ранее записанный пропуск manual test относился к моменту, когда ключ ещё не был доступен.

После изменения файлов перезапустить Uvicorn (или использовать --reload локально). Перед запуском из .env в bash выполнить set -a, source .env, set +a; приложение не загружает .env автоматически.

## Phase 2 — ручное подтверждение scoring-признаков

В карточке доступны safety_risk и critical_outage (yes/no/unknown), а также длительность: «Нет данных» → unknown, «Менее двух дней» → no, «Два дня и более» → yes. Начальные значения берутся из AI. Изменение автоматически отправляет обычную HTML-форму на backend; без JavaScript доступна кнопка «Пересчитать».

Исходный AIAnalysis, его значения, evidence и review_reasons не изменяются. Текущие решения находятся отдельно в operator_overrides; effective_values показывает значения для расчёта. Любой изменённый признак отмечается operator override, даже если оператор затем выбрал исходное AI-значение. Замечания AI в карточке явно обозначены как исходные.

Backend повторно вызывает существующий app/scoring.py, который не изменялся. Для override основание обозначено как решение оператора и не выдаётся за цитату AI. Повторных AI-вызовов нет. Unknown блокирует final score/priority и оставляет subtotal и список неизвестных признаков. Пример yes/unknown/yes → смена critical_outage на no → 50/MEDIUM; смена на yes → 80/HIGH.

Карточки с исходным AI и последними overrides хранятся только в памяти одного процесса: до 256 карточек, час после создания/последней правки. После перезапуска, истечения срока или вытеснения карточки нужно снова выполнить Analyze; сообщение об этом сохраняет текст формы. Это временное состояние, не постоянная БД и не журнал изменений. Использовать один worker; SQLite, duplicate detection и deployment не добавлены.

Endpoints: POST /cards/{card_id}/features для формы и PATCH /api/cards/{card_id}/features для JSON {field, value}. Клиент не может подменить исходный анализ или прислать готовый score через этот endpoint.

Проверка: полный pytest — 168 passed, два прежних deprecation warnings TestClient. Chrome подтвердил автоматический пересчёт 50/MEDIUM ↔ 80/HIGH ↔ unknown, mapping длительности, сохранность AI, маркеры override и мобильную ширину. За сценарий выполнен только один Analyze. Остановлено на review, commit/push не выполнялись.
