-- Базовая схема: пользователи, роли, компании, профиль, источники, новости, лента.

CREATE TABLE companies (
    id          BIGSERIAL PRIMARY KEY,
    inn         VARCHAR(12) NOT NULL UNIQUE,
    ogrn        VARCHAR(15),
    name        TEXT        NOT NULL,
    -- Профиль компании: ключ = ID элемента из справочника profile_elements (И1, Б3, ...),
    -- значение = произвольный JSON с данными элемента.
    profile     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id          BIGSERIAL PRIMARY KEY,
    company_id  BIGINT      REFERENCES companies(id) ON DELETE SET NULL,
    email       TEXT        NOT NULL UNIQUE,
    full_name   TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Справочник ролей директоров (лист «2. Роли директоров»).
CREATE TABLE roles (
    id          SMALLSERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    question    TEXT NOT NULL DEFAULT '',
    focus       TEXT NOT NULL DEFAULT ''
);

-- Один пользователь может совмещать несколько ролей.
CREATE TABLE user_roles (
    user_id     BIGINT   NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id     SMALLINT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

-- Справочник элементов профиля компании (лист «1. Профиль компании»).
CREATE TABLE profile_elements (
    code        TEXT PRIMARY KEY,           -- И1, Б3, Г2, С4, О1 ...
    block       TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    purpose     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE role_profile_elements (
    role_id      SMALLINT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    element_code TEXT     NOT NULL REFERENCES profile_elements(code) ON DELETE CASCADE,
    PRIMARY KEY (role_id, element_code)
);

-- Источники новостей и данных (лист «3. Источники»).
CREATE TABLE sources (
    id          TEXT PRIMARY KEY,           -- S001 ...
    category    TEXT NOT NULL,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL DEFAULT '',
    api_access  TEXT NOT NULL DEFAULT '',
    -- Тип адаптера сборщика: alfa, rss, http_json, manual. NULL = не собирается автоматически.
    adapter     TEXT,
    config      JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled     BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE source_profile_elements (
    source_id    TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    element_code TEXT NOT NULL REFERENCES profile_elements(code) ON DELETE CASCADE,
    PRIMARY KEY (source_id, element_code)
);

-- Сырые новости и аналитика из всех источников.
CREATE TABLE news_items (
    id           BIGSERIAL PRIMARY KEY,
    source_id    TEXT        NOT NULL REFERENCES sources(id),
    external_id  TEXT        NOT NULL,
    url          TEXT        NOT NULL DEFAULT '',
    title        TEXT        NOT NULL,
    summary      TEXT        NOT NULL DEFAULT '',
    body         TEXT        NOT NULL DEFAULT '',
    published_at TIMESTAMPTZ NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw          JSONB,
    UNIQUE (source_id, external_id)
);
CREATE INDEX news_items_published_at_idx ON news_items (published_at DESC);

-- Персонализированная лента: результат фильтрации/ранжирования моделью
-- для пары (пользователь, роль). Одна новость может попасть в ленту нескольких ролей.
CREATE TABLE feed_items (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id     SMALLINT    NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    news_id     BIGINT      NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
    kind        TEXT        NOT NULL DEFAULT 'event' CHECK (kind IN ('event', 'risk', 'opportunity')),
    score       REAL        NOT NULL DEFAULT 0,
    insight     TEXT        NOT NULL DEFAULT '',
    -- Какие элементы профиля «сработали» (для объяснения, почему новость в ленте).
    elements    TEXT[]      NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at     TIMESTAMPTZ,
    UNIQUE (user_id, role_id, news_id)
);
CREATE INDEX feed_items_user_idx ON feed_items (user_id, created_at DESC);

-- Метаданные файлов; сами файлы лежат в объектном хранилище (MinIO / S3).
CREATE TABLE company_files (
    id           BIGSERIAL PRIMARY KEY,
    company_id   BIGINT      NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    object_key   TEXT        NOT NULL UNIQUE,
    filename     TEXT        NOT NULL,
    content_type TEXT        NOT NULL DEFAULT 'application/octet-stream',
    size_bytes   BIGINT      NOT NULL,
    uploaded_by  BIGINT      REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
