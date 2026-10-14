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

// RunOnce — один проход: собрать новости со всех включённых источников и
// для каждой новой новости построить элементы лент.
func (p *Pipeline) RunOnce(ctx context.Context) error {
	sources, err := p.Store.EnabledSources(ctx)
	if err != nil {
		return err
	}
	users, err := p.Store.UsersForFeed(ctx)
	if err != nil {
		return err
	}
	companies := map[int64]domain.Company{}
	for _, u := range users {
		if u.CompanyID == nil {
			continue
		}
		if _, ok := companies[*u.CompanyID]; !ok {
			c, err := p.Store.GetCompany(ctx, *u.CompanyID)
			if err != nil {
				return err
			}
			companies[c.ID] = c
		}
	}

	for _, src := range sources {
		f, ok := p.Fetchers[src.Adapter]
		if !ok {
			p.Log.Warn("no fetcher for adapter", "source", src.ID, "adapter", src.Adapter)
			continue
		}
		items, err := f.Fetch(ctx, src)
		if err != nil {
			p.Log.Error("fetch failed", "source", src.ID, "err", err)
			continue
		}
		for _, n := range items {
			n.SourceID = src.ID
			id, isNew, err := p.Store.UpsertNews(ctx, n)
			if err != nil {
				return err
			}
			if !isNew {
				continue
			}
			n.ID = id
			p.distribute(ctx, n, users, companies)
		}
		p.Log.Info("source processed", "source", src.ID, "items", len(items))
	}
	return nil
}

func (p *Pipeline) distribute(ctx context.Context, n domain.NewsItem, users []domain.User, companies map[int64]domain.Company) {
	for _, u := range users {
		if len(u.Roles) == 0 || u.CompanyID == nil {
			continue
		}
		matches, err := p.Ranker.Rank(ctx, feed.Request{News: n, Roles: u.Roles, Company: companies[*u.CompanyID]})
		if err != nil {
			p.Log.Error("rank failed", "news", n.ID, "user", u.ID, "err", err)
			continue
		}
		for _, m := range matches {
			item := domain.FeedItem{Kind: m.Kind, Score: m.Score, Insight: m.Insight, Elements: m.Elements}
			if err := p.Store.AddFeedItem(ctx, u.ID, m.Role, n.ID, item); err != nil {
				p.Log.Error("add feed item", "err", err)
			}
		}
	}
}
