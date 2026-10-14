package postgres

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

var ErrNotFound = errors.New("not found")

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

func (s *Store) CreateUser(ctx context.Context, u domain.User) (domain.User, error) {
	err := s.pool.QueryRow(ctx,
		`INSERT INTO users (company_id, email, full_name) VALUES ($1, $2, $3) RETURNING id`,
		u.CompanyID, u.Email, u.FullName).Scan(&u.ID)
	if err != nil {
		return u, err
	}
	if len(u.Roles) > 0 {
		if err := s.SetUserRoles(ctx, u.ID, u.Roles); err != nil {
			return u, err
		}
	}
	return s.GetUser(ctx, u.ID)
}

// SetUserRoles заменяет набор ролей пользователя (роли передаются кодами: sales, procurement, ...).
func (s *Store) SetUserRoles(ctx context.Context, userID int64, codes []string) error {
	return pgx.BeginFunc(ctx, s.pool, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `DELETE FROM user_roles WHERE user_id = $1`, userID); err != nil {
			return err
		}
		_, err := tx.Exec(ctx, `
			INSERT INTO user_roles (user_id, role_id)
			SELECT $1, id FROM roles WHERE code = ANY($2)`, userID, codes)
		return err
	})
}
