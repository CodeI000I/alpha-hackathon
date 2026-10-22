-- Очередь оценок новостей AI-оркестратором и первые RSS-источники.

-- Одна оценка на пару (новость, компания) по объединению ролей её директоров.
-- Воркер повторяет неудачные оценки (attempts, next_attempt_at), а готовый ответ (matches)
-- раскладывает по лентам всех директоров компании с подходящей ролью.
CREATE TABLE news_rankings (
    news_id         BIGINT      NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
    company_id      BIGINT      NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    status          TEXT        NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'failed')),
    attempts        INT         NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    error           TEXT        NOT NULL DEFAULT '',
    -- Роли, по которым оценено; новая роль у директоров компании отправляет новость на переоценку.
    roles           TEXT[]      NOT NULL DEFAULT '{}',
    -- Ответ оркестратора: [{"role", "kind", "score", "insight", "elements"}].
    matches         JSONB       NOT NULL DEFAULT '[]'::jsonb,
    -- Время постановки в очередь: сначала оцениваются задачи последнего прохода (в том числе импорт).
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (news_id, company_id)
);
CREATE INDEX news_rankings_due_idx ON news_rankings (next_attempt_at) WHERE status = 'pending';

-- Источник для служебного импорта (POST /api/v1/internal/news), когда sourceId не указан.
INSERT INTO sources (id, category, name, url, api_access, adapter, enabled)
VALUES ('manual', 'Служебные', 'Ручной импорт новостей', '', 'POST /api/v1/internal/news', NULL, false)
ON CONFLICT (id) DO NOTHING;

-- RSS-ленты источников с пометкой RSS в листе «3. Источники». Адреса проверены 22.10.2026,
-- кроме government.ru: ссылка взята из подвала сайта, сама лента извне не открылась.
-- У S112 (bcs-express.ru), S143 (business-gazeta.ru), S145 (tadviser.ru) и S146 (portnews.ru)
-- рабочей ленты не нашли, они остаются выключенными.
UPDATE sources SET config = config || jsonb_build_object('feed_url', v.feed_url), enabled = true
FROM (VALUES
    ('S085', 'http://government.ru/all/rss/'),
    ('S086', 'http://kremlin.ru/events/all/feed'),
    ('S136', 'https://www.interfax.ru/rss'),
    ('S137', 'https://tass.ru/rss/v2.xml'),
    ('S138', 'https://1prime.ru/export/rss2/index.xml'),
    ('S139', 'https://rssexport.rbc.ru/rbcnews/news/30/full.rss'),
    ('S140', 'https://www.kommersant.ru/RSS/news.xml'),
    ('S141', 'https://www.vedomosti.ru/rss/news'),
    ('S142', 'https://frankmedia.ru/feed'),
    ('S144', 'https://new-retail.ru/rss/index_all.php')
) AS v(id, feed_url)
WHERE sources.id = v.id AND sources.adapter = 'rss';
