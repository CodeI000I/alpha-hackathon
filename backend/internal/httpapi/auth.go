package httpapi

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"golang.org/x/crypto/bcrypt"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
)

const (
	sessionCookie = "alpha_session"
	sessionTTL    = 7 * 24 * time.Hour
	maxAuthBody   = 8 << 10
)

type authenticatedUserKey struct{}

func currentUser(r *http.Request) (domain.User, bool) {
	u, ok := r.Context().Value(authenticatedUserKey{}).(domain.User)
	return u, ok
}

func (s *Server) authorizeUserID(w http.ResponseWriter, r *http.Request, id int64) bool {
	if !s.RequireAuth {
		return true
	}
	u, ok := currentUser(r)
	if ok && u.ID == id {
		return true
	}
	writeJSON(w, http.StatusForbidden, apiError{"Недостаточно прав"})
	return false
}

func (s *Server) authorizeCompanyID(w http.ResponseWriter, r *http.Request, id int64) bool {
	if !s.RequireAuth {
		return true
	}
	u, ok := currentUser(r)
	if ok && u.CompanyID != nil && *u.CompanyID == id {
		return true
	}
	writeJSON(w, http.StatusForbidden, apiError{"Недостаточно прав"})
	return false
}

func (s *Server) guard(next http.Handler) http.Handler {
	if !s.RequireAuth {
		return next
	}
	return s.requireAuth(next)
}

func (s *Server) requireAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead && r.Method != http.MethodOptions && !sameOriginRequest(r) {
			writeJSON(w, http.StatusForbidden, apiError{"Запрос должен быть отправлен с этого сайта"})
			return
		}
		cookie, err := r.Cookie(sessionCookie)
		if err != nil || cookie.Value == "" {
			writeJSON(w, http.StatusUnauthorized, apiError{"Требуется вход"})
			return
		}
		u, err := s.Store.GetUserBySession(r.Context(), digestToken(cookie.Value))
		if errors.Is(err, postgres.ErrNotFound) {
			writeJSON(w, http.StatusUnauthorized, apiError{"Сессия истекла или недействительна"})
			return
		}
		if err != nil {
			s.fail(w, err, "")
			return
		}
		next.ServeHTTP(w, r.WithContext(withUser(r, u)))
	})
}

func withUser(r *http.Request, u domain.User) context.Context {
	return context.WithValue(r.Context(), authenticatedUserKey{}, u)
}

func newSessionToken() (string, string, error) {
	var b [32]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", "", err
	}
	token := hex.EncodeToString(b[:])
	return token, digestToken(token), nil
}

func digestToken(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

func (s *Server) setSessionCookie(w http.ResponseWriter, token string, expires time.Time) {
	http.SetCookie(w, &http.Cookie{Name: sessionCookie, Value: token, Path: "/", Expires: expires,
		MaxAge: int(time.Until(expires).Seconds()), HttpOnly: true, Secure: s.CookieSecure, SameSite: http.SameSiteStrictMode})
}

func (s *Server) clearSessionCookie(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{Name: sessionCookie, Value: "", Path: "/", MaxAge: -1,
		HttpOnly: true, Secure: s.CookieSecure, SameSite: http.SameSiteStrictMode})
}

func sameOriginRequest(r *http.Request) bool {
	if site := strings.ToLower(r.Header.Get("Sec-Fetch-Site")); site == "cross-site" {
		return false
	}
	origin := r.Header.Get("Origin")
	if origin == "" {
		return r.Header.Get("Sec-Fetch-Site") == "same-origin"
	}
	u, err := url.Parse(origin)
	return err == nil && u.Host != "" && u.User == nil && (u.Path == "" || u.Path == "/") && u.RawQuery == "" && u.Fragment == "" &&
		strings.EqualFold(u.Host, r.Host) && (u.Scheme == "http" || u.Scheme == "https")
}

func decodeAuthJSON(w http.ResponseWriter, r *http.Request, dst any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, maxAuthBody)
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	if err := d.Decode(dst); err != nil {
		badRequest(w, "invalid authentication request")
		return false
	}
	var trailing any
	if err := d.Decode(&trailing); !errors.Is(err, io.EOF) {
		badRequest(w, "request must contain one JSON object")
		return false
	}
	return true
}

func (s *Server) login(w http.ResponseWriter, r *http.Request) {
	if s.RequireAuth && !sameOriginRequest(r) {
		writeJSON(w, http.StatusForbidden, apiError{"Запрос должен быть отправлен с этого сайта"})
		return
	}
	if !s.allowAuthAttempt(w, r) {
		return
	}
	var in struct {
		Email    string `json:"email"`
		Password string `json:"password"`
	}
	if !decodeAuthJSON(w, r, &in) {
		return
	}
	in.Email = strings.TrimSpace(in.Email)
	if in.Email == "" || len(in.Email) > maxEmail || in.Password == "" || len(in.Password) > 72 {
		writeJSON(w, http.StatusUnauthorized, apiError{"Неверная почта или пароль"})
		return
	}
	u, hash, err := s.Store.GetUserCredentials(r.Context(), in.Email)
	if errors.Is(err, postgres.ErrInvalidCredentials) || (err == nil && (hash == "" || bcrypt.CompareHashAndPassword([]byte(hash), []byte(in.Password)) != nil)) {
		writeJSON(w, http.StatusUnauthorized, apiError{"Неверная почта или пароль"})
		return
	}
	if err != nil {
		s.fail(w, err, "")
		return
	}
	s.resetAuthAttempts(r)
	token, tokenHash, err := newSessionToken()
	if err != nil {
		s.fail(w, err, "")
		return
	}
	expires := time.Now().Add(sessionTTL)
	if err := s.Store.CreateSession(r.Context(), tokenHash, u.ID, expires); err != nil {
		s.fail(w, err, "")
		return
	}
	s.setSessionCookie(w, token, expires)
	writeJSON(w, http.StatusOK, u)
}

func (s *Server) allowAuthAttempt(w http.ResponseWriter, r *http.Request) bool {
	s.loginLimiterOnce.Do(func() { s.loginLimiter = &loginLimiterState{entries: make(map[string]loginWindow)} })
	if !s.loginLimiter.allow(clientIP(r), time.Now()) {
		w.Header().Set("Retry-After", "60")
		writeJSON(w, http.StatusTooManyRequests, apiError{"Слишком много попыток входа; повторите позже"})
		return false
	}
	return true
}

func (s *Server) resetAuthAttempts(r *http.Request) {
	s.loginLimiterOnce.Do(func() { s.loginLimiter = &loginLimiterState{entries: make(map[string]loginWindow)} })
	s.loginLimiter.reset(clientIP(r))
}

type loginWindow struct {
	started time.Time
	count   int
}
type loginLimiterState struct {
	mu      sync.Mutex
	entries map[string]loginWindow
}

func (l *loginLimiterState) allow(ip string, now time.Time) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	entry, ok := l.entries[ip]
	if !ok || now.Sub(entry.started) >= time.Minute {
		if len(l.entries) >= 1024 {
			oldestIP := ""
			var oldest time.Time
			for candidate, value := range l.entries {
				if oldestIP == "" || value.started.Before(oldest) {
					oldestIP, oldest = candidate, value.started
				}
			}
			delete(l.entries, oldestIP)
		}
		l.entries[ip] = loginWindow{started: now, count: 1}
		return true
	}
	entry.count++
	l.entries[ip] = entry
	return entry.count <= 10
}

func (l *loginLimiterState) reset(ip string) { l.mu.Lock(); delete(l.entries, ip); l.mu.Unlock() }

func clientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func (s *Server) me(w http.ResponseWriter, r *http.Request) {
	u, ok := currentUser(r)
	if !ok {
		writeJSON(w, http.StatusUnauthorized, apiError{"Требуется вход"})
		return
	}
	writeJSON(w, http.StatusOK, u)
}

func (s *Server) logout(w http.ResponseWriter, r *http.Request) {
	if c, err := r.Cookie(sessionCookie); err == nil && c.Value != "" {
		if err := s.Store.DeleteSession(r.Context(), digestToken(c.Value)); err != nil {
			s.fail(w, err, "")
			return
		}
	}
	s.clearSessionCookie(w)
	w.WriteHeader(http.StatusNoContent)
}

func hashPassword(password string) (string, error) {
	b, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	return string(b), err
}
