package postgres

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

var (
	ErrIdempotencyConflict        = errors.New("idempotency key already used for a different request")
	ErrOnboardingResourceConflict = errors.New("company or user already exists")
	ErrUnknownRole                = errors.New("unknown role")
)

// CreateOnboarding atomically creates the company, its first user, role links,
// and the idempotency record. Concurrent replays of a key serialize in PG.
func (s *Store) CreateOnboarding(ctx context.Context, key, requestHash string, company domain.Company, user domain.User) (domain.Company, domain.User, bool, error) {
	var resultCompany domain.Company
	var resultUser domain.User
	replayed := false
	err := pgx.BeginFunc(ctx, s.pool, func(tx pgx.Tx) error {
		// Transaction-scoped lock: no external work is performed while it is held.
		if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, "onboarding:"+key); err != nil {
			return err
		}
		var existingHash string
		var companyID, userID int64
		err := tx.QueryRow(ctx, `SELECT request_hash, company_id, user_id FROM onboarding_requests WHERE idempotency_key=$1`, key).
			Scan(&existingHash, &companyID, &userID)
		if err == nil {
			if existingHash != requestHash {
				return ErrIdempotencyConflict
			}
			resultCompany, err = getCompanyTx(ctx, tx, companyID)
			if err != nil {
				return err
			}
			resultUser, err = getUserTx(ctx, tx, userID)
			if err != nil {
				return err
			}
			replayed = true
			return nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return err
		}

		if company.Profile == nil {
			company.Profile = map[string]json.RawMessage{}
		}
		if err := tx.QueryRow(ctx, `
			INSERT INTO companies (inn, ogrn, name, profile)
			VALUES ($1, NULLIF($2, ''), $3, $4) RETURNING id`, company.INN, company.OGRN, company.Name, company.Profile).Scan(&company.ID); err != nil {
			return err
		}
		user.CompanyID = &company.ID
		if err := tx.QueryRow(ctx, `
			INSERT INTO users (company_id, email, full_name)
			VALUES ($1, $2, $3) RETURNING id`, company.ID, user.Email, user.FullName).Scan(&user.ID); err != nil {
			return err
		}
		for _, code := range user.Roles {
			var roleID int16
			if err := tx.QueryRow(ctx, `SELECT id FROM roles WHERE code=$1`, code).Scan(&roleID); errors.Is(err, pgx.ErrNoRows) {
				return ErrUnknownRole
			} else if err != nil {
				return err
			}
			if _, err := tx.Exec(ctx, `INSERT INTO user_roles (user_id, role_id) VALUES ($1, $2)`, user.ID, roleID); err != nil {
				return err
			}
		}
		if _, err := tx.Exec(ctx, `INSERT INTO onboarding_requests (idempotency_key, request_hash, company_id, user_id) VALUES ($1, $2, $3, $4)`, key, requestHash, company.ID, user.ID); err != nil {
			return err
		}
		resultCompany, err = getCompanyTx(ctx, tx, company.ID)
		if err != nil {
			return err
		}
		resultUser, err = getUserTx(ctx, tx, user.ID)
		return err
	})
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == "23505" {
		return domain.Company{}, domain.User{}, false, ErrOnboardingResourceConflict
	}
	return resultCompany, resultUser, replayed, err
}

func getCompanyTx(ctx context.Context, tx pgx.Tx, id int64) (domain.Company, error) {
	var company domain.Company
	var ogrn *string
	err := tx.QueryRow(ctx, `SELECT id, inn, ogrn, name, profile, created_at, updated_at FROM companies WHERE id=$1`, id).
		Scan(&company.ID, &company.INN, &ogrn, &company.Name, &company.Profile, &company.CreatedAt, &company.UpdatedAt)
	if ogrn != nil {
		company.OGRN = *ogrn
	}
	return company, err
}

func getUserTx(ctx context.Context, tx pgx.Tx, id int64) (domain.User, error) {
	var user domain.User
	err := tx.QueryRow(ctx, userSelect+` WHERE u.id=$1 GROUP BY u.id`, id).
		Scan(&user.ID, &user.CompanyID, &user.Email, &user.FullName, &user.CreatedAt, &user.Roles)
	return user, err
}
