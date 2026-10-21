// Package config читает настройки из переменных окружения (12-factor).
package config

import (
	"fmt"
	"os"
	"time"
)

type Config struct {
	HTTPAddr        string
	DatabaseURL     string
	StaticDir       string // каталог со сборкой фронтенда; пусто = не отдавать статику
	S3              S3
	OrchestratorURL string // адрес AI-оркестратора (LangGraph), который решает, что попадёт в ленту
	IngestPeriod    time.Duration
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
		HTTPAddr:        env("HTTP_ADDR", ":8080"),
		DatabaseURL:     os.Getenv("DATABASE_URL"),
		StaticDir:       os.Getenv("STATIC_DIR"),
		OrchestratorURL: os.Getenv("ORCHESTRATOR_URL"),
		S3: S3{
			Endpoint:  os.Getenv("S3_ENDPOINT"),
			AccessKey: os.Getenv("S3_ACCESS_KEY"),
			SecretKey: os.Getenv("S3_SECRET_KEY"),
			Bucket:    env("S3_BUCKET", "company-files"),
			UseSSL:    env("S3_USE_SSL", "false") == "true",
		},
	}
	period, err := time.ParseDuration(env("INGEST_PERIOD", "15m"))
	if err != nil {
		return c, fmt.Errorf("INGEST_PERIOD: %w", err)
	}
	c.IngestPeriod = period
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
