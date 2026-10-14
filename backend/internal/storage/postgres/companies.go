package postgres

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/jackc/pgx/v5"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

func (s *Store) GetCompany(ctx context.Context, id int64) (domain.Company, error) {
	var c domain.Company
	var ogrn *string
	err := s.pool.QueryRow(ctx,
		`SELECT id, inn, ogrn, name, profile, created_at, updated_at FROM companies WHERE id = $1`, id).
		Scan(&c.ID, &c.INN, &ogrn, &c.Name, &c.Profile, &c.CreatedAt, &c.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return c, ErrNotFound
	}
	if ogrn != nil {
		c.OGRN = *ogrn
	}
	return c, err
}

func (s *Store) CreateCompany(ctx context.Context, c domain.Company) (domain.Company, error) {
	if c.Profile == nil {
		c.Profile = map[string]json.RawMessage{}
	}
	err := s.pool.QueryRow(ctx,
		`INSERT INTO companies (inn, ogrn, name, profile) VALUES ($1, NULLIF($2, ''), $3, $4) RETURNING id`,
		c.INN, c.OGRN, c.Name, c.Profile).Scan(&c.ID)
	if err != nil {
		return c, err
	}
	return s.GetCompany(ctx, c.ID)
}

// PatchProfile сливает переданные элементы профиля с уже сохранёнными (JSONB ||).
func (s *Store) PatchProfile(ctx context.Context, id int64, patch map[string]json.RawMessage) (domain.Company, error) {
	tag, err := s.pool.Exec(ctx,
		`UPDATE companies SET profile = profile || $2, updated_at = now() WHERE id = $1`, id, patch)
	if err != nil {
		return domain.Company{}, err
	}
	if tag.RowsAffected() == 0 {
		return domain.Company{}, ErrNotFound
	}
	return s.GetCompany(ctx, id)
}

func (s *Store) CreateCompanyFile(ctx context.Context, f domain.CompanyFile) (domain.CompanyFile, error) {
	err := s.pool.QueryRow(ctx, `
		INSERT INTO company_files (company_id, object_key, filename, content_type, size_bytes)
		VALUES ($1, $2, $3, $4, $5) RETURNING id, created_at`,
		f.CompanyID, f.ObjectKey, f.Filename, f.ContentType, f.SizeBytes).Scan(&f.ID, &f.CreatedAt)
	return f, err
}

func (s *Store) ListCompanyFiles(ctx context.Context, companyID int64) ([]domain.CompanyFile, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT id, company_id, object_key, filename, content_type, size_bytes, created_at
		FROM company_files WHERE company_id = $1 ORDER BY created_at DESC`, companyID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []domain.CompanyFile{}
	for rows.Next() {
		var f domain.CompanyFile
		if err := rows.Scan(&f.ID, &f.CompanyID, &f.ObjectKey, &f.Filename, &f.ContentType, &f.SizeBytes, &f.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, f)
	}
	return out, rows.Err()
}
