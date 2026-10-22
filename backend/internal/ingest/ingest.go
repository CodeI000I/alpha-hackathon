// Package ingest собирает новости из источников и раскладывает их по лентам пользователей.
package ingest

import (
	"context"
	"errors"
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

// maxAttempts — после стольких неудач подряд оценка новости снимается с очереди (status = failed).
const maxAttempts = 8

type Pipeline struct {
	Store     *postgres.Store
	Ranker    feed.Ranker
	Fetchers  map[string]Fetcher // ключ = sources.adapter
	Log       *slog.Logger
	MaxPerRun int           // оценок за проход: первая загрузка RSS не должна съесть суточный бюджет LLM
	Lookback  time.Duration // оцениваются только новости, опубликованные за этот период

	pausedUntil time.Time // оркестратор ответил Retry-After (лимит или бюджет LLM)
}

// RunOnce — один проход: собрать новости со всех включённых источников, оценить их и разложить по лентам.
func (p *Pipeline) RunOnce(ctx context.Context) error {
	if err := p.Collect(ctx); err != nil {
		return err
	}
	return p.Rank(ctx)
}

// Collect сохраняет новости со всех включённых источников. Оценивает их Rank.
func (p *Pipeline) Collect(ctx context.Context) error {
	sources, err := p.Store.EnabledSources(ctx)
	if err != nil {
		return err
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
		added := 0
		for _, n := range items {
			n.SourceID = src.ID
			_, isNew, err := p.Store.UpsertNews(ctx, n)
			if err != nil {
				return err
			}
			if isNew {
				added++
			}
		}
		p.Log.Info("source processed", "source", src.ID, "items", len(items), "new", added)
	}
	return nil
}

// Rank ставит свежие новости в очередь оценок, выполняет не больше MaxPerRun оценок
// и раскладывает готовые результаты по лентам.
func (p *Pipeline) Rank(ctx context.Context) error {
	since := time.Now().Add(-p.Lookback)
	queued, err := p.Store.EnqueueRankings(ctx, since)
	if err != nil {
		return err
	}
	if wait := time.Until(p.pausedUntil); wait > 0 {
		p.Log.Info("ranking paused by orchestrator", "queued", queued, "resume_in", wait.Round(time.Second).String())
	} else if err := p.rankDue(ctx); err != nil {
		return err
	}
	added, err := p.Store.FanOutFeed(ctx, since)
	if err != nil {
		return err
	}
	p.Log.Info("ranking done", "queued", queued, "feed_items", added)
	return nil
}

func (p *Pipeline) rankDue(ctx context.Context) error {
	due, err := p.Store.DueRankings(ctx, p.MaxPerRun)
	if err != nil {
		return err
	}
	companies := map[int64]domain.Company{}
	for _, r := range due {
		c, ok := companies[r.CompanyID]
		if !ok {
			var err error
			if c, err = p.Store.GetCompany(ctx, r.CompanyID); err != nil {
				return err
			}
			companies[c.ID] = c
		}
		var matches []feed.Match
		var err error
		if len(r.Roles) > 0 { // роли могли снять после постановки в очередь
			matches, err = p.Ranker.Rank(ctx, feed.Request{News: feed.NewsFrom(r.News), Roles: r.Roles, Company: c})
		}
		if err == nil {
			if err := p.Store.FinishRanking(ctx, r.News.ID, r.CompanyID, r.Roles, matches); err != nil {
				return err
			}
			continue
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}

		now := time.Now()
		var fe *feed.Error
		errors.As(err, &fe)
		switch {
		case fe != nil && fe.Permanent:
			// Оркестратор отверг эту новость: повтор не поможет, переходим к следующей.
			p.Log.Warn("rank rejected", "news", r.News.ID, "company", r.CompanyID, "err", err)
			if err := p.Store.RetryRanking(ctx, r.News.ID, r.CompanyID, r.Attempts+1, now, true, err.Error()); err != nil {
				return err
			}
			continue
		case fe != nil && fe.RetryAfter > 0:
			// Лимит или суточный бюджет LLM: попытку не засчитываем, ждём, сколько просят.
			p.pausedUntil = now.Add(fe.RetryAfter)
			p.Log.Warn("rank postponed", "news", r.News.ID, "company", r.CompanyID, "until", p.pausedUntil, "err", err)
			if err := p.Store.RetryRanking(ctx, r.News.ID, r.CompanyID, r.Attempts, p.pausedUntil, false, err.Error()); err != nil {
				return err
			}
		default:
			attempt := r.Attempts + 1
			p.Log.Warn("rank failed", "news", r.News.ID, "company", r.CompanyID, "attempt", attempt, "err", err)
			if err := p.Store.RetryRanking(ctx, r.News.ID, r.CompanyID, attempt, now.Add(backoff(attempt)), attempt >= maxAttempts, err.Error()); err != nil {
				return err
			}
		}
		// Оркестратор недоступен или просит подождать: следующие оценки упадут так же,
		// остаток очереди — в следующий проход.
		return nil
	}
	return nil
}

// backoff — пауза перед повтором: 1, 2, 4, … минут, не больше 6 часов.
func backoff(attempt int) time.Duration {
	return min(time.Minute<<min(attempt-1, 10), 6*time.Hour)
}
