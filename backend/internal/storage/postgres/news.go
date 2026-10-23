package postgres

import (
	"context"
	"errors"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/feed"
	"github.com/jackc/pgx/v5"
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

// UpsertNews сохраняет новость и задания доставки атомарно. Второй результат
// показывает, изменилось ли содержимое (включая новую запись).
func (s *Store) UpsertNews(ctx context.Context, n domain.NewsItem) (int64, bool, error) {
	var id int64
	changed := false
	err := pgx.BeginFunc(ctx, s.pool, func(tx pgx.Tx) error {
		err := tx.QueryRow(ctx, `INSERT INTO news_items
			(source_id, external_id, url, title, summary, body, published_at)
			VALUES ($1, $2, $3, $4, $5, $6, $7)
			ON CONFLICT (source_id, external_id) DO NOTHING RETURNING id`,
			n.SourceID, n.ExternalID, n.URL, n.Title, n.Summary, n.Body, n.PublishedAt).Scan(&id)
		if err == nil {
			changed = true
			return enqueueNewsDeliveries(ctx, tx, id, 1)
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		var oldURL, oldTitle, oldSummary, oldBody string
		var oldPublished time.Time
		var revision int64
		if err := tx.QueryRow(ctx, `SELECT id,url,title,summary,body,published_at,revision
			FROM news_items WHERE source_id=$1 AND external_id=$2 FOR UPDATE`, n.SourceID, n.ExternalID).
			Scan(&id, &oldURL, &oldTitle, &oldSummary, &oldBody, &oldPublished, &revision); err != nil {
			return err
		}
		if oldURL == n.URL && oldTitle == n.Title && oldSummary == n.Summary && oldBody == n.Body && oldPublished.Equal(n.PublishedAt) {
			return nil
		}
		changed = true
		if _, err := tx.Exec(ctx, `UPDATE news_items SET url=$2,title=$3,summary=$4,body=$5,published_at=$6,revision=revision+1
			WHERE id=$1`, id, n.URL, n.Title, n.Summary, n.Body, n.PublishedAt); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `UPDATE news_deliveries SET state='superseded',updated_at=now()
			WHERE news_id=$1 AND state IN ('pending','running')`, id); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `UPDATE feed_items SET active=false WHERE news_id=$1`, id); err != nil {
			return err
		}
		return enqueueNewsDeliveries(ctx, tx, id, revision+1)
	})
	return id, changed, err
}

func enqueueNewsDeliveries(ctx context.Context, tx pgx.Tx, newsID, revision int64) error {
	_, err := tx.Exec(ctx, `INSERT INTO news_deliveries(news_id,revision,user_id)
		SELECT $1,$2,u.id FROM users u JOIN user_roles ur ON ur.user_id=u.id
		WHERE u.company_id IS NOT NULL GROUP BY u.id
		ON CONFLICT (news_id,revision,user_id) DO NOTHING`, newsID, revision)
	return err
}

// NewsDelivery is a fenced claim on one user's ranking job.
type NewsDelivery struct {
	ID         int64
	NewsID     int64
	Revision   int64
	UserID     int64
	ClaimToken int64
	News       domain.NewsItem
	User       domain.User
	Company    domain.Company
	HasCompany bool
}

// ClaimNewsDeliveries claims a bounded batch; expired claims are reclaimed with a new fencing token.
func (s *Store) ClaimNewsDeliveries(ctx context.Context, limit int) ([]NewsDelivery, error) {
	if limit < 1 || limit > 100 {
		limit = 100
	}
	var out []NewsDelivery
	err := pgx.BeginFunc(ctx, s.pool, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `UPDATE news_deliveries d SET state='failed',failures=failures+1,
			lease_until=NULL,last_error='lease_expired',updated_at=now()
			FROM news_items n WHERE n.id=d.news_id AND n.revision=d.revision AND d.state='running'
			AND d.lease_until<=now() AND d.failures>=7`); err != nil {
			return err
		}
		rows, err := tx.Query(ctx, `WITH picked AS (
			SELECT d.id FROM news_deliveries d JOIN news_items n ON n.id=d.news_id
			WHERE n.revision=d.revision AND ((d.state='pending' AND d.next_attempt_at<=now()) OR
			(d.state='running' AND d.lease_until<=now()))
			ORDER BY d.next_attempt_at,d.id LIMIT $1 FOR UPDATE OF d SKIP LOCKED
		) UPDATE news_deliveries d SET state='running', attempts=attempts+1,
			failures=failures+CASE WHEN d.state='running' THEN 1 ELSE 0 END,
			last_error=CASE WHEN d.state='running' THEN 'lease_expired' ELSE d.last_error END,
			claim_token=claim_token+1,
			lease_until=now()+interval '2 minutes',updated_at=now()
		FROM picked p,news_items n WHERE d.id=p.id AND n.id=d.news_id
		RETURNING d.id,d.news_id,d.revision,d.user_id,d.claim_token,n.source_id,n.external_id,n.url,n.title,n.summary,n.body,n.published_at`, limit)
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			var d NewsDelivery
			d.News.ID = 0
			if err := rows.Scan(&d.ID, &d.NewsID, &d.Revision, &d.UserID, &d.ClaimToken,
				&d.News.SourceID, &d.News.ExternalID, &d.News.URL, &d.News.Title, &d.News.Summary, &d.News.Body, &d.News.PublishedAt); err != nil {
				return err
			}
			d.News.ID = d.NewsID
			out = append(out, d)
		}
		if err := rows.Err(); err != nil {
			return err
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	for i := range out {
		u, err := s.GetUser(ctx, out[i].UserID)
		if errors.Is(err, ErrNotFound) {
			out[i].User.ID = out[i].UserID
			continue
		}
		if err != nil {
			return nil, err
		}
		out[i].User = u
		if u.CompanyID == nil {
			continue
		}
		c, err := s.GetCompany(ctx, *u.CompanyID)
		if errors.Is(err, ErrNotFound) {
			continue
		}
		if err != nil {
			return nil, err
		}
		out[i].Company = c
		out[i].HasCompany = true
	}
	return out, nil
}

// CompleteNewsDelivery commits current matches (including an empty result) only for the current claim/revision.
func (s *Store) CompleteNewsDelivery(ctx context.Context, d NewsDelivery, matches []feed.Match) (bool, error) {
	completed := false
	err := pgx.BeginFunc(ctx, s.pool, func(tx pgx.Tx) error {
		var revision int64
		if err := tx.QueryRow(ctx, `SELECT revision FROM news_items WHERE id=$1 FOR UPDATE`, d.NewsID).Scan(&revision); errors.Is(err, pgx.ErrNoRows) {
			return nil
		} else if err != nil {
			return err
		}
		var userID int64
		if err := tx.QueryRow(ctx, `SELECT id FROM users WHERE id=$1 FOR UPDATE`, d.UserID).Scan(&userID); errors.Is(err, pgx.ErrNoRows) {
			return nil
		} else if err != nil {
			return err
		}
		var state string
		var token int64
		if err := tx.QueryRow(ctx, `SELECT state,claim_token FROM news_deliveries WHERE id=$1 AND news_id=$2 FOR UPDATE`, d.ID, d.NewsID).Scan(&state, &token); errors.Is(err, pgx.ErrNoRows) {
			return nil
		} else if err != nil {
			return err
		}
		if revision != d.Revision || state != "running" || token != d.ClaimToken {
			return nil
		}
		var currentRoles []string
		if err := tx.QueryRow(ctx, `SELECT COALESCE(array_agg(r.code ORDER BY r.id), '{}')
			FROM user_roles ur JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=$1`, d.UserID).Scan(&currentRoles); err != nil {
			return err
		}
		if !sameStrings(currentRoles, d.User.Roles) {
			_, err := tx.Exec(ctx, `UPDATE news_deliveries SET state='pending',lease_until=NULL,next_attempt_at=now(),updated_at=now()
				WHERE id=$1 AND claim_token=$2 AND state='running'`, d.ID, d.ClaimToken)
			return err
		}
		if _, err := tx.Exec(ctx, `UPDATE feed_items SET active=false WHERE user_id=$1 AND news_id=$2`, d.UserID, d.NewsID); err != nil {
			return err
		}
		for _, m := range matches {
			elements := m.Elements
			if elements == nil {
				elements = []string{}
			}
			if _, err := tx.Exec(ctx, `INSERT INTO feed_items(user_id,role_id,news_id,kind,score,insight,elements,active)
				SELECT $1,r.id,$2,$4,$5,$6,$7,true FROM roles r
				JOIN user_roles ur ON ur.role_id=r.id AND ur.user_id=$1 WHERE r.code=$3
				ON CONFLICT(user_id,role_id,news_id) DO UPDATE SET kind=EXCLUDED.kind,score=EXCLUDED.score,
				insight=EXCLUDED.insight,elements=EXCLUDED.elements,active=true`, d.UserID, d.NewsID, m.Role, m.Kind, m.Score, m.Insight, elements); err != nil {
				return err
			}
		}
		tag, err := tx.Exec(ctx, `UPDATE news_deliveries SET state='done',lease_until=NULL,last_error='',updated_at=now()
			WHERE id=$1 AND claim_token=$2 AND state='running'`, d.ID, d.ClaimToken)
		if err != nil {
			return err
		}
		completed = tag.RowsAffected() == 1
		return nil
	})
	return completed, err
}

func sameStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func (s *Store) RetryNewsDelivery(ctx context.Context, d NewsDelivery, errorCode string) error {
	if errorCode != "rank_failed" && errorCode != "persistence_failed" {
		errorCode = "processing_failed"
	}
	_, err := s.pool.Exec(ctx, `UPDATE news_deliveries SET
		state=CASE WHEN failures+1 >= 8 THEN 'failed' ELSE 'pending' END,
		failures=failures+1, lease_until=NULL,
		next_attempt_at=now()+LEAST(interval '5 minutes', interval '5 seconds' * power(2,LEAST(failures,6))),
		last_error=$3,updated_at=now() WHERE id=$1 AND state='running' AND claim_token=$2`, d.ID, d.ClaimToken, errorCode)
	return err
}

func (s *Store) AddFeedItem(ctx context.Context, userID int64, roleCode string, newsID int64, f domain.FeedItem) error {
	if f.Elements == nil {
		f.Elements = []string{}
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
func (s *Store) Feed(ctx context.Context, userID int64, roleCode string, limit int) ([]domain.FeedItem, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT f.id, r.code, f.kind, f.score, f.insight, f.elements, f.created_at, f.read_at,
		       n.id, n.source_id, n.url, n.title, n.summary, n.published_at
		FROM feed_items f
		JOIN roles r ON r.id = f.role_id
		JOIN user_roles ur ON ur.user_id=f.user_id AND ur.role_id=f.role_id
		JOIN news_items n ON n.id = f.news_id
		WHERE f.active AND f.user_id = $1 AND ($2 = '' OR r.code = $2)
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
