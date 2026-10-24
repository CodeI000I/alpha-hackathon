// Package ingest собирает новости из источников и раскладывает их по лентам пользователей.
package ingest

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/feed"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
)

// Fetcher — адаптер одного типа источника (Альфа-Банк, RSS, JSON API СМИ, ...).
type Fetcher interface {
	Fetch(ctx context.Context, src postgres.SourceConfig) ([]domain.NewsItem, error)
}

const maxAttempts = 8

type Pipeline struct {
	Store     *postgres.Store
	Ranker    feed.Ranker
	Fetchers  map[string]Fetcher // ключ = sources.adapter
	Log       *slog.Logger
	MaxPerRun int
	Lookback  time.Duration
	Lease     time.Duration

	pausedUntil time.Time
	oldestNext  bool
}

// RunOnce собирает источники, затем обрабатывает ограниченное число доставок.
func (p *Pipeline) RunOnce(ctx context.Context) error {
	if err := p.Collect(ctx); err != nil {
		return err
	}
	return p.Rank(ctx)
}

// Collect сохраняет новости всех включённых источников.
func (p *Pipeline) Collect(ctx context.Context) error {
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
	return nil
}

// Rank rechecks recent work for backfill, then makes at most MaxPerRun ranked deliveries.
func (p *Pipeline) Rank(ctx context.Context) error {
	if wait := time.Until(p.pausedUntil); wait > 0 {
		p.logger().Info("ranking paused by orchestrator", "resume_in", wait.Round(time.Second).String())
		return nil
	}
	since := time.Time{}
	if p.Lookback > 0 {
		since = time.Now().Add(-p.Lookback)
	}
	if !since.IsZero() {
		if err := p.Store.EnqueueRecentNewsDeliveries(ctx, since); err != nil {
			return err
		}
	}
	limit := p.MaxPerRun
	if limit < 1 {
		limit = 20
	}
	lease := p.Lease
	if lease < 10*time.Minute {
		lease = 10 * time.Minute
	}
	for range limit {
		newestFirst := p.nextClaimNewestFirst()
		deliveries, err := p.Store.ClaimNewsDeliveriesSinceOrder(ctx, 1, lease, since, newestFirst)
		if err != nil {
			return err
		}
		if len(deliveries) == 0 {
			return nil
		}
		d := deliveries[0]
		if d.User.ID == 0 || d.User.CompanyID == nil || !d.HasCompany || len(d.User.Roles) == 0 {
			if _, err := p.Store.CompleteNewsDelivery(ctx, d, nil); err != nil {
				return err
			}
			continue
		}
		roles, err := p.Store.CompanyRoles(ctx, *d.User.CompanyID)
		if err != nil {
			if retryErr := p.Store.RetryNewsDelivery(ctx, d, "rank_failed"); retryErr != nil {
				return retryErr
			}
			return err
		}
		if len(roles) == 0 {
			if _, err := p.Store.CompleteNewsDelivery(ctx, d, nil); err != nil {
				return err
			}
			continue
		}
		if p.Ranker == nil {
			return fmt.Errorf("ranker is not configured")
		}
		requestNews := feed.NewsFrom(d.News)
		requestNews.Revision = d.Revision
		matches, rankErr := p.Ranker.Rank(ctx, feed.Request{News: requestNews, Roles: roles, Company: d.Company})
		if rankErr != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			if retryErr := p.retryRank(ctx, d, rankErr); retryErr != nil {
				return retryErr
			}
			var remote *feed.Error
			if !errors.As(rankErr, &remote) || !remote.Permanent {
				return nil
			}
			continue
		}
		completed, err := p.Store.CompleteNewsDelivery(ctx, d, matches)
		if err != nil {
			if retryErr := p.Store.RetryNewsDelivery(ctx, d, "persistence_failed"); retryErr != nil {
				return retryErr
			}
			p.logger().Error("complete feed delivery", "news", d.NewsID, "user", d.UserID, "err", err)
			continue
		}
		if !completed {
			p.logger().Info("stale news delivery ignored", "news", d.NewsID, "user", d.UserID)
		}
	}
	return nil
}

func (p *Pipeline) nextClaimNewestFirst() bool {
	newestFirst := !p.oldestNext
	p.oldestNext = !p.oldestNext
	return newestFirst
}

func (p *Pipeline) processDeliveries(ctx context.Context) error { return p.Rank(ctx) }

func (p *Pipeline) retryRank(ctx context.Context, d postgres.NewsDelivery, rankErr error) error {
	var remote *feed.Error
	if errors.As(rankErr, &remote) && remote.Permanent {
		return p.Store.RetryNewsDeliveryAt(ctx, d, "rank_rejected", time.Now(), true)
	}
	if errors.As(rankErr, &remote) && remote.RetryAfter > 0 {
		p.pausedUntil = time.Now().Add(remote.RetryAfter)
		return p.Store.RetryNewsDeliveryAt(ctx, d, "rank_deferred", p.pausedUntil, false)
	}
	attempt := d.Attempts
	return p.Store.RetryNewsDeliveryAt(ctx, d, "rank_failed", time.Now().Add(backoff(attempt)), attempt >= maxAttempts)
}

// backoff — пауза перед повтором: 1, 2, 4, … минут, не больше 6 часов.
func backoff(attempt int) time.Duration {
	if attempt < 1 {
		attempt = 1
	}
	return min(time.Minute<<min(attempt-1, 10), 6*time.Hour)
}

func (p *Pipeline) logger() *slog.Logger {
	if p.Log != nil {
		return p.Log
	}
	return slog.Default()
}
