package postgres

import (
	"context"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/feed"
)

// Очередь оценок news_rankings: одна оценка оркестратора на пару (новость, компания)
// по объединению ролей директоров компании. Результат раскладывается по лентам всех
// директоров с подходящей ролью, в том числе зарегистрированных позже.

// companyRoles — роли директоров каждой компании.
const companyRoles = `
	SELECT u.company_id, array_agg(DISTINCT r.code ORDER BY r.code) AS roles
	FROM users u
	JOIN user_roles ur ON ur.user_id = u.id
	JOIN roles r ON r.id = ur.role_id
	WHERE u.company_id IS NOT NULL
	GROUP BY u.company_id`

// EnqueueRankings ставит в очередь оценки новостей, опубликованных начиная с since, для всех
// компаний, где у директоров есть роли. Уже оценённую новость отправляет на переоценку,
// если у компании появилась роль, по которой её не оценивали. Возвращает число новых задач.
func (s *Store) EnqueueRankings(ctx context.Context, since time.Time) (int64, error) {
	tag, err := s.pool.Exec(ctx, `
		INSERT INTO news_rankings (news_id, company_id)
		SELECT n.id, cr.company_id FROM news_items n CROSS JOIN (`+companyRoles+`) cr
		WHERE n.published_at >= $1
		ON CONFLICT DO NOTHING`, since)
	if err != nil {
		return 0, err
	}
	_, err = s.pool.Exec(ctx, `
		UPDATE news_rankings nr
		SET status = 'pending', attempts = 0, next_attempt_at = now(), updated_at = now()
		FROM news_items n, (`+companyRoles+`) cr
		WHERE nr.status = 'done' AND n.id = nr.news_id AND n.published_at >= $1
		  AND cr.company_id = nr.company_id AND NOT cr.roles <@ nr.roles`, since)
	return tag.RowsAffected(), err
}

// Ranking — задача оценки: новость и текущие роли директоров компании.
type Ranking struct {
	News      domain.NewsItem // с полным текстом Body
	CompanyID int64
	Roles     []string
	Attempts  int
}

// DueRankings — задачи, которые пора выполнить. Сначала поставленные в очередь последними:
// новость из служебного импорта не ждёт разбора старой очереди. Внутри одного прохода
// сбора — от свежих публикаций к старым, независимо от источника.
func (s *Store) DueRankings(ctx context.Context, limit int) ([]Ranking, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT n.id, n.source_id, n.url, n.title, n.summary, n.body, n.published_at, nr.company_id, nr.attempts,
		       COALESCE(cr.roles, '{}')
		FROM news_rankings nr
		JOIN news_items n ON n.id = nr.news_id
		LEFT JOIN (`+companyRoles+`) cr ON cr.company_id = nr.company_id
		WHERE nr.status = 'pending' AND nr.next_attempt_at <= now()
		ORDER BY nr.created_at DESC, n.published_at DESC
		LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Ranking
	for rows.Next() {
		var r Ranking
		n := &r.News
		if err := rows.Scan(&n.ID, &n.SourceID, &n.URL, &n.Title, &n.Summary, &n.Body, &n.PublishedAt,
			&r.CompanyID, &r.Attempts, &r.Roles); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// FinishRanking сохраняет ответ оркестратора; в ленты его раскладывает FanOutFeed.
func (s *Store) FinishRanking(ctx context.Context, newsID, companyID int64, roles []string, matches []feed.Match) error {
	if roles == nil {
		roles = []string{}
	}
	if matches == nil {
		matches = []feed.Match{} // nil ушёл бы в JSONB как null
	}
	_, err := s.pool.Exec(ctx, `
		UPDATE news_rankings
		SET status = 'done', roles = $3, matches = $4, error = '', updated_at = now()
		WHERE news_id = $1 AND company_id = $2`, newsID, companyID, roles, matches)
	return err
}

// RetryRanking откладывает задачу до next или, если failed, снимает её с очереди.
func (s *Store) RetryRanking(ctx context.Context, newsID, companyID int64, attempts int, next time.Time, failed bool, reason string) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE news_rankings
		SET status = CASE WHEN $5 THEN 'failed' ELSE 'pending' END,
		    attempts = $3, next_attempt_at = $4, error = $6, updated_at = now()
		WHERE news_id = $1 AND company_id = $2`, newsID, companyID, attempts, next, failed, reason)
	return err
}

// FanOutFeed добавляет в ленты директоров карточки из готовых оценок новостей, опубликованных
// начиная с since: по каждой роли из ответа оркестратора — всем директорам компании с этой ролью.
// Повторный вызов ничего не дублирует. Возвращает число новых карточек.
func (s *Store) FanOutFeed(ctx context.Context, since time.Time) (int64, error) {
	tag, err := s.pool.Exec(ctx, `
		INSERT INTO feed_items (user_id, role_id, news_id, kind, score, insight, elements)
		SELECT u.id, r.id, nr.news_id, m.kind, COALESCE(m.score, 0), COALESCE(m.insight, ''), COALESCE(m.elements, '{}')
		FROM news_rankings nr
		JOIN news_items n ON n.id = nr.news_id
		CROSS JOIN LATERAL jsonb_to_recordset(nr.matches)
		     AS m(role TEXT, kind TEXT, score REAL, insight TEXT, elements TEXT[])
		JOIN roles r ON r.code = m.role
		JOIN users u ON u.company_id = nr.company_id
		JOIN user_roles ur ON ur.user_id = u.id AND ur.role_id = r.id
		WHERE nr.status = 'done' AND n.published_at >= $1 AND m.kind IN ('event', 'risk', 'opportunity')
		ON CONFLICT (user_id, role_id, news_id) DO NOTHING`, since)
	return tag.RowsAffected(), err
}

// ImportedNews — результат служебного импорта одной новости.
type ImportedNews struct {
	ID      int64 `json:"id"`
	Created bool  `json:"created"` // false — новость с таким sourceId и externalId уже была
}

// ImportNews сохраняет новости одной транзакцией и будит воркер, чтобы он оценил их,
// не дожидаясь очередного сбора. ErrNotFound — нет источника.
func (s *Store) ImportNews(ctx context.Context, items []domain.NewsItem) ([]ImportedNews, error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	out := make([]ImportedNews, len(items))
	for i, n := range items {
		err := tx.QueryRow(ctx, upsertNews,
			n.SourceID, n.ExternalID, n.URL, n.Title, n.Summary, n.Body, n.PublishedAt).Scan(&out[i].ID, &out[i].Created)
		if pgCode(err) == "23503" {
			return nil, ErrNotFound
		}
		if err != nil {
			return nil, err
		}
	}
	if _, err := tx.Exec(ctx, `SELECT pg_notify($1, '')`, refreshChannel); err != nil {
		return nil, err
	}
	return out, tx.Commit(ctx)
}

// refreshChannel — канал LISTEN/NOTIFY, по которому сервер API будит воркер:
// после импорта новостей и после смены состава директоров или их ролей.
const refreshChannel = "feed_refresh"

// RequestFeedRefresh просит воркер оценить очередь и разложить карточки сейчас, а не через INGEST_PERIOD.
func (s *Store) RequestFeedRefresh(ctx context.Context) error {
	_, err := s.pool.Exec(ctx, `SELECT pg_notify($1, '')`, refreshChannel)
	return err
}

// ListenFeedRefresh шлёт в wake сигнал на каждый RequestFeedRefresh, пока не отменён ctx
// или не оборвалось соединение (тогда возвращает ошибку, вызывающий переподключается).
func (s *Store) ListenFeedRefresh(ctx context.Context, wake chan<- struct{}) error {
	c, err := s.pool.Acquire(ctx)
	if err != nil {
		return err
	}
	// Соединение с LISTEN не возвращаем в пул: иначе подписка достанется чужим запросам.
	conn := c.Hijack()
	defer conn.Close(context.Background())
	if _, err := conn.Exec(ctx, `LISTEN `+refreshChannel); err != nil {
		return err
	}
	for {
		if _, err := conn.WaitForNotification(ctx); err != nil {
			return err
		}
		select {
		case wake <- struct{}{}:
		default: // проход уже запрошен
		}
	}
}
