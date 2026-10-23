// Package ingest собирает новости из источников и раскладывает их по лентам пользователей.
package ingest

import (
	"context"
	"log/slog"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/feed"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
)

// Fetcher — адаптер одного типа источника (Альфа-Банк, RSS, JSON API СМИ, ...).
type Fetcher interface {
	Fetch(ctx context.Context, src postgres.SourceConfig) ([]domain.NewsItem, error)
}

type Pipeline struct {
	Store    *postgres.Store
	Ranker   feed.Ranker
	Fetchers map[string]Fetcher // ключ = sources.adapter
	Log      *slog.Logger
}

// RunOnce собирает источники и обрабатывает ограниченную пачку устойчивых заданий.
func (p *Pipeline) RunOnce(ctx context.Context) error {
	if err := p.processDeliveries(ctx); err != nil {
		return err
	}
	sources, err := p.Store.EnabledSources(ctx)
	if err != nil {
		return err
	}
	for _, src := range sources {
		f, ok := p.Fetchers[src.Adapter]
		if !ok {
			p.logger().Warn("no fetcher for adapter", "source", src.ID, "adapter", src.Adapter)
			continue
		}
		items, err := f.Fetch(ctx, src)
		if err != nil {
			p.logger().Error("fetch failed", "source", src.ID, "err", err)
			continue
		}
		for _, n := range items {
			n.SourceID = src.ID
			if _, _, err := p.Store.UpsertNews(ctx, n); err != nil {
				return err
			}
		}
		p.logger().Info("source processed", "source", src.ID, "items", len(items))
	}
	return p.processDeliveries(ctx)
}

func (p *Pipeline) processDeliveries(ctx context.Context) error {
	for range 100 {
		deliveries, err := p.Store.ClaimNewsDeliveries(ctx, 1)
		if err != nil {
			return err
		}
		if len(deliveries) == 0 {
			return nil
		}
		d := deliveries[0]
		var matches []feed.Match
		var rankErr error
		if d.User.ID != 0 && d.User.CompanyID != nil && d.HasCompany && len(d.User.Roles) > 0 {
			matches, rankErr = p.Ranker.Rank(ctx, feed.Request{News: d.News, Roles: d.User.Roles, Company: d.Company})
		}
		if rankErr != nil {
			p.logger().Error("rank failed", "news", d.NewsID, "user", d.UserID, "err", rankErr)
			if retryErr := p.Store.RetryNewsDelivery(ctx, d, "rank_failed"); retryErr != nil {
				return retryErr
			}
			continue
		}
		completed, completeErr := p.Store.CompleteNewsDelivery(ctx, d, matches)
		if completeErr != nil {
			p.logger().Error("complete feed delivery", "news", d.NewsID, "user", d.UserID, "err", completeErr)
			if retryErr := p.Store.RetryNewsDelivery(ctx, d, "persistence_failed"); retryErr != nil {
				return retryErr
			}
			continue
		}
		if !completed {
			p.logger().Info("stale news delivery ignored", "news", d.NewsID, "user", d.UserID)
		}
	}
	return nil
}

func (p *Pipeline) logger() *slog.Logger {
	if p.Log != nil {
		return p.Log
	}
	return slog.Default()
}
