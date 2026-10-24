package httpapi

import (
	"fmt"
	"testing"
	"time"
)

func TestLoginLimiterAllowsTenAttemptsPerMinuteAndBoundsKeys(t *testing.T) {
	limiter := &loginLimiterState{entries: make(map[string]loginWindow)}
	now := time.Now()
	for i := 0; i < 10; i++ {
		if !limiter.allow("192.0.2.1", now) {
			t.Fatalf("attempt %d unexpectedly rejected", i+1)
		}
	}
	if limiter.allow("192.0.2.1", now) {
		t.Fatal("eleventh attempt was not throttled")
	}
	if !limiter.allow("192.0.2.1", now.Add(time.Minute)) {
		t.Fatal("attempt after window was not allowed")
	}
	for i := 0; i < 1100; i++ {
		limiter.allow(fmt.Sprintf("192.0.2.%d", i), now)
	}
	if len(limiter.entries) > 1024 {
		t.Fatalf("limiter grew to %d entries", len(limiter.entries))
	}
}
