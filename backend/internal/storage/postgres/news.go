package postgres

import (
	"context"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

// SourceConfig — источник, для которого включён автоматический сбор.
type SourceConfig struct {
	ID      string
	Adapter string
	URL     string
	Config  map[string]any
}

func (s *Store) EnabledSources(ctx context.Context) ([]SourceConfig, error) {
	rows, err := s.pool.Query(ctx,
		`SELECT id, adapter, url, config FROM sources WHERE enabled AND adapter IS NOT NULL ORDER BY id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []SourceConfig
	for rows.Next() {
		var c SourceConfig
		if err := rows.Scan(&c.ID, &c.Adapter, &c.URL, &c.Config); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// UpsertNews сохраняет новость; повторный сбор той же новости её не дублирует.
// Возвращает id и признак того, что новость новая.
func (s *Store) UpsertNews(ctx context.Context, n domain.NewsItem) (int64, bool, error) {
	var id int64
	var inserted bool
	err := s.pool.QueryRow(ctx, `
		INSERT INTO news_items (source_id, external_id, url, title, summary, body, published_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
		ON CONFLICT (source_id, external_id) DO UPDATE SET title = EXCLUDED.title
		RETURNING id, (xmax = 0)`,
		n.SourceID, n.ExternalID, n.URL, n.Title, n.Summary, n.Body, n.PublishedAt).Scan(&id, &inserted)
	return id, inserted, err
}

func (s *Store) AddFeedItem(ctx context.Context, userID int64, roleCode string, newsID int64, f domain.FeedItem) error {
	if f.Elements == nil {
		f.Elements = []string{} // nil ушёл бы в БД как NULL, а колонка NOT NULL
	}
	_, err := s.pool.Exec(ctx, `
		INSERT INTO feed_items (user_id, role_id, news_id, kind, score, insight, elements)
		SELECT $1, id, $3, $4, $5, $6, $7 FROM roles WHERE code = $2
		ON CONFLICT (user_id, role_id, news_id) DO NOTHING`,
		userID, roleCode, newsID, f.Kind, f.Score, f.Insight, f.Elements)
	return err
}

// UsersForFeed — все пользователи с их ролями (для построения лент).
func (s *Store) UsersForFeed(ctx context.Context) ([]domain.User, error) {
	rows, err := s.pool.Query(ctx, userSelect+` GROUP BY u.id ORDER BY u.id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []domain.User
	for rows.Next() {
		var u domain.User
		if err := rows.Scan(&u.ID, &u.CompanyID, &u.Email, &u.FullName, &u.CreatedAt, &u.Roles); err != nil {
			return nil, err
		}
		out = append(out, u)
	}
	return out, rows.Err()
}

// Feed возвращает ленту пользователя; roleCode = "" — по всем его ролям.
// ErrNotFound — пользователя нет (пустая лента существующего пользователя — пустой срез).
func (s *Store) Feed(ctx context.Context, userID int64, roleCode string, limit int) ([]domain.FeedItem, error) {
	ok, err := s.userExists(ctx, userID)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, ErrNotFound
	}
	rows, err := s.pool.Query(ctx, `
		SELECT f.id, r.code, f.kind, f.score, f.insight, f.elements, f.created_at, f.read_at,
		       n.id, n.source_id, n.url, n.title, n.summary, n.published_at
		FROM feed_items f
		JOIN roles r ON r.id = f.role_id
		JOIN news_items n ON n.id = f.news_id
		WHERE f.user_id = $1 AND ($2 = '' OR r.code = $2)
		ORDER BY n.published_at DESC, f.score DESC
		LIMIT $3`, userID, roleCode, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []domain.FeedItem{}
	for rows.Next() {
		var f domain.FeedItem
		if err := rows.Scan(&f.ID, &f.Role, &f.Kind, &f.Score, &f.Insight, &f.Elements, &f.CreatedAt, &f.ReadAt,
			&f.News.ID, &f.News.SourceID, &f.News.URL, &f.News.Title, &f.News.Summary, &f.News.PublishedAt); err != nil {
			return nil, err
		}
		out = append(out, f)
	}
	return out, rows.Err()
}
