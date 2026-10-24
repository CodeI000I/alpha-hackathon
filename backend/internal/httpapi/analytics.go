package httpapi

import (
	"bytes"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
)

const (
	maxAnalyticsRequest  = 2 << 20
	maxAnalyticsResponse = 10 << 20
)

var safeAnalyticsSegment = regexp.MustCompile(`^[A-Za-z0-9_-]{1,200}$`)

func allowedAnalyticsPath(method, path string) bool {
	parts := strings.Split(path, "/")
	for _, part := range parts {
		if !safeAnalyticsSegment.MatchString(part) {
			return false
		}
	}
	switch {
	case path == "situation":
		return method == http.MethodGet
	case path == "documents":
		return method == http.MethodGet
	case path == "issues":
		return method == http.MethodGet
	case len(parts) == 2 && parts[0] == "issues":
		return method == http.MethodGet
	case len(parts) == 3 && parts[0] == "issues":
		switch parts[2] {
		case "evidence", "history":
			return method == http.MethodGet
		case "state":
			return method == http.MethodGet || method == http.MethodPatch
		case "questions":
			return method == http.MethodPost
		}
	case len(parts) == 2 && parts[0] == "conversations":
		return method == http.MethodGet
	case path == "refresh":
		return method == http.MethodPost
	case len(parts) == 2 && parts[0] == "jobs":
		return method == http.MethodGet
	}
	return false
}

func (s *Server) analyticsProxy(w http.ResponseWriter, r *http.Request) {
	u, ok := currentUser(r)
	if !ok || u.CompanyID == nil {
		writeJSON(w, http.StatusForbidden, apiError{"Профиль компании не настроен"})
		return
	}
	role := strings.TrimSpace(r.URL.Query().Get("role"))
	roleAllowed := false
	for _, candidate := range u.Roles {
		if role == candidate {
			roleAllowed = true
			break
		}
	}
	if !roleAllowed {
		writeJSON(w, http.StatusForbidden, apiError{"Роль не назначена пользователю"})
		return
	}
	path := strings.TrimPrefix(r.PathValue("rest"), "/")
	if !allowedAnalyticsPath(r.Method, path) {
		writeJSON(w, http.StatusNotFound, apiError{"Метод API не найден"})
		return
	}
	if s.AnalyticsURL == "" || s.AnalyticsToken == "" {
		writeJSON(w, http.StatusServiceUnavailable, apiError{"Аналитика временно недоступна"})
		return
	}
	base, err := url.Parse(s.AnalyticsURL)
	if err != nil || (base.Scheme != "http" && base.Scheme != "https") || base.Host == "" || base.User != nil || base.Fragment != "" {
		s.Log.Error("invalid analytics URL configuration")
		writeJSON(w, http.StatusServiceUnavailable, apiError{"Аналитика временно недоступна"})
		return
	}
	query := r.URL.Query()
	query.Del("role") // доверенный scope передаётся только через заголовок ниже
	target := *base
	target.Path = strings.TrimRight(base.Path, "/") + "/v1/analytics/" + path
	target.RawPath = ""
	target.RawQuery = query.Encode()
	body, err := io.ReadAll(io.LimitReader(r.Body, maxAnalyticsRequest+1))
	if err != nil {
		badRequest(w, "invalid request body")
		return
	}
	if len(body) > maxAnalyticsRequest {
		writeJSON(w, http.StatusRequestEntityTooLarge, apiError{"request body too large"})
		return
	}
	proxyReq, err := http.NewRequestWithContext(r.Context(), r.Method, target.String(), bytes.NewReader(body))
	if err != nil {
		s.fail(w, err, "")
		return
	}
	if ct := r.Header.Get("Content-Type"); ct != "" {
		proxyReq.Header.Set("Content-Type", ct)
	}
	if accept := r.Header.Get("Accept"); accept != "" {
		proxyReq.Header.Set("Accept", accept)
	}
	proxyReq.Header.Set("Authorization", "Bearer "+s.AnalyticsToken)
	proxyReq.Header.Set("X-User-ID", fmt.Sprint(u.ID))
	proxyReq.Header.Set("X-Company-ID", fmt.Sprint(*u.CompanyID))
	proxyReq.Header.Set("X-Role", role)
	proxyReq.Header.Set("X-Tenant-ID", "alpha")
	client := &http.Client{Timeout: 5 * time.Minute, CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }}
	resp, err := client.Do(proxyReq)
	if err != nil {
		writeJSON(w, http.StatusBadGateway, apiError{"Не удалось связаться с аналитикой"})
		return
	}
	defer resp.Body.Close()
	response, err := io.ReadAll(io.LimitReader(resp.Body, maxAnalyticsResponse+1))
	if err != nil {
		writeJSON(w, http.StatusBadGateway, apiError{"Не удалось прочитать ответ аналитики"})
		return
	}
	if len(response) > maxAnalyticsResponse {
		writeJSON(w, http.StatusBadGateway, apiError{"Ответ аналитики превышает лимит"})
		return
	}
	if ct := resp.Header.Get("Content-Type"); ct != "" {
		w.Header().Set("Content-Type", ct)
	}
	if retry := resp.Header.Get("Retry-After"); retry != "" {
		w.Header().Set("Retry-After", retry)
	}
	w.WriteHeader(resp.StatusCode)
	_, _ = w.Write(response)
}
