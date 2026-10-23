package ingest

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
)

type rssTransport func(*http.Request) (*http.Response, error)

func (f rssTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func fixtureRSS(body string) RSSFetcher {
	return RSSFetcher{Client: &http.Client{Transport: rssTransport(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}, nil
	})}}
}

func TestRSSDatesDoNotBecomeFetchTime(t *testing.T) {
	src := postgres.SourceConfig{ID: "fixture", Config: map[string]any{"feed_url": "https://feed.example/rss"}}
	for _, date := range []string{"Fri, 23 Oct 2026 15:30:00 +0300", "Fri, 23 Oct 2026 12:30:00 GMT"} {
		t.Run(date, func(t *testing.T) {
			fetcher := fixtureRSS(fmt.Sprintf(`<rss><channel><item><guid>id-1</guid><title>Title</title><pubDate>%s</pubDate></item></channel></rss>`, date))
			items, err := fetcher.Fetch(context.Background(), src)
			want := time.Date(2026, 10, 23, 12, 30, 0, 0, time.UTC)
			if err != nil || len(items) != 1 || !items[0].PublishedAt.Equal(want) {
				t.Fatalf("got %#v, %v; want original publication time %s", items, err, want)
			}
		})
	}
}

func TestRSSRejectsInvalidInput(t *testing.T) {
	src := postgres.SourceConfig{ID: "fixture", Config: map[string]any{"feed_url": "https://feed.example/rss"}}
	for name, body := range map[string]string{
		"unknown date":     `<rss><channel><item><guid>x</guid><title>T</title><pubDate>unknown</pubDate></item></channel></rss>`,
		"missing identity": `<rss><channel><item><title>T</title><pubDate>Fri, 23 Oct 2026 12:30:00 GMT</pubDate></item></channel></rss>`,
		"wrong root":       `<html><body>Provider failed</body></html>`,
		"oversize":         `<rss><channel><title>` + strings.Repeat("x", 8<<20) + `</title></channel></rss>`,
	} {
		t.Run(name, func(t *testing.T) {
			items, err := fixtureRSS(body).Fetch(context.Background(), src)
			if err == nil {
				t.Fatalf("accepted invalid feed: %#v", items)
			}
		})
	}
}

func TestAlfaUnavailableIsNotSuccessfulEmptyFetch(t *testing.T) {
	if _, err := (AlfaFetcher{}).Fetch(context.Background(), postgres.SourceConfig{ID: "fixture"}); err == nil {
		t.Fatal("unconfigured adapter must expose unavailability")
	}
}

func TestRSSAmbiguousZoneDoesNotDependOnWorkerTimezone(t *testing.T) {
	previous := time.Local
	t.Cleanup(func() { time.Local = previous })
	src := postgres.SourceConfig{ID: "fixture", Config: map[string]any{"feed_url": "https://feed.example/rss"}}
	for _, location := range []*time.Location{time.UTC, time.FixedZone("PST", -8*3600)} {
		time.Local = location
		body := `<rss><channel><item><guid>x</guid><title>T</title><pubDate>Fri, 23 Oct 2026 12:30:00 PST</pubDate></item></channel></rss>`
		if _, err := fixtureRSS(body).Fetch(context.Background(), src); err == nil {
			t.Fatalf("ambiguous PST accepted with worker local zone %s", location)
		}
	}
}
