package ingest

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/devowt/alpha-hackaton/backend/coldstart"
	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

func TestColdStartNewUserAndRoleChangeUseThreeWeeks(t *testing.T) {
	f := newIngestFixture(t)
	ctx := context.Background()
	var ids []int64
	for i, age := range []time.Duration{14 * 24 * time.Hour, 22 * 24 * time.Hour} {
		n := f.news
		n.SourceID, n.ExternalID, n.PublishedAt = f.source, fmt.Sprintf("coldstart-%d", i), time.Now().Add(-age)
		id, _, err := f.store.UpsertNews(ctx, n)
		if err != nil {
			t.Fatal(err)
		}
		ids = append(ids, id)
	}
	original, err := f.store.GetUser(ctx, f.userID)
	if err != nil {
		t.Fatal(err)
	}
	u, err := f.store.CreateUser(ctx, domain.User{CompanyID: original.CompanyID, Email: f.source + "-coldstart@example.test", FullName: "Cold start", Roles: []string{"procurement"}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { f.pool.Exec(context.Background(), "DELETE FROM users WHERE id=$1", u.ID) })
	for i, id := range ids {
		var count int
		if err := f.pool.QueryRow(ctx, "SELECT count(*) FROM news_deliveries WHERE user_id=$1 AND news_id=$2", u.ID, id).Scan(&count); err != nil {
			t.Fatal(err)
		}
		want := 0
		if i == 0 {
			want = 1
		}
		if count != want {
			t.Fatalf("age index %d: deliveries=%d, want %d", i, count, want)
		}
	}
	if _, err := f.pool.Exec(ctx, "UPDATE news_deliveries SET state='done' WHERE user_id=$1", u.ID); err != nil {
		t.Fatal(err)
	}
	if err := f.store.SetUserRoles(ctx, u.ID, []string{"cfo"}); err != nil {
		t.Fatal(err)
	}
	var state string
	if err := f.pool.QueryRow(ctx, "SELECT state FROM news_deliveries WHERE user_id=$1 AND news_id=$2", u.ID, ids[0]).Scan(&state); err != nil {
		t.Fatal(err)
	}
	if state != "pending" {
		t.Fatalf("three-week item was not requeued on role change: %s", state)
	}
}

func TestColdStartSnapshotReplayPreservesLiveRevision(t *testing.T) {
	f := newIngestFixture(t)
	ctx := context.Background()
	const key = "docid_41664"
	// Seed includes this item; a newer live version must win over the frozen data.
	news := f.news
	news.SourceID, news.ExternalID, news.Body = "S077", key, "live revision"
	id, _, err := f.store.UpsertNews(ctx, news)
	if err != nil {
		t.Fatal(err)
	}
	known := map[int64]bool{id: true}
	before, err := f.pool.Query(ctx, "SELECT id FROM news_items WHERE source_id IN ('S077','S142')")
	if err != nil {
		t.Fatal(err)
	}
	for before.Next() {
		var n int64
		if err := before.Scan(&n); err != nil {
			t.Fatal(err)
		}
		known[n] = true
	}
	if err := before.Err(); err != nil {
		t.Fatal(err)
	}
	before.Close()
	t.Cleanup(func() {
		rows, err := f.pool.Query(context.Background(), "SELECT id FROM news_items WHERE source_id IN ('S077','S142')")
		if err != nil {
			t.Error(err)
			return
		}
		var added []int64
		for rows.Next() {
			var n int64
			rows.Scan(&n)
			if !known[n] {
				added = append(added, n)
			}
		}
		rows.Close()
		added = append(added, id)
		f.pool.Exec(context.Background(), "DELETE FROM news_items WHERE id=ANY($1)", added)
	})
	body, err := coldstart.FS.ReadFile("0008_news_coldstart.sql")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.pool.Exec(ctx, string(body)); err != nil {
		t.Fatal(err)
	}
	var first int
	if err := f.pool.QueryRow(ctx, "SELECT count(*) FROM news_items WHERE source_id IN ('S077','S142')").Scan(&first); err != nil {
		t.Fatal(err)
	}
	if first < 300 {
		t.Fatalf("snapshot was not installed: %d", first)
	}
	if _, err := f.pool.Exec(ctx, "UPDATE news_deliveries SET state='done' WHERE news_id=$1 AND user_id=$2", id, f.userID); err != nil {
		t.Fatal(err)
	}
	if _, err := f.pool.Exec(ctx, string(body)); err != nil {
		t.Fatal(err)
	}
	var second int
	var text, state string
	if err := f.pool.QueryRow(ctx, "SELECT count(*) FROM news_items WHERE source_id IN ('S077','S142')").Scan(&second); err != nil {
		t.Fatal(err)
	}
	if first != second {
		t.Fatalf("replay changed count: %d -> %d", first, second)
	}
	if err := f.pool.QueryRow(ctx, "SELECT body FROM news_items WHERE id=$1", id).Scan(&text); err != nil {
		t.Fatal(err)
	}
	if text != "live revision" {
		t.Fatal("seed overwrote live article")
	}
	if err := f.pool.QueryRow(ctx, "SELECT state FROM news_deliveries WHERE news_id=$1 AND user_id=$2", id, f.userID).Scan(&state); err != nil {
		t.Fatal(err)
	}
	if state != "done" {
		t.Fatal("seed replay requeued completed delivery")
	}
}
