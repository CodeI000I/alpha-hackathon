package ingest

import (
	"context"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
)

// AlfaFetcher — лента новостей и аналитики Альфа-Банка.
// Формат и доступ пока неизвестны (у источников S001–S019 нет публичного API):
// реализовать, когда организаторы дадут выгрузку или эндпоинт.
type AlfaFetcher struct{}

func (AlfaFetcher) Fetch(ctx context.Context, src postgres.SourceConfig) ([]domain.NewsItem, error) {
	return nil, nil
}
