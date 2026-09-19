# Городской помощник — Phase 1

Локальный end-to-end прототип: текст обращения → валидация → mock AI features → deterministic scoring → одна карточка оператора. Настоящий AI, поиск дублей, сохранение и deployment не реализованы.

## Problem / Target users / Value

Оператор городской службы вручную читает жалобы, определяет категорию и приоритет. Прототип показывает структуру будущего рабочего процесса и объяснение расчёта. Эффективность на реальных обращениях пока не измерена.

## Solution / Key features

- Форма обращения и кнопка Analyze, валидация 1–5 000 символов после trim.
- Pydantic-контракт: category, summary, location, event_time_text, ongoing, safety_risk, critical_outage, persists_multiple_days, review_reasons.
- Признаки содержат value yes/no/unknown и evidence — точные цитаты входного текста.
- Карточка: категория, краткое извлечение из текста, место, score, priority, reasons с баллами/цитатами и раскрываемый structured analysis.
- Шесть синтетических примеров; явная ошибка пустого ввода; API для того же сценария.

## AI role

В Phase 1 используется **mock по ограниченным regex-шаблонам**, не реальный AI. Mock возвращает только AIAnalysis, без score, priority или числа дублей. Summary — первые 280 символов текста, а не генеративная сводка; категории и адрес извлекаются упрощённо. Нет сетевых AI-вызовов и ключей.

Замена mock на реального провайдера должна возвращать тот же AIAnalysis. Проверка цитат и scoring остаются в приложении независимо от провайдера. В mock отсутствие совпадения трактуется как no только для демонстрации; это не доказательство отсутствия риска. Некоторые отрицания/неопределённость обрабатываются, произвольный естественный язык не гарантируется.

## Priority — demo rules

Это демонстрационная модель, **не реальные нормативы городской службы**.

| Признак | Баллы |
|---|---:|
| Safety risk | +40 |
| Critical infrastructure/service outage | +30 |
| Три и более probable duplicate reports | +20 |
| Проблема длится минимум два дня | +10 |

Каждый вклад начисляется один раз. 0–29 LOW; 30–59 MEDIUM; 60+ HIGH. Причины включают только сработавшие правила.

**Граница Phase 1:** поиска дублей нет. Backend явно передаёт в engine count=0, а UI предупреждает, что вклад отключён. В API probable_duplicate_count=null (не измерен), duplicate_count_for_scoring=0, duplicate_detection_status=disabled_phase1. Это не утверждение «дублей нет». Правило +20 реализовано в том же engine и проверяется unit-тестами на синтетическом count; API не принимает count от пользователя.

При неизвестном scoring-признаке engine возвращает score/priority=null, subtotal известных вкладов и unresolved. Для будущего поиска неизвестный count=None также блокирует итог, а не подменяется нулём. Подсчёт уникальных кандидатов и их ID будет ответственностью будущего duplicate detection, а не mock или scoring.

## Architecture / Tech stack

Python 3.12+, FastAPI, Pydantic 2, Jinja2, Uvicorn, HTML/CSS; форма работает без JavaScript.

```text
HTML form / JSON API
    → AnalyzeRequest validation
    → mock_ai.analyze → AIAnalysis + evidence validation
    → scoring.calculate_priority
    → OperatorCard → Jinja2 HTML / JSON
```

- app/models.py — контракты.
- app/mock_ai.py — временный поставщик признаков.
- app/scoring.py — независимый engine всех четырёх правил.
- app/main.py — общая сборка карточки для формы и API.
- app/examples.py — синтетические тексты.
- app/templates/index.html и app/static/style.css — UI.

## How to run locally

Из bash, Python 3.12+:

```bash
cd /home/batyr/projects/hackathon-training
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Открыть http://127.0.0.1:8000. OpenAPI: http://127.0.0.1:8000/docs.
Остановка — Ctrl+C. Для запуска без тестовых инструментов установить только requirements.txt. Версии зависимостей зафиксированы в requirements.lock.txt; основные зависимости перечислены отдельно, lock используется как constraints.

## Environment variables

Не требуются. .env исключён из Git; AI API-ключи на этом этапе не используются.

## Main scenario / Demo data

1. Открыть главную страницу.
2. Выбрать «Фонарь и искрение», затем Analyze.
3. Увидеть Освещение, score 50, MEDIUM, причины +40 за риск и +10 за длительность.
4. Проверить исходные цитаты и structured analysis.
5. Отправить пустое поле — получить понятную ошибку, а не карточку с LOW.

| Пример | Ожидаемый результат в Phase 1 |
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
curl -s http://127.0.0.1:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"text":"Провод искрит второй день."}'
```

## Tests

```bash
cd /home/batyr/projects/hackathon-training
.venv/bin/python -m pytest -q
```

Unit: все 16 комбинаций правил, границы score, порог 2/3 дубля и однократное начисление, неизвестные признаки, неверные аргументы, пересчёт без мутации. Integration: общая цепочка для HTML и API, все demo-классы, пустой/длинный ввод, неизвестность, проверка цитат, экранирование HTML и ошибки анализа.

Проверено на Python 3.12.3: **61 passed**; pip check — без конфликтов. На живом Uvicorn проверены HTML/API, LOW/MEDIUM/HIGH, unknown и пустой ввод 422. В Chrome проверены выбор примера → Analyze → 50/MEDIUM и две причины, structured analysis, мобильная ширина 390px и пустой ввод. Два предупреждения deprecation относятся к Starlette TestClient (HTTPX/AnyIO), не к сбоям приложения.

## Deployment / Limitations

Публичного deployment нет. Только локальный запуск, без authentication, roles, embeddings, duplicate detection, SQLite, карт и интеграций. Данные не сохраняются; подтверждение дублей и исправления в UI пока отсутствуют. Все результаты mock; реальную точность/производительность AI не оценивали.

## External materials

- Исходные AGENTS.md и docs/HACKATHON_PLAYBOOK.txt существовали до реализации; требования и CASE/PLAN предоставлены/одобрены пользователем.
- Код, HTML/CSS, тесты и синтетические примеры подготовлены с AI-помощью Codex; внешние UI-шаблоны/датасеты не использованы.
- Прямые зависимости: FastAPI (MIT), Pydantic (MIT), Jinja2 (BSD-3-Clause), Uvicorn (BSD-3-Clause), python-multipart (Apache-2.0); тесты: pytest (MIT), HTTPX (BSD-3-Clause). Источники — одноимённые пакеты PyPI; точные установленные версии, включая транзитивные, в requirements.lock.txt.
- Продуктовые AI-модели не подключены.

## Future development / Project documents

CASE.md и PLAN.md описывают целевой MVP шире Phase 1. Следующие этапы требуют отдельного запроса: реальный AI, semantic duplicate detection, подтверждение оператором, история и deployment. Текущая остановка — после проверки Phase 1. Commit и push не выполняются.
