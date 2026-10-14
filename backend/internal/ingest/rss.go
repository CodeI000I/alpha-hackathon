package ingest

import (
	"context"
	"encoding/xml"
	"fmt"
	"net/http"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
)

// RSSFetcher читает RSS 2.0. URL ленты берётся из sources.config.feed_url.
type RSSFetcher struct {
	Client *http.Client
}

type rssDoc struct {
	Items []struct {
		GUID        string `xml:"guid"`
		Link        string `xml:"link"`
		Title       string `xml:"title"`
		Description string `xml:"description"`
		PubDate     string `xml:"pubDate"`
	} `xml:"channel>item"`
}

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
	if err := xml.NewDecoder(resp.Body).Decode(&doc); err != nil {
		return nil, err
	}
	out := make([]domain.NewsItem, 0, len(doc.Items))
	for _, it := range doc.Items {
		id := it.GUID
		if id == "" {
			id = it.Link
		}
		published, err := time.Parse(time.RFC1123Z, it.PubDate)
		if err != nil {
			published = time.Now()
		}
		out = append(out, domain.NewsItem{
			ExternalID: id, URL: it.Link, Title: it.Title, Summary: it.Description, PublishedAt: published,
		})
	}
	return out, nil
}
