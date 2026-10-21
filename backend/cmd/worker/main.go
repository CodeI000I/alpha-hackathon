// Воркер: периодически собирает новости из источников и строит персональные ленты.
package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/config"
	"github.com/devowt/alpha-hackaton/backend/internal/feed"
	"github.com/devowt/alpha-hackaton/backend/internal/ingest"
	"github.com/devowt/alpha-hackaton/backend/internal/orchestrator"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
	"github.com/devowt/alpha-hackaton/backend/migrations"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	cfg, err := config.Load()
	if err != nil {
		log.Error("config", "err", err)
		os.Exit(1)
	}
	store, err := postgres.New(ctx, cfg.DatabaseURL)
	if err != nil {
		log.Error("postgres", "err", err)
		os.Exit(1)
	}
	defer store.Close()
	if err := store.Migrate(ctx, migrations.FS); err != nil {
		log.Error("migrate", "err", err)
		os.Exit(1)
	}

	var ranker feed.Ranker = feed.KeywordRanker{}
	if cfg.OrchestratorURL != "" {
		ranker = orchestrator.New(cfg.OrchestratorURL)
	} else {
		log.Warn("ORCHESTRATOR_URL is empty: using keyword ranker stub")
	}
	httpClient := &http.Client{Timeout: 30 * time.Second}
	p := &ingest.Pipeline{
		Store:  store,
		Ranker: ranker,
		Fetchers: map[string]ingest.Fetcher{
			"alfa": ingest.AlfaFetcher{},
			"rss":  ingest.RSSFetcher{Client: httpClient},
		},
		Log: log,
	}

	ticker := time.NewTicker(cfg.IngestPeriod)
	defer ticker.Stop()
	for {
		if err := p.RunOnce(ctx); err != nil {
			log.Error("ingest run failed", "err", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
