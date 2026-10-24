package postgres

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

var ErrInvalidCredentials = errors.New("invalid credentials")

func (s *Store) GetUserCredentials(ctx context.Context, email string) (domain.User, string, error) {
	var user domain.User
	var passwordHash string
	err := s.pool.QueryRow(ctx, `
		SELECT u.id, u.company_id, u.email, u.full_name, u.created_at,
		       COALESCE(array_agg(r.code ORDER BY r.id) FILTER (WHERE r.code IS NOT NULL), '{}'), u.password_hash
		FROM users u LEFT JOIN user_roles ur ON ur.user_id=u.id LEFT JOIN roles r ON r.id=ur.role_id
		WHERE lower(u.email)=lower($1) GROUP BY u.id`, email).
		Scan(&user.ID, &user.CompanyID, &user.Email, &user.FullName, &user.CreatedAt, &user.Roles, &passwordHash)
	if errors.Is(err, pgx.ErrNoRows) {
		return user, "", ErrInvalidCredentials
	}
	return user, passwordHash, err
}

func (s *Store) GetUserBySession(ctx context.Context, tokenHash string) (domain.User, error) {
	var user domain.User
	err := s.pool.QueryRow(ctx, userSelect+` JOIN auth_sessions a ON a.user_id=u.id WHERE a.token_hash=$1 AND a.expires_at>now() GROUP BY u.id`, tokenHash).
		Scan(&user.ID, &user.CompanyID, &user.Email, &user.FullName, &user.CreatedAt, &user.Roles)
	if errors.Is(err, pgx.ErrNoRows) {
		return user, ErrNotFound
	}
	return user, err
}

func (s *Store) CreateSession(ctx context.Context, tokenHash string, userID int64, expires time.Time) error {
	_, err := s.pool.Exec(ctx, `INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES($1,$2,$3)`, tokenHash, userID, expires)
	return err
}

func (s *Store) DeleteSession(ctx context.Context, tokenHash string) error {
	_, err := s.pool.Exec(ctx, `DELETE FROM auth_sessions WHERE token_hash=$1`, tokenHash)
	return err
}

func (s *Store) SetPasswordByEmail(ctx context.Context, email, passwordHash string) error {
	return pgx.BeginFunc(ctx, s.pool, func(tx pgx.Tx) error {
		var userID int64
		err := tx.QueryRow(ctx, `UPDATE users SET password_hash=$2 WHERE lower(email)=lower($1) RETURNING id`, email, passwordHash).Scan(&userID)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrNotFound
		}
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `DELETE FROM auth_sessions WHERE user_id=$1`, userID)
		return err
	})
}
