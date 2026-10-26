// Сервер API: JSON для фронтенда + раздача собранного фронтенда.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/devowt/alpha-hackaton/backend/coldstart"
	"github.com/devowt/alpha-hackaton/backend/internal/config"
	"github.com/devowt/alpha-hackaton/backend/internal/httpapi"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/files"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
	"github.com/devowt/alpha-hackaton/backend/migrations"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	if err := run(log); err != nil {
		log.Error("server stopped", "err", err)
		os.Exit(1)
	}
}

func run(log *slog.Logger) error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	cfg, err := config.Load()
	if err != nil {
		return err
	}
	store, err := postgres.New(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	defer store.Close()
	if err := store.Migrate(ctx, migrations.FS); err != nil {
		return err
	}
	if cfg.ColdStartEnabled {
		if err := store.Migrate(ctx, coldstart.FS); err != nil {
			return err
		}
	}

	srv := &httpapi.Server{Store: store, StaticDir: cfg.StaticDir, InternalToken: cfg.InternalToken,
		RequireAuth: true, CookieSecure: cfg.SessionCookieSecure,
		AnalyticsURL: cfg.Orchestrator.URL, AnalyticsToken: cfg.Orchestrator.Token, Log: log}
	if cfg.S3.Endpoint != "" {
		if srv.Files, err = files.New(ctx, cfg.S3); err != nil {
			return err
		}
	} else {
		log.Warn("S3_ENDPOINT is empty: file uploads are disabled")
	}

	httpSrv := &http.Server{Addr: cfg.HTTPAddr, Handler: srv.Handler(), ReadHeaderTimeout: 10 * time.Second}
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		_ = httpSrv.Shutdown(shutdownCtx)
	}()
	log.Info("listening", "addr", cfg.HTTPAddr)
	if err := httpSrv.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}
