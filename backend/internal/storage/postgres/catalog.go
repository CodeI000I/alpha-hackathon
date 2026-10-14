package postgres

import (
	"context"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

func (s *Store) ListRoles(ctx context.Context) ([]domain.Role, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT r.id, r.code, r.name, r.question, r.focus,
		       COALESCE(array_agg(e.element_code ORDER BY e.element_code) FILTER (WHERE e.element_code IS NOT NULL), '{}')
		FROM roles r
		LEFT JOIN role_profile_elements e ON e.role_id = r.id
		GROUP BY r.id ORDER BY r.id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []domain.Role
	for rows.Next() {
		var r domain.Role
		if err := rows.Scan(&r.ID, &r.Code, &r.Name, &r.Question, &r.Focus, &r.Elements); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func (s *Store) ListProfileElements(ctx context.Context) ([]domain.ProfileElement, error) {
	rows, err := s.pool.Query(ctx, `SELECT code, block, name, description, purpose FROM profile_elements ORDER BY code`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []domain.ProfileElement
	for rows.Next() {
		var e domain.ProfileElement
		if err := rows.Scan(&e.Code, &e.Block, &e.Name, &e.Description, &e.Purpose); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}
