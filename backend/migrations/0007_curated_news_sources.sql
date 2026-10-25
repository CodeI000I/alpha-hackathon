-- Компактный набор из company_research.xlsx, лист «3. Источники».
-- Сужаем только прежний seed-набор RSS; новости, доставки и пользовательские
-- источники не удаляются. Причины выбора и live-проверки: docs/news-sources.md.
UPDATE sources SET enabled = false
WHERE id IN ('S085', 'S086', 'S137', 'S138', 'S139', 'S140', 'S141', 'S144')
  AND adapter = 'rss';

-- Приоритет происхождения — порядок опроса, не вероятность истинности новости
-- и не оценка её влияния на компанию. Сохраняем прежний feed_content Frank Media,
-- чтобы повторный сбор не удалял уже полученный через RSS полный текст.
UPDATE sources SET adapter = 'rss', enabled = true,
    config = config || v.settings::jsonb
FROM (VALUES
    ('S077', '{"feed_url":"https://www.cbr.ru/rss/RssPress","article_hosts":["www.cbr.ru"],"content_policy":"metadata_only","source_class":"official_primary","priority":1,"selection":"trusted-demo-v1"}'),
    ('S136', '{"feed_url":"https://www.interfax.ru/rss","article_hosts":["www.interfax.ru"],"categories":["Экономика"],"content_policy":"metadata_only","source_class":"established_media","priority":2,"selection":"trusted-demo-v1"}'),
    ('S142', '{"feed_url":"https://frankmedia.ru/feed","article_hosts":["frankmedia.ru"],"content_policy":"feed_content","source_class":"industry_media","priority":3,"selection":"trusted-demo-v1"}')
) AS v(id, settings)
WHERE sources.id = v.id;
