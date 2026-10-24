# Аудит пайплайна, 23 октября 2026

Исторический отчёт до подключения к приложению. Интеграция в main и актуальные
проверки описаны в [отчёте от 24 октября](integration-main-2026-10-24.md).

Проверена ветка `ai-orchestrator`, исходный commit `fff8580`. Перед работой выполнен
fetch; локальная ветка совпадала с remote. Аудит охватил Python orchestrator,
analytics, parser_service, Go ingestion/storage/API, React и manifests зависимостей.
Три агента выполняли отдельные задачи с Ponytail и Agent Skills; основной агент
проверял границы компонентов, зависимости, изменения и результаты.

Аналитический `create_router` по-прежнему не зарегистрирован в рабочих приложениях.
Все HTTP/БД/модельные проверки используют временные приложения, базы и transports.
Командные ключи, рабочие БД, модельные API, кластер и deployment не использовались.

## Подтверждённые дефекты и исправления

| Область | Дефект | Исправление и проверка |
| --- | --- | --- |
| Профиль → пересчёт | Сбой после сохранения профиля оставлял изменение без job; одинаковый повтор не восстанавливал job | Профиль и постановка задания в одной транзакции; идентичный повтор восстанавливает отсутствующее задание |
| Конкурентная очередь analytics | Запоздалое создание/retry могло перезаписать завершённую job в queued | Создание с `expected_version=0`; после конфликта читается победитель; retry перечитывает статус под lock. Тесты воспроизводят оба порядка исполнения |
| Advisory locks | Истечение PostgreSQL statement timeout при конкуренции становилось неожиданной ошибкой | `StoreBusy`, HTTP 503; worker откладывает работу без расхода попытки. Общий statement timeout сохранён |
| Snapshot | Неизменные версии issues преждевременно прекращали refresh и оставляли старую временную метку/границу обработанного архива | Обновляются метаданные; synthesis переиспользует текст без дополнительного LLM-вызова |
| Кеш impact | Смена извлечённых chunks при той же версии профиля возвращала прежнюю оценку | Fingerprint включает весь фактический evidence и текущую версию retriever; исключён только `as_of`, чтобы часы сами не запускали платный пересчёт |
| Размер assessment | Допустимые 12 фактов/chunks могли превысить стандартные 32 000 символов запроса | Общий с LLMClient построитель считает полный JSON, инструкцию и схему. Слишком большой полный контекст сохраняется как `needs_context/context_limit` без модельного вызова; факты и оговорки не обрезаются. Необязательный триаж не вытесняет primary evidence |
| Ответы моделей | Malformed HTTP 200 мог приводить к AttributeError/KeyError или записываться как успешный вызов | Проверка формы ChatCompletion, choice/message/content и finish_reason до публикации/учёта успеха |
| System One | Ответ полностью буферизовался без cap; общий lock создавал неограниченное ожидание следующих запросов | Streaming cap 1 МиБ, identity encoding, отказ до чтения тела HTTP-ошибки; ожидание lock ограничено настроенным timeout, затем применяется существующий fallback |
| PDF/DOCX | Native-заголовок скрывал сканированное тело; геометрия и многократное использование сжатого текста увеличивали память до проверки лимита | Partial/full OCR; 25 млн пикселей/страницу и 200 млн/документ до OCR. Лимит текста проверяется при добавлении каждого сегмента, до общей склейки |
| Документы | Разобранный документ можно было сохранить с другими исходными байтами или подменёнными chunks | `source_digest`/`parsed_text_digest`, проверка offsets, текста, hash, namespace и уникальности chunk ID до записи. Прямой ingest соблюдает лимиты парсера; старые записи читаются благодаря nullable digest-полям |
| Embeddings | Модель с `max_seq_length=128` молча теряла хвост длинных chunks | Token windows, проверка длины после decode, взвешенная нормализованная агрегация. Явный атомарный `KnowledgeService.reindex(scope)` обновляет текущие chunks/facts без новых ревизий и без повторного extraction |
| Retrieval | Повторное чтение историй каждого документа и отдельных chunks, затем повтор того же обхода для графа | Scoped `histories` одним SQL, одна загрузка chunks на retrieval, повторное использование внутри graph path search |
| Граф | Второй hop терялся из-за регистра/пробелов/Unicode в ID, alias-цикл мог стать ложным путём; каждый узел сканировал все рёбра | NFC и канонические ключи на каждом hop, проверка циклов, индекс смежности; отдельные RED→GREEN fixtures |
| Graphify и интервалы | Даты импортированных рёбер не проверялись так же, как результаты обычного extraction; принимались обратные/пустые интервалы | Переиспользован существующий validator цитат/ссылок/дат, добавлено общее `valid_from < valid_until` для KnowledgeEdge |
| HTML | Глубокая повреждённая разметка приводила к квадратичному поиску по stack | Индекс frames по tag и счётчик ignored depth; сохранены существующие structural extraction tests |
| Safe fetch | Chunked/unknown-length тело ровно на cap отвергалось как слишком большое | Проверка EOF одним дополнительным байтом; cap принимается, cap+1 отвергается |
| Go `/rank` | Принимались чужие/повторные роли, неизвестный kind, некорректный score, trailing JSON и неограниченный ответ; полный body новости терялся в JSON | Cap 1 МиБ, whole-document JSON, валидация массива и каждого match; additive `body` в запросе. RoundTripper tests без внешней сети |
| Go news → feed | После Rank/DB ошибки сохранённая новость больше не обрабатывалась; исправления не обновляли полный текст/инсайты | Транзакционная очередь по news revision/user, bounded claim, backoff, lease/fencing, failed после 8 ошибок. Исправление немедленно скрывает старый инсайт, успешный результат атомарно заменяет набор feed rows, сохраняя read_at |
| Go роли/результаты | Снятая роль могла остаться в ленте или попасть туда из запоздалого Rank; nil elements не проходили NOT NULL | Проверка ролей и смена ролей сериализованы на user row, Feed фильтрует текущие роли; nil elements нормализуются в пустой массив |
| Legacy RSS | Даже обычный GMT мог заменяться временем fetch; пустой ID объединял разные новости; HTML-ошибка могла выглядеть пустой RSS | RFC date parsing с явным timezone, неизвестная дата/ID/title отвергаются, проверяется root `rss`, cap 8 МиБ. Неизвестное время не выдумывается |
| Alfa adapter | Нереализованный адаптер сообщал успешный пустой результат | Явная ошибка отсутствующего контракта источника; адаптер не изображает реальную интеграцию |
| Legacy JSON API | JSON тела четырёх endpoints не имели ограничения | Cap 1 МиБ до storage; отдельные тесты oversized bodies |
| Регистрация | Компания создавалась отдельно от пользователя, сбой второго запроса оставлял orphan и ломал retry | Один транзакционный `/api/v1/onboarding`, idempotency key + hash; rollback, replay, concurrency и конфликт проверяются на временной PostgreSQL. Новый endpoint требует роли; retry key очищается после подтверждённого успеха |
| Интерфейс | Ошибки API оставляли вечную загрузку/пустую страницу; некорректный user ID попадал в запросы; feed URL мог содержать javascript/data | Явные ошибки и повтор, safe integer ID, ссылки только HTTP(S). Проверено в браузере с mock API |

Проверка Go `return out, Decode(&out)` не подтвердила предполагаемую ошибку порядка
вычисления. Этот вывод не включён в исправленные дефекты; сохранён тест корректного
декодирования. Наличие подозрительного выражения само по себе не считалось доказательством.

## Измерения

Измерения локальные, на синтетических данных. Они не заменяют sizing рабочей системы.

| Сценарий | До | После | Смысл |
| --- | --- | --- | --- |
| Retrieval, 40 документов/40 chunks, MemoryStore | 164 Store-вызова, median 3,037 мс | 4 вызова, median 1,882 мс | Убран N+1; это не измерение PostgreSQL throughput |
| Graph paths, 1 000 рёбер | 0,377 с | 0,011 с | 500 путей в обоих случаях |
| Graph paths, 2 000 рёбер | 1,500 с | 0,019 с | 1 000 путей в обоих случаях |
| Graph paths, 5 000 рёбер | 9,395 с | 0,060 с | 2 500 путей в обоих случаях |
| HTML, 6 000 незакрытых/несогласованных tags, около 42 КБ | 2,787 с | 0,0173 с | Убран квадратичный проход stack; 12 000 tags после исправления — 0,0318 с |
| Локальный embedding, два входа по 442 токена, warm CPU median 8 запусков | 18,29 мс с усечением | 40,50 мс с полным покрытием | Дополнительное время оплачивает обработку хвоста, это исправление полноты, а не ускорение |

Graph benchmark воспроизводится командой
`python -m orchestrator.analytics.tests.perf.benchmark_graph_paths`.
Локальная pinned multilingual модель разбила 442 токена на окна 128/128/128/67
(со специальными токенами); изменение последнего слова изменило 384-мерный вектор.
Прежние векторы не смешиваются с `:token-windows-v1`: требуется новая индексация
документов. До неё остаются лексические каналы. Retriever identity также изменена.

## Зависимости и чистая установка

Проверялись установленные Python-пакеты, npm lockfile и Go module graph с анализом
вызываемых символов. Это проверка известных advisories на дату отчёта, а не доказательство
отсутствия неизвестных уязвимостей в исходниках всех сторонних проектов.

- Конфликт FastAPI `0.156.2`/`0.156.8` воспроизведён чистым resolver: два requirements
  нельзя было поставить вместе. Pin orchestrator выровнен на `0.156.8`; установка
  analytics + parser requirements в новый venv и `pip check` проходят.
- `pip-audit` первоначально нашёл advisories в локальном pip 25.0.1, но не в пакетах
  приложения. Инструмент обновлён до 26.2.2; повторная проверка всех 97 установленных
  пакетов, включая optional embeddings, дала **0 известных уязвимостей**.
  Инструмент окружения не объявлен runtime-зависимостью приложения.
  Отдельная повторная проверка нового чистого venv: **70 пакетов, 0 findings**.
- `govulncheck`: до исправления 44 module-level advisories, из них 3 в вызываемых
  символах. Обновлены pgx 5.9.2, compress 1.18.7, x/net 0.60.0 и согласованные
  транзитивные x/crypto 0.57.0, x/text 0.42.0, x/sys/x/sync. Сборка/CI/Docker используют
  Go 1.27.3. После обновления **0 package/call-level findings**; один module-only
  advisory относится к неимпортируемому устаревшему `x/crypto/openpgp` без исправленной
  версии. Добавлять его в приложение нельзя.
- npm сначала показал 2 moderate findings в цепочке React Router. Версия обновлена
  с 6.30.6 до 7.18.4; React 18 и Node 22+ удовлетворяют требованиям. BrowserRouter,
  переходы и onboarding проверены с новой версией; повторный `npm audit` — **0 findings**.

Источники исправлений: [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/#01568),
[pip release notes](https://pip.pypa.io/en/stable/news/),
[pgx placeholder advisory](https://pkg.go.dev/vuln/GO-2026-5004),
[x/text invalid UTF-8](https://pkg.go.dev/vuln/GO-2026-5970),
[x/text panic](https://pkg.go.dev/vuln/GO-2026-6629),
[неиспользуемый OpenPGP](https://pkg.go.dev/vuln/GO-2026-5932),
[React Router open redirect](https://github.com/remix-run/react-router/security/advisories/GHSA-wrjc-x8rr-h8h6),
[React Router SSR hydration](https://github.com/remix-run/react-router/security/advisories/GHSA-337j-9hxr-rhxg).

## Сверка спецификации и границ интеграции

| Требование | Реализация и доказательство | Граница |
| --- | --- | --- |
| Статьи → события, версии, исправления/отмена | analytics service + acceptance tests | Parser material → NewsArticle ещё требует согласованного mapping; неизвестный published_at нельзя подменять временем fetch |
| Документы → факты/связи → evidence | knowledge tests, реальный OCR, digest checks | Citation match подтверждает источник цитаты, но не семантическую истинность утверждения |
| Tenant/company/user isolation | scoped Store, router tests, scoped histories | Рабочая auth-зависимость должна быть внедрена при совместном подключении; legacy Go пока без auth |
| System One → полный assessment | integration tests и оба PG demo режима | Триаж advisory, не основание автоматически скрывать новость или заменять полную оценку |
| CompanyImpact → mixed BusinessIssue → Snapshot | service/synthesis/acceptance tests, demo | Численные вероятности и деньги не суммируются; неизвестное остаётся неизвестным |
| Чтение, история, чат, user state | router/service tests, read_calls=0 в demo | Чат проверен с синтетической моделью; live качество отдельно |
| Restart, retries, бюджет, leases | PG checkpoints, конкурентные tests, два временных worker-а | Настоящий scheduler/worker deployment не подключён |
| A/B/C/Graphify comparison | существующий evaluation harness и fixtures | Нет размеченной выборки, доказывающей пользу графа или качество живой модели |

## Воспроизводимые проверки

| Проверка | Результат |
| --- | --- |
| Core orchestrator, новый Python 3.12 venv, отдельная PostgreSQL | 112 тестов, 0 пропусков |
| Analytics, PostgreSQL + pgvector + OCR | 118 тестов, 0 пропусков |
| Parser, отдельная PostgreSQL | 125 тестов, 0 пропусков |
| Go 1.27.3, две отдельные БД, `go test -race -count=1 -v ./...` | 28 тестовых функций / 52 случая с subtests, 0 пропусков; race detector не выявил гонок в выполненных сценариях |
| Go `vet`, Linux amd64 `CGO_ENABLED=0` сборка server/worker | Успешно |
| Frontend TypeScript + Vite | Сборка успешна; браузерный smoke с временным mock API: навигация, ошибки/retry, onboarding/replay, invalid IDs, безопасные URL |
| Workflow syntax и Helm | actionlint успешен; Helm 4.3.1 lint `--strict` и render успешны; GitHub CI/кластер не запускались |
| Reindex: настоящая локальная модель + PostgreSQL/pgvector | 2 строки обновлены, обе найдены vector search; версия компании не изменилась, дополнительных LLM-вызовов нет |
| Сквозной PostgreSQL + PostgresSaver demo, режимы systemone/fallback | В каждом: 3 события, 1 mixed issue, 4 версии issue, `read_calls=0`; 6 завершённых triage, фактический provider соответственно systemone/llm |

Всего **355 Python-тестов**. PostgreSQL suites используют разные базы: core fixtures
содержат намеренно неполные records и не должны попадать в analytics suite.
Регрессии проверялись сначала на старом поведении; дополнительно удаление streaming
cap в временном in-memory mutation воспроизвело провал теста. Проверка пустых ролей
через Go overlay также дала ожидаемые 201 вместо 400 до исправления.

После подготовки зависимостей, OCR assets и отдельных тестовых баз:

```bash
ANALYTICS_TEST_DATABASE_URL="$CORE_TEST_DSN" python -m unittest discover -s orchestrator/tests -q
ANALYTICS_TEST_DATABASE_URL="$ANALYTICS_TEST_DSN" python -m unittest discover -s orchestrator/analytics/tests -q
PARSER_TEST_DATABASE_URL="$PARSER_TEST_DSN" python -m unittest discover -s parser_service/tests -q
# Из backend/; только loopback, базы alpha_test и analytics_test_audit_backend.
ALPHA_TEST_DATABASE_URL="$ONBOARDING_TEST_DSN" INGEST_TEST_DATABASE_URL="$INGEST_TEST_DSN" go test -race -count=1 -v ./...
go vet ./...
# Из frontend/
npm ci
npm run build
```

Reusable workflow `.github/workflows/pipeline-tests.yml` поднимает PostgreSQL,
готовит pinned OCR и запускает все три Python suite и Go с race detector. Пропуски
тестов считаются ошибкой; shell включает pipefail, поэтому `tee` не скрывает сбой.
Он включён обязательным prerequisite существующего CI/CD до сборки/push образа.

## Изменения поведения и эксплуатация

Миграция Go `0003_news_delivery.sql` добавляет revision, active и `news_deliveries`;
`0004_onboarding.sql` — журнал идемпотентной регистрации. Существующие feed rows
остаются видимыми после миграции, пока не изменится источник или набор ролей.
Claim выполняется по одной записи: до 100 до fetch и до 100 после него. Lease 2 минуты
не тратится на ожидание остальных Rank-запросов; backoff 5/10/20/40/80/160/300 секунд,
фактический повтор также зависит от периода worker. Восьмая ошибка или истёкший lease
завершает задание как failed; смена ролей не расходует этот счётчик. Новые ревизии
получают собственные задания. Для осознанного повтора после устранения причины:

```sql
UPDATE news_deliveries
SET state='pending', failures=0, last_error='', lease_until=NULL,
    next_attempt_at=now(), updated_at=now()
WHERE id = :delivery_id AND state='failed';
```

Исторический backfill, новые пользователи и изменение профиля в legacy Go-контуре
автоматически не запускают пересчёт архива. Это отдельная граница интеграции;
аналитический Python-контур уже имеет явные reprocess jobs. Строгий RSS adapter
теперь отвергает ошибочный feed/item вместо подстановки текущего времени. В Python
parser неизвестная дата сохраняется неизвестной до согласованного mapping.

После смены модели embeddings используйте `service.knowledge.reindex(scope)` на
настроенном KnowledgeService и явный `service.reprocess_company(scope,
reason='embedding-reindex')`, если требуется обновить оценки. Reindex не меняет
факты, документы и ревизии; при ошибке индекс публикуется целиком либо не меняется.
Пересчёт оценки выполняет worker отдельно. Большие документы всё ещё должны
укладываться в настроенный лимит extraction-запроса; автоматическое смысловое
разбиение договоров с оговорками не добавлялось.

## Остаточные ограничения перед совместным подключением

1. Наличие цитаты и даты внутри неё не доказывает отрицание/утверждение или роль даты
   «начало/окончание». Нужна размеченная проверка extraction/assessment на реальных
   данных; ненадёжная regex-проверка смысла не добавлялась. `source_supported` здесь
   означает проверенную ссылку/цитату, а не независимое подтверждение истинности.
2. Analytics router остаётся изолированным. Нужно согласовать ingestion mapping,
   auth/ACL, service-token boundary, API для mixed issues и UI. У legacy Go `/rank`
   по-прежнему таймаут 30 с и нет передачи service token; он не подключён к новому
   analytics router. Прямой TypeSafe endpoint не является нашим `/rank`.
3. AlfaFetcher не имеет контракта живого источника. CBR live-доступ ранее получал 403;
   запрет не обходился. Универсальный поиск, material-version registry и внешний
   Graphify extractor не реализованы этим аудитом.
4. Для большого корпуса остаются линейная загрузка histories/records, повторная
   сборка BM25, массовый пересчёт архива и хранение JSONB-истории. Следующие оптимизации
   выбираются по PostgreSQL EXPLAIN/нагрузке: server-side pagination, batched evidence
   reads, incremental index/cache и ограниченная очередь компаний. Прототип не получил
   неподтверждённый производственный SLA.
5. HTTPX read timeout ограничивает бездействие при чтении, а не полное wall-clock
   время медленно поступающего ответа. Cap и ограниченное ожидание lock устранены
   как отдельные риски; жёсткий общий deadline/отмена провайдера требуют отдельного
   runtime решения. Длительная OCR/extraction также требует sizing/изоляции worker-а.
6. Docker daemon отсутствовал в локальном окружении. Helm 4.3.1 установлен во временную
   папку из [официального архива](https://helm.sh/docs/intro/install/) с проверкой SHA-256; `helm lint --strict` и render
   прошли без обращения к кластеру. Полный Docker image и CI на GitHub нельзя считать
   выполненными только по локальным тестам. Deployment не запускался.

Дальнейшее подключение потребует живого smoke с выделенным бюджетом и реальной
инфраструктурой. Текущие результаты подтверждают изолированный прототип и перечисленные
регрессии; они не являются обещанием отсутствия любых будущих сбоев или UB в native dependencies.
