# API backend «Сигнала»

Контракт, который сейчас реализует Go backend (`internal/httpapi`). Его использует frontend
(`frontend/src/api/client.ts`, описание со стороны frontend — `frontend/BACKEND_INTEGRATION_RU.md`
в ветке `frontend`). Новые маршруты появляются только после согласования с frontend.

## Общие правила

- Базовый путь `/api/v1`, JSON в camelCase, модели — `internal/domain/models.go`.
- Даты — RFC 3339. Пустые списки — `[]`, пустой профиль компании — `{}`.
- Ошибка — неуспешный HTTP-статус и тело `{"error": "текст"}`. Текст на русском:
  frontend показывает его пользователю как есть.
- Неизвестный путь под `/api/` — `404 {"error": "Метод API не найден"}`, а не `index.html`.
- Авторизации нет: это прототип, пользователь восстанавливается по сохранённому в браузере `userId`.

| Статус | Когда |
| --- | --- |
| `400` | Некорректный ID в пути, битый JSON, не прошла проверка полей |
| `404` | Нет пользователя или компании |
| `409` | ИНН или email уже зарегистрированы |
| `413` | Загружаемый файл больше 50 МБ |
| `503` | Не настроено файловое хранилище (`S3_ENDPOINT` пуст) |
| `500` | Непредвиденная ошибка (подробности только в логе сервера) |

## Маршруты

| Метод | Путь | Ответ | Ошибки |
| --- | --- | --- | --- |
| `GET` | `/roles` | `200 Role[]` | |
| `GET` | `/profile-elements` | `200 ProfileElement[]` | |
| `POST` | `/companies` | `201 Company` | `400`, `409` |
| `GET` | `/companies/{id}` | `200 Company` | `400`, `404` |
| `PATCH` | `/companies/{id}/profile` | `200 Company` | `400`, `404` |
| `GET` | `/companies/{id}/files` | `200 CompanyFile[]`, новые первыми | `400`, `404` |
| `POST` | `/companies/{id}/files` | `201 CompanyFile` | `400`, `404`, `413`, `503` |
| `POST` | `/users` | `201 User` | `400`, `404`, `409` |
| `GET` | `/users/{id}` | `200 User` | `400`, `404` |
| `PUT` | `/users/{id}/roles` | `200 User` | `400`, `404` |
| `GET` | `/users/{id}/feed` | `200 FeedItem[]` | `400`, `404` |

Служебные: `GET /healthz` (процесс жив), `GET /readyz` (`503`, если нет связи с БД).

## Регистрация

Frontend отправляет два запроса: сначала компания, потом пользователь с её `id`.

### `POST /companies`

```json
{ "inn": "7707083893", "name": "ООО Север" }
```

- `name` обязателен, после обрезки пробелов от 1 до 160 символов.
- `inn` — 10 или 12 цифр. Контрольная сумма не проверяется.
- `ogrn` необязателен, если передан — 13 или 15 цифр. `profile` необязателен.
- Повторный ИНН → `409 {"error": "Компания с таким ИНН уже зарегистрирована"}`.

### `POST /users`

```json
{ "fullName": "Анна Петрова", "email": "anna@example.ru", "companyId": 17, "roles": ["ceo", "cfo"] }
```

- `fullName` обязателен, до 120 символов; `email` — вида `x@y.z`, до 320 символов.
  Пробелы по краям обрезаются (как во frontend).
- `companyId` может быть `null`; несуществующая компания → `404 {"error": "Компания не найдена"}`.
- `roles` — коды из `/roles`, неизвестные коды пропускаются. В ответе фактический набор ролей.
- Повторный email → `409 {"error": "Пользователь с такой электронной почтой уже зарегистрирован"}`.
- Пользователь и его роли создаются одной транзакцией: неудачная попытка email не занимает.

Если `POST /users` вернул ошибку, компания уже создана. Frontend хранит её `id` и при повторе
отправляет только `POST /users`, поэтому после `409` по email достаточно исправить почту.

## Роли

`PUT /users/{id}/roles` с телом `{"roles": ["strategy", "cfo"]}` заменяет набор ролей целиком
и возвращает пользователя. Неизвестные коды пропускаются, пустой массив снимает все роли.

## Лента

`GET /users/{id}/feed?role=cfo&limit=200`

- `role` необязателен: без него лента по всем ролям пользователя.
- `limit` от 1 до 200, по умолчанию 50; больше 200 обрезается до 200.
- Порядок: сначала свежие новости (`news.publishedAt`), при равенстве — выше `score`.
- `kind` — `event`, `risk` или `opportunity`; `score` — релевантность `0…1`; `elements` — всегда массив.
- Несуществующий пользователь → `404`; у существующего без записей — `[]`.

## Файлы компании

`POST /companies/{id}/files` — `multipart/form-data`, поле строго `file`, до 50 МБ.
Компания проверяется до записи в хранилище, поэтому `404` не оставляет файлов-сирот.
Ответ подтверждает только сохранение файла: обработка документов пока не реализована.

## Модели

```json
// Role
{ "id": 5, "code": "cfo", "name": "Финансовый директор", "question": "…", "focus": "…", "elements": ["Б2", "Б3"] }

// ProfileElement
{ "code": "Б2", "block": "Бизнес", "name": "…", "description": "…", "purpose": "…" }

// Company
{ "id": 17, "inn": "7707083893", "ogrn": "", "name": "ООО Север", "profile": {},
  "createdAt": "2026-10-22T08:55:00Z", "updatedAt": "2026-10-22T08:55:00Z" }

// User
{ "id": 23, "companyId": 17, "email": "anna@example.ru", "fullName": "Анна Петрова",
  "roles": ["ceo", "cfo"], "createdAt": "2026-10-22T09:00:00Z" }

// FeedItem
{ "id": 101, "role": "cfo", "kind": "risk", "score": 0.96, "insight": "…", "elements": ["Б3"],
  "news": { "id": 1001, "sourceId": "S015", "url": "https://…", "title": "…", "summary": "…",
            "publishedAt": "2026-10-22T10:30:00Z" },
  "createdAt": "2026-10-22T10:35:00Z", "readAt": null }

// CompanyFile
{ "id": 7, "companyId": 17, "filename": "бюджет-2027.pdf", "contentType": "application/pdf",
  "sizeBytes": 1842903, "createdAt": "2026-10-22T11:00:00Z" }
```

## Проверка

Тесты контракта (`internal/httpapi/api_test.go`) идут против настоящего PostgreSQL и без
`TEST_DATABASE_URL` пропускаются, в том числе в CI:

```bash
docker run -d --rm --name alpha-test-pg -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app \
  -e POSTGRES_DB=alpha -p 127.0.0.1:55432:5432 postgres:16-alpine
TEST_DATABASE_URL='postgres://app:app@localhost:55432/alpha?sslmode=disable' go test ./...
docker stop alpha-test-pg
```
