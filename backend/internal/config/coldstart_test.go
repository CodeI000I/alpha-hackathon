package config

import (
	"testing"
	"time"
)

func TestColdStartDefaultsAndOptOut(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgresql://localhost/test")
	t.Setenv("RANK_LOOKBACK", "")
	t.Setenv("NEWS_COLDSTART_ENABLED", "")
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.ColdStartEnabled || cfg.RankLookback != 21*24*time.Hour {
		t.Fatalf("enabled=%v, lookback=%s; want true, 504h", cfg.ColdStartEnabled, cfg.RankLookback)
	}
	t.Setenv("NEWS_COLDSTART_ENABLED", "false")
	cfg, err = Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.ColdStartEnabled {
		t.Fatal("explicit opt-out was ignored")
	}
}
