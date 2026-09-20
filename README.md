# Городской помощник — Phase 3: кандидаты на дубликаты

End-to-end прототип: текст → mock или OpenRouter → validated AIAnalysis → deterministic duplicate matching → существующий scoring → карточка → решение оператора. Phase 3 добавляет кандидатов на дубликаты и confirm/reject. Embeddings, SQLite и следующие этапы не реализованы. Ранний deployment на Render работает по сообщению пользователя; текущие изменения ещё не опубликованы.

## Problem / Target users / Value

Оператор городской службы вручную читает жалобы, определяет категорию и приоритет. Прототип показывает структуру будущего рабочего процесса и объяснение расчёта. Эффективность на реальных обращениях пока не измерена.

## Solution / Key features

- Форма обращения и кнопка Analyze, валидация 1–5 000 символов после trim.
- Pydantic-контракт: category, summary, location, event_time_text, ongoing, safety_risk, critical_outage, persists_multiple_days, review_reasons.
- Признаки содержат value yes/no/unknown и evidence — точные цитаты входного текста.
- Карточка: категория, краткое извлечение из текста, место, score, priority, reasons с баллами/цитатами и раскрываемый structured analysis.
- Шесть синтетических примеров ввода и 12 исторических обращений; явная ошибка пустого ввода; API для того же сценария.
- Кандидаты с technical similarity, основаниями, pending/confirmed/rejected и пересчётом +20 за 3+ неотклонённых кандидата.

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

**Phase 3:** backend считает уникальные ID pending/confirmed кандидатов. Rejected не участвуют. API возвращает duplicate_detection_status=complete, probable_duplicate_count и duplicate_count_for_scoring с фактическим числом найденных активных кандидатов. Клиент не может прислать собственный count/score. Reasons для +20 содержат ID кандидатов.

При неизвестном scoring-признаке engine возвращает score/priority=null, subtotal известных вкладов и unresolved. Поиск кандидатов не превращает unknown в no. Если AI вернул critical_outage=unknown, оператор сначала проверяет этот признак; до решения итогового HIGH/MEDIUM/LOW нет.

## Architecture / Tech stack

Python 3.12+, FastAPI, Pydantic 2, Jinja2, Uvicorn, HTML/CSS; анализ работает без JavaScript; небольшой script автоматически отправляет изменения признаков, без него есть кнопка пересчёта.

```text
HTML form / JSON API
    → AnalyzeRequest validation
    → AnalysisProvider (mock / OpenRouter)
    → AIAnalysis + evidence validation
    → duplicates.find_candidates (синтетическая история)
    → scoring.calculate_priority
    → OperatorCard → Jinja2 HTML / JSON
    → confirm/reject или feature override → повторный scoring
```

- app/models.py — контракты.
- app/mock_ai.py — сохранённый mock; app/providers/ — общий интерфейс, factory, adapters, prompt и безопасные ошибки.
- app/scoring.py — независимый engine всех четырёх правил.
- app/duplicates.py и app/data/reports.json — deterministic matching и история.
- app/operator_review.py — временные решения оператора и общий пересчёт.
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
3. Увидеть Освещение, четыре pending кандидата, score 70/HIGH: +40 риск, +10 длительность, +20 повторы.
4. Отклонить два кандидата: остаётся два, вклад повторов +0, score 50/MEDIUM. Подтвердить одного отклонённого: снова три и 70/HIGH.
5. Проверить исходные цитаты и structured analysis.
6. Отправить пустое поле — получить понятную ошибку, а не карточку с LOW.

| Пример | Ожидаемый результат в mock |
|---|---|
| Фонарь и искрение | 70 / HIGH (4 кандидата) |
| Нет воды второй день | 40 / MEDIUM |
| Искрение + нет воды второй день | 80 / HIGH |
| Мусор во дворе | 0 / LOW |
| Отрицание искрения и оголённых проводов | 20 / LOW (4 кандидата на неисправную лампу; риска нет) |
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

## Подготовка к раннему deployment на Render

Ранний deployment Phase 2 работает по сообщению пользователя; Phase 3 в этом задании не публикуется. Настройки Python Web Service: Root Directory — корень репозитория (поле можно оставить пустым). Файл .python-version содержит 3.12; не задавайте конфликтующий PYTHON_VERSION в настройках сервиса.

**Build Command**

```bash
pip install -r requirements.txt
```

**Start Command**

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

**Health Check Path:** /health. GET /health возвращает HTTP 200 и {"status":"ok"}. Это проверка работоспособности приложения, не доступности OpenRouter: она не вызывает AI и не требует API key.

Environment variables задать в Render Dashboard:

| Name | Value |
|---|---|
| AI_PROVIDER | openrouter |
| OPENROUTER_API_KEY | Реальный ключ, вводится только в Environment сервиса |
| OPENROUTER_MODEL | openrouter/free |

PORT предоставляет Render; start command использует его значение. Не копировать .env в репозиторий: файл остаётся ignored, ключ в README/исходниках не хранится. .env.example — только пример без секрета.

Production dependencies уже перечислены в requirements.txt: FastAPI, Pydantic, Jinja2, Uvicorn, python-multipart, HTTPX. requirements.lock.txt используется как constraints; наличие там pytest не устанавливает его при production build. requirements-dev.txt нужен только для тестов.

Для текущего временного хранилища карточек использовать один instance и один worker; если WEB_CONCURRENCY задан в environment, установить 1. Рестарт/redeploy очищает карточки и operator overrides — потребуется повторный Analyze. Постоянного хранения, embeddings и SQLite пока нет. История read-only входит в репозиторий; filesystem writes не нужны.

Официальные инструкции: [Render FastAPI](https://render.com/docs/deploy-fastapi), [Python version](https://render.com/docs/python-version), [port binding](https://render.com/docs/web-services#port-binding).

## Deployment / Limitations

Ранний Render deployment подтверждён пользователем; URL не предоставлен, повторная публичная проверка здесь не выполнялась. Без authentication, roles, embeddings, SQLite, карт и интеграций. Карточки, scoring overrides и решения по дубликатам временно хранятся в памяти одного процесса; постоянного хранения нет. В mock режиме результаты синтетические; в openrouter режиме запрос уходит реальному AI. Проверка структуры и вхождения цитат не доказывает смысловую правильность признаков; оператор проверяет результат. Реальную точность/производительность на датасете не оценивали.

## External materials

- Исходные AGENTS.md и docs/HACKATHON_PLAYBOOK.txt существовали до реализации; требования и CASE/PLAN предоставлены/одобрены пользователем.
- Код, HTML/CSS, тесты и синтетические примеры подготовлены с AI-помощью Codex; внешние UI-шаблоны/датасеты не использованы.
- Прямые зависимости: FastAPI (MIT), Pydantic (MIT), Jinja2 (BSD-3-Clause), Uvicorn (BSD-3-Clause), python-multipart (Apache-2.0); HTTP-клиент: HTTPX (BSD-3-Clause); тесты: pytest (MIT). Источники — одноимённые пакеты PyPI; точные установленные версии, включая транзитивные, в requirements.lock.txt.
- Добавлен OpenRouter adapter. Запрашиваемая модель задаётся OPENROUTER_MODEL; для тренировки — openrouter/free. Факт успешного живого вызова указывается отдельно от unit-тестов с mock HTTP.

## Future development / Project documents

CASE.md и PLAN.md отделяют текущую Phase 3 от более широкого целевого MVP. Следующие этапы требуют отдельного запроса: embeddings, постоянная история, улучшение качества и дальнейший deployment. Текущая остановка — review после Phase 3. Commit и push не выполняются.

### Исправление обрезанного ответа OpenRouter

На demo-тексте воспроизведён HTTP 200 с finish_reason=length: лимит 1800 токенов обрезал JSON. Лимит увеличен до 4096, prompt требует компактный JSON и короткие непрерывные цитаты. Для invalid_response добавлены безопасные причины (truncated/json/fields/feature_shape/schema/negative_without_evidence/envelope/incomplete); в логах только code/reason, без ключа, обращения и сырого ответа. Автоматические retry/fallback не добавлены, строгая проверка evidence сохранена.

Проверка после исправления: 148 tests passed. Один реальный запрос с двухстрочным примером про фонарь успешно прошёл Pydantic и exact evidence validation: category=Освещение, subtotal=50, critical_outage=unknown, итоговые score/priority=null. Это ожидаемый результат при недостатке данных, а не ошибка. Ключ прочитан только для запроса из локального .env и не выведен. Ранее записанный пропуск manual test относился к моменту, когда ключ ещё не был доступен.

После изменения файлов перезапустить Uvicorn (или использовать --reload локально). Перед запуском из .env в bash выполнить set -a, source .env, set +a; приложение не загружает .env автоматически.

## История Phase 2 — ручное подтверждение scoring-признаков

В карточке доступны safety_risk и critical_outage (yes/no/unknown), а также длительность: «Нет данных» → unknown, «Менее двух дней» → no, «Два дня и более» → yes. Начальные значения берутся из AI. Изменение автоматически отправляет обычную HTML-форму на backend; без JavaScript доступна кнопка «Пересчитать».

Исходный AIAnalysis, его значения, evidence и review_reasons не изменяются. Текущие решения находятся отдельно в operator_overrides; effective_values показывает значения для расчёта. Любой изменённый признак отмечается operator override, даже если оператор затем выбрал исходное AI-значение. Замечания AI в карточке явно обозначены как исходные.

Backend повторно вызывает существующий app/scoring.py, который не изменялся. Для override основание обозначено как решение оператора и не выдаётся за цитату AI. Повторных AI-вызовов нет. Unknown блокирует final score/priority и оставляет subtotal и список неизвестных признаков. Пример yes/unknown/yes → смена critical_outage на no → 50/MEDIUM; смена на yes → 80/HIGH.

Карточки с исходным AI и последними overrides хранятся только в памяти одного процесса: до 256 карточек, час после создания/последней правки. После перезапуска, истечения срока или вытеснения карточки нужно снова выполнить Analyze; сообщение об этом сохраняет текст формы. Это временное состояние, не постоянная БД и не журнал изменений. Использовать один worker; SQLite, duplicate detection и deployment не добавлены.

Endpoints: POST /cards/{card_id}/features для формы и PATCH /api/cards/{card_id}/features для JSON {field, value}. Клиент не может подменить исходный анализ или прислать готовый score через этот endpoint.

Проверка: полный pytest — 168 passed, два прежних deprecation warnings TestClient. Chrome подтвердил автоматический пересчёт 50/MEDIUM ↔ 80/HIGH ↔ unknown, mapping длительности, сохранность AI, маркеры override и мобильную ширину. За сценарий выполнен только один Analyze. Остановлено на review, commit/push не выполнялись.

## Phase 3 — текущая реализация и границы

Разрешён и реализован только lightweight deterministic поиск кандидатов. Ранний Render deployment предыдущего этапа работает по сообщению пользователя; изменения Phase 3 ещё не опубликованы. Никаких embeddings, дополнительных LLM calls, SQLite, auth, ролей, карт и следующих этапов.

Поток: validated AIAnalysis → app/duplicates.py + app/data/reports.json → кандидаты → прежний scoring engine → карточка → confirm/reject → повторный scoring. 12 синтетических исторических записей, четыре кандидата для основного сценария; история не пополняется вводом пользователя и никогда не перезаписывается. Решения оператора хранятся только в существующей памяти карточки (один процесс, TTL 1 час, максимум 256 карточек).

Совпадение category (кроме «Другое») и нормализованного street/house обязательно. Регистр, пунктуация, пробелы, ул./улица и д./дом нормализуются; ограниченная нормализация окончания ой/ую → ая. Буква дома, дробь, корпус и строение различаются. Нераспознанное место не порождает кандидатов. Текст сравнивается по пересечению множеств слов с небольшим словарём формулировок неисправного освещения; text similarity = 100 × |intersection| / min(|tokens A|, |tokens B|). Для освещения дополнительно нужны признаки неисправности; починенные фонари и различие внутренней лампы/наружного освещения отсекаются.

Пороги в app/duplicates.py: TEXT_SIMILARITY_THRESHOLD=50, DUPLICATE_SIMILARITY_THRESHOLD=80. Итоговый similarity = 20 за категорию + 40 за адрес + 0.4 × text similarity (0–100). Это технический demo score, не вероятность; пороги не калиброваны на реальных обращениях. Сортировка: similarity убывает, затем ID. Все уникальные найденные ID показаны и участвуют в подсчёте.

Pending и confirmed учитываются; rejected сохраняется в карточке, но исключается из count и reasons. Confirm/reject идемпотентны, решение можно изменить; автоматического merge нет. При 3+ активных кандидатах добавляется +20 по существующему правилу. Unknown scoring-признак по-прежнему блокирует итог. Исходные AI features/evidence и operator overrides сохраняются при пересчёте.

Demo: safety=yes, critical=no, multiple_days=yes → четыре pending → 70/HIGH. Один reject → три → 70/HIGH; второй reject → два → 50/MEDIUM. При реальном AI critical=unknown сначала оператор должен принять решение по признаку: до этого только subtotal, без финального HIGH. Подтверждение вместо reject сохраняет вклад.

Ограничения: поверхностное текстовое сравнение, небольшой словарь и адресный парсер, нет геокодирования/полноценной морфологии/проверки времени события; разные объекты у одного дома могут стать кандидатами. Неизвестное место даёт пустую выдачу с объяснением, а не доказательство отсутствия дублей. Требуется человек; новые обращения и связи не сохраняются между перезапусками. Следующие разделы с cosine/embeddings/SQLite описывают прежний целевой MVP и не расширяют scope Phase 3.

API решений: PATCH /api/cards/{card_id}/duplicates/{report_id} с JSON {"status":"confirmed"} или {"status":"rejected"}; HTML-форма — POST /cards/{card_id}/duplicates/{report_id}. Недоступная/истёкшая карточка или неизвестный кандидат возвращает 404; нельзя добавить произвольный исторический ID или изменить AI-данные. Отказ загрузки/валидации встроенной истории блокирует старт приложения, не выдаётся за нулевой count.

Dataset создан синтетически с помощью Codex для этого этапа, без внешних данных и персональных сведений. Новых runtime dependencies нет: matcher использует стандартную библиотеку Python. Исходные проверки Phase 1–2 сохранены; ожидания отключённого поиска и demo score обновлены там, где поведение намеренно изменилось.

### Проверка Phase 3

Полный pytest: **211 passed**, два прежних deprecation warnings Starlette TestClient. Основной сценарий проверен через живой Uvicorn/HTTP в отдельном production-only окружении Python 3.12: HTML Analyze → четыре кандидата / 70 HIGH; два Reject → два / 50 MEDIUM; Confirm → три / 70 HIGH; unknown → subtotal 70 без итогового priority. Проверены /health, CSS и сохранение исходного текста. Runtime использовал mock; дополнительных реальных OpenRouter calls не было. Временный сервер остановлен. git diff --check пройден. Остановка на review; следующие этапы, commit, push и публикация Phase 3 не выполнялись.
