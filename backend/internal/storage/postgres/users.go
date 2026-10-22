package postgres

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

var (
	ErrNotFound   = errors.New("not found")
	ErrEmailTaken = errors.New("email is already registered")
	ErrINNTaken   = errors.New("inn is already registered")
)

// pgCode — код ошибки PostgreSQL (23505 unique_violation, 23503 foreign_key_violation, ...).
func pgCode(err error) string {
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) {
		return pgErr.Code
	}
	return ""
}

const userSelect = `
	SELECT u.id, u.company_id, u.email, u.full_name, u.created_at,
	       COALESCE(array_agg(r.code ORDER BY r.id) FILTER (WHERE r.code IS NOT NULL), '{}')
	FROM users u
	LEFT JOIN user_roles ur ON ur.user_id = u.id
	LEFT JOIN roles r ON r.id = ur.role_id`

func (s *Store) GetUser(ctx context.Context, id int64) (domain.User, error) {
	var u domain.User
	err := s.pool.QueryRow(ctx, userSelect+` WHERE u.id = $1 GROUP BY u.id`, id).
		Scan(&u.ID, &u.CompanyID, &u.Email, &u.FullName, &u.CreatedAt, &u.Roles)
	if errors.Is(err, pgx.ErrNoRows) {
		return u, ErrNotFound
	}
	return u, err
}

// CreateUser создаёт пользователя вместе с ролями одной транзакцией, чтобы сбой на ролях
// не оставлял пользователя, email которого уже занят. ErrEmailTaken — email уже есть,
// ErrNotFound — нет компании companyId.
func (s *Store) CreateUser(ctx context.Context, u domain.User) (domain.User, error) {
	err := pgx.BeginFunc(ctx, s.pool, func(tx pgx.Tx) error {
		err := tx.QueryRow(ctx,
			`INSERT INTO users (company_id, email, full_name) VALUES ($1, $2, $3) RETURNING id`,
			u.CompanyID, u.Email, u.FullName).Scan(&u.ID)
		switch pgCode(err) {
		case "23505":
			return ErrEmailTaken
		case "23503":
			return ErrNotFound
		}
		if err != nil {
			return err
		}
		return replaceRoles(ctx, tx, u.ID, u.Roles)
	})
	if err != nil {
		return u, err
	}
	return s.GetUser(ctx, u.ID)
}

// SetUserRoles заменяет набор ролей пользователя (роли передаются кодами: sales, procurement, ...).
// Неизвестные коды пропускаются. ErrNotFound — пользователя нет.
func (s *Store) SetUserRoles(ctx context.Context, userID int64, codes []string) error {
	return pgx.BeginFunc(ctx, s.pool, func(tx pgx.Tx) error {
		// FOR UPDATE: параллельные PUT одного пользователя выполняются по очереди.
		var id int64
		err := tx.QueryRow(ctx, `SELECT id FROM users WHERE id = $1 FOR UPDATE`, userID).Scan(&id)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrNotFound
		}
		if err != nil {
			return err
		}
		return replaceRoles(ctx, tx, userID, codes)
	})
}

func replaceRoles(ctx context.Context, tx pgx.Tx, userID int64, codes []string) error {
	if _, err := tx.Exec(ctx, `DELETE FROM user_roles WHERE user_id = $1`, userID); err != nil {
		return err
	}
	_, err := tx.Exec(ctx, `
		INSERT INTO user_roles (user_id, role_id)
		SELECT $1, id FROM roles WHERE code = ANY($2)`, userID, codes)
	return err
}

func (s *Store) userExists(ctx context.Context, id int64) (bool, error) {
	var ok bool
	err := s.pool.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM users WHERE id = $1)`, id).Scan(&ok)
	return ok, err
}
