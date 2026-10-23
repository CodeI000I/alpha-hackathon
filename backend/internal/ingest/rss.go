package ingest

import (
	"context"
	"encoding/xml"
	"fmt"
	"io"
	"net/http"
	"net/mail"
	"strings"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
)

// RSSFetcher читает RSS 2.0. URL ленты берётся из sources.config.feed_url.
type RSSFetcher struct {
	Client *http.Client
}

type rssDoc struct {
	XMLName xml.Name `xml:"rss"`
	Items   []struct {
		GUID        string `xml:"guid"`
		Link        string `xml:"link"`
		Title       string `xml:"title"`
		Description string `xml:"description"`
		PubDate     string `xml:"pubDate"`
	} `xml:"channel>item"`
}

const maxRSSBytes = 8 << 20

func (f RSSFetcher) Fetch(ctx context.Context, src postgres.SourceConfig) ([]domain.NewsItem, error) {
	feedURL, _ := src.Config["feed_url"].(string)
	if feedURL == "" {
		return nil, fmt.Errorf("source %s: config.feed_url is empty", src.ID)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, feedURL, nil)
	if err != nil {
		return nil, err
	}
	resp, err := f.Client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("rss %s: %s", feedURL, resp.Status)
	}
	var doc rssDoc
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxRSSBytes+1))
	if err != nil {
		return nil, err
	}
	if len(body) > maxRSSBytes {
		return nil, fmt.Errorf("rss source %s: feed exceeds %d bytes", src.ID, maxRSSBytes)
	}
	if err := xml.Unmarshal(body, &doc); err != nil {
		return nil, err
	}
	out := make([]domain.NewsItem, 0, len(doc.Items))
	for _, it := range doc.Items {
		id := strings.TrimSpace(it.GUID)
		if id == "" {
			id = strings.TrimSpace(it.Link)
		}
		if id == "" || strings.TrimSpace(it.Title) == "" {
			return nil, fmt.Errorf("rss source %s: item has no stable identity or title", src.ID)
		}
		published, err := mail.ParseDate(strings.TrimSpace(it.PubDate))
		if err != nil {
			return nil, fmt.Errorf("rss source %s: item has no valid publication date", src.ID)
		}
		parts := strings.Fields(it.PubDate)
		zone := parts[len(parts)-1]
		numericZone := len(zone) == 5 && (zone[0] == '+' || zone[0] == '-')
		// mail.ParseDate may resolve abbreviations using time.Local. Require an
		// explicit numeric offset or UTC name so the worker host cannot change it.
		if !numericZone && zone != "UTC" && zone != "GMT" && zone != "UT" {
			return nil, fmt.Errorf("rss source %s: ambiguous publication timezone", src.ID)
		}
		out = append(out, domain.NewsItem{
			ExternalID: id, URL: it.Link, Title: it.Title, Summary: it.Description, PublishedAt: published,
		})
	}
	return out, nil
}
