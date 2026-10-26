// Package config читает настройки из переменных окружения (12-factor).
package config

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

type Config struct {
	HTTPAddr            string
	SessionCookieSecure bool
	DatabaseURL         string
	StaticDir           string // каталог со сборкой фронтенда; пусто = не отдавать статику
	S3                  S3
	Orchestrator        Orchestrator
	InternalToken       string // токен служебных маршрутов /api/v1/internal/...; пусто = маршруты выключены
	ColdStartEnabled    bool
	IngestPeriod        time.Duration
	RankMaxPerRun       int           // сколько оценок новостей воркер делает за проход (бережёт суточный бюджет LLM)
	RankLookback        time.Duration // оцениваются только новости, опубликованные не раньше now - RankLookback
}

// Orchestrator — AI-оркестратор (LangGraph), который решает, что попадёт в ленту.
type Orchestrator struct {
	URL     string // пусто = заглушка по ключевым словам
	Token   string // совпадает с AI_SERVICE_TOKEN оркестратора
	Timeout time.Duration
}

type S3 struct {
	Endpoint  string
	AccessKey string
	SecretKey string
	Bucket    string
	UseSSL    bool
}

func Load() (Config, error) {
	c := Config{
		HTTPAddr:            env("HTTP_ADDR", ":8080"),
		SessionCookieSecure: env("SESSION_COOKIE_SECURE", "true") == "true",
		DatabaseURL:         os.Getenv("DATABASE_URL"),
		StaticDir:           os.Getenv("STATIC_DIR"),
		Orchestrator: Orchestrator{
			URL:   os.Getenv("ORCHESTRATOR_URL"),
			Token: os.Getenv("ORCHESTRATOR_TOKEN"),
		},
		InternalToken:    os.Getenv("INTERNAL_API_TOKEN"),
		ColdStartEnabled: env("NEWS_COLDSTART_ENABLED", "true") == "true",
		S3: S3{
			Endpoint:  os.Getenv("S3_ENDPOINT"),
			AccessKey: os.Getenv("S3_ACCESS_KEY"),
			SecretKey: os.Getenv("S3_SECRET_KEY"),
			Bucket:    env("S3_BUCKET", "company-files"),
			UseSSL:    env("S3_USE_SSL", "false") == "true",
		},
	}
	if c.Orchestrator.Token == "" {
		c.Orchestrator.Token = os.Getenv("AI_SERVICE_TOKEN")
	}
	var err error
	for _, d := range []struct {
		key, def string
		dst      *time.Duration
	}{
		{"INGEST_PERIOD", "15m", &c.IngestPeriod},
		{"ORCHESTRATOR_TIMEOUT", "5m", &c.Orchestrator.Timeout},
		{"RANK_LOOKBACK", "504h", &c.RankLookback},
	} {
		if *d.dst, err = time.ParseDuration(env(d.key, d.def)); err != nil || *d.dst <= 0 {
			return c, fmt.Errorf("%s: want a positive duration like 15m, got %q", d.key, env(d.key, d.def))
		}
	}
	if c.RankMaxPerRun, err = strconv.Atoi(env("RANK_MAX_PER_RUN", "20")); err != nil || c.RankMaxPerRun < 1 {
		return c, fmt.Errorf("RANK_MAX_PER_RUN: want a positive integer, got %q", env("RANK_MAX_PER_RUN", "20"))
	}
	if c.DatabaseURL == "" {
		return c, fmt.Errorf("DATABASE_URL is required")
	}
	return c, nil
}

func env(key, def string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return def
}
