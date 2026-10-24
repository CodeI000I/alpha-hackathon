package httpapi

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"sort"
	"strings"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
)

const maxOnboardingBody = 64 << 10

type onboardingRequest struct {
	Company struct {
		INN  string `json:"inn"`
		OGRN string `json:"ogrn"`
		Name string `json:"name"`
	} `json:"company"`
	User struct {
		Email    string   `json:"email"`
		FullName string   `json:"fullName"`
		Password string   `json:"password"`
		Roles    []string `json:"roles"`
	} `json:"user"`
}

func (s *Server) createOnboarding(w http.ResponseWriter, r *http.Request) {
	if s.RequireAuth && !sameOriginRequest(r) {
		writeJSON(w, http.StatusForbidden, apiError{"Запрос должен быть отправлен с этого сайта"})
		return
	}
	if s.RequireAuth && !s.allowAuthAttempt(w, r) {
		return
	}
	key := r.Header.Get("Idempotency-Key")
	if !validIdempotencyKey(key) {
		badRequest(w, "Idempotency-Key must be 1-128 ASCII letters, digits, '.', '_', ':', or '-'")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxOnboardingBody)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	var input onboardingRequest
	if err := decoder.Decode(&input); err != nil {
		var maxErr *http.MaxBytesError
		if errors.As(err, &maxErr) {
			writeJSON(w, http.StatusRequestEntityTooLarge, apiError{"request body too large"})
			return
		}
		badRequest(w, "invalid onboarding request")
		return
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		var maxErr *http.MaxBytesError
		if errors.As(err, &maxErr) {
			writeJSON(w, http.StatusRequestEntityTooLarge, apiError{"request body too large"})
			return
		}
		badRequest(w, "request must contain one JSON object")
		return
	}

	input.Company.INN = strings.TrimSpace(input.Company.INN)
	input.Company.OGRN = strings.TrimSpace(input.Company.OGRN)
	input.Company.Name = strings.TrimSpace(input.Company.Name)
	input.User.Email = strings.ToLower(strings.TrimSpace(input.User.Email))
	input.User.FullName = strings.TrimSpace(input.User.FullName)
	if input.Company.INN == "" || len(input.Company.INN) > 12 || input.Company.Name == "" || len(input.Company.OGRN) > 15 || input.User.Email == "" || input.User.FullName == "" {
		badRequest(w, "company inn/name and user email/fullName are required and identifiers must fit their columns")
		return
	}
	if len(input.User.Password) < 10 || len(input.User.Password) > 72 {
		badRequest(w, "password must be between 10 and 72 bytes")
		return
	}
	if input.User.Roles == nil {
		input.User.Roles = []string{}
	}
	if len(input.User.Roles) == 0 {
		badRequest(w, "at least one role is required")
		return
	}
	for i, role := range input.User.Roles {
		input.User.Roles[i] = strings.TrimSpace(role)
		if input.User.Roles[i] == "" {
			badRequest(w, "roles must contain non-empty role codes")
			return
		}
	}
	sort.Strings(input.User.Roles)
	for i := 1; i < len(input.User.Roles); i++ {
		if input.User.Roles[i] == input.User.Roles[i-1] {
			badRequest(w, "duplicate roles are not allowed")
			return
		}
	}
	requestFingerprint := input
	requestFingerprint.User.Password = ""
	canonical, err := json.Marshal(requestFingerprint)
	if err != nil {
		s.fail(w, err, msgCompanyNotFound)
		return
	}
	digest := sha256.Sum256(canonical)
	token, sessionHash, err := newSessionToken()
	if err != nil {
		s.fail(w, err, msgCompanyNotFound)
		return
	}
	expires := time.Now().Add(sessionTTL)
	company, user, replayed, err := s.Store.CreateOnboarding(r.Context(), key, hex.EncodeToString(digest[:]), input.User.Password, sessionHash, expires, domain.Company{
		INN: input.Company.INN, OGRN: input.Company.OGRN, Name: input.Company.Name,
	}, domain.User{Email: input.User.Email, FullName: input.User.FullName, Roles: input.User.Roles})
	if errors.Is(err, postgres.ErrInvalidCredentials) {
		writeJSON(w, http.StatusUnauthorized, apiError{"Неверная почта или пароль"})
		return
	}
	if errors.Is(err, postgres.ErrIdempotencyConflict) {
		writeJSON(w, http.StatusConflict, apiError{"idempotency key was already used for a different request"})
		return
	}
	if errors.Is(err, postgres.ErrOnboardingResourceConflict) {
		writeJSON(w, http.StatusConflict, apiError{"company or user already exists"})
		return
	}
	if errors.Is(err, postgres.ErrUnknownRole) {
		badRequest(w, "one or more roles are unknown")
		return
	}
	if err != nil {
		s.fail(w, err, msgCompanyNotFound)
		return
	}
	status := http.StatusCreated
	if replayed {
		status = http.StatusOK
	}
	if s.RequireAuth {
		s.resetAuthAttempts(r)
	}
	s.setSessionCookie(w, token, expires)
	writeJSON(w, status, struct {
		Company domain.Company `json:"company"`
		User    domain.User    `json:"user"`
	}{Company: company, User: user})
}

func validIdempotencyKey(key string) bool {
	if len(key) < 1 || len(key) > 128 {
		return false
	}
	for i := 0; i < len(key); i++ {
		c := key[i]
		if (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || strings.ContainsRune("._:-", rune(c)) {
			continue
		}
		return false
	}
	return true
}
