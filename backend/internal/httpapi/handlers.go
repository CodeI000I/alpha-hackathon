package httpapi

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"path"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

const maxJSONBody = 1 << 20

// Те же правила, что у формы регистрации во фронтенде (frontend/src/pages/OnboardingPage.tsx,
// frontend/src/auth/onboardingDraft.ts), чтобы сервер не принимал то, что форма бы отклонила.
var (
	innRe   = regexp.MustCompile(`^\d{10}(\d{2})?$`)
	ogrnRe  = regexp.MustCompile(`^\d{13}(\d{2})?$`)
	emailRe = regexp.MustCompile(`^\S+@\S+\.\S+$`)
)

const (
	maxFullName    = 120
	maxEmail       = 320
	maxCompanyName = 160
)

func (s *Server) listRoles(w http.ResponseWriter, r *http.Request) {
	roles, err := s.Store.ListRoles(r.Context())
	if err != nil {
		s.fail(w, err, "")
		return
	}
	writeJSON(w, http.StatusOK, roles)
}

func (s *Server) listProfileElements(w http.ResponseWriter, r *http.Request) {
	els, err := s.Store.ListProfileElements(r.Context())
	if err != nil {
		s.fail(w, err, "")
		return
	}
	writeJSON(w, http.StatusOK, els)
}

func (s *Server) createUser(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxJSONBody)
	var in struct {
		domain.User
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		badRequest(w, "Ожидается JSON с полями fullName, email, companyId и roles")
		return
	}
	in.User.FullName = strings.TrimSpace(in.FullName)
	in.User.Email = strings.ToLower(strings.TrimSpace(in.Email))
	switch {
	case in.FullName == "" || utf8.RuneCountInString(in.FullName) > maxFullName:
		badRequest(w, fmt.Sprintf("Укажите имя не длиннее %d символов", maxFullName))
		return
	case !emailRe.MatchString(in.Email) || len(in.Email) > maxEmail:
		badRequest(w, "Укажите корректную электронную почту")
		return
	}
	if s.RequireAuth {
		if in.CompanyID == nil || !s.authorizeCompanyID(w, r, *in.CompanyID) {
			return
		}
		if len(in.Password) < 10 || len(in.Password) > 72 {
			badRequest(w, "password must be between 10 and 72 bytes")
			return
		}
	} else if in.Password != "" && (len(in.Password) < 10 || len(in.Password) > 72) {
		badRequest(w, "password must be between 10 and 72 bytes")
		return
	}
	passwordHash := ""
	var err error
	if in.Password != "" {
		passwordHash, err = hashPassword(in.Password)
		if err != nil {
			s.fail(w, err, msgCompanyNotFound)
			return
		}
	}
	u, err := s.Store.CreateUserWithPassword(r.Context(), in.User, passwordHash)
	if err != nil {
		s.fail(w, err, msgCompanyNotFound) // 404 здесь возможен только из-за companyId
		return
	}
	s.refreshFeed(r)
	writeJSON(w, http.StatusCreated, u)
}

func (s *Server) getUser(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(r)
	if !ok {
		badRequest(w, msgBadID)
		return
	}
	if !s.authorizeUserID(w, r, id) {
		return
	}
	u, err := s.Store.GetUser(r.Context(), id)
	if err != nil {
		s.fail(w, err, msgUserNotFound)
		return
	}
	writeJSON(w, http.StatusOK, u)
}

func (s *Server) setUserRoles(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxJSONBody)
	id, ok := pathID(r)
	if !ok {
		badRequest(w, msgBadID)
		return
	}
	if !s.authorizeUserID(w, r, id) {
		return
	}
	if s.RequireAuth {
		writeJSON(w, http.StatusForbidden, apiError{"Изменение ролей доступно администратору компании"})
		return
	}
	var in struct {
		Roles []string `json:"roles"`
	}
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		badRequest(w, `Ожидается JSON вида {"roles": ["cfo"]}`)
		return
	}
	if err := s.Store.SetUserRoles(r.Context(), id, in.Roles); err != nil {
		s.fail(w, err, msgUserNotFound)
		return
	}
	s.refreshFeed(r)
	u, err := s.Store.GetUser(r.Context(), id)
	if err != nil {
		s.fail(w, err, msgUserNotFound)
		return
	}
	writeJSON(w, http.StatusOK, u)
}

const (
	defaultFeedLimit = 50
	maxFeedLimit     = 200
)

func (s *Server) getFeed(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(r)
	if !ok {
		badRequest(w, msgBadID)
		return
	}
	if !s.authorizeUserID(w, r, id) {
		return
	}
	limit := defaultFeedLimit
	if v, err := strconv.Atoi(r.URL.Query().Get("limit")); err == nil && v > 0 {
		limit = min(v, maxFeedLimit)
	}
	items, err := s.Store.Feed(r.Context(), id, r.URL.Query().Get("role"), limit)
	if err != nil {
		s.fail(w, err, msgUserNotFound)
		return
	}
	writeJSON(w, http.StatusOK, items)
}

func (s *Server) createCompany(w http.ResponseWriter, r *http.Request) {
	if s.RequireAuth {
		writeJSON(w, http.StatusForbidden, apiError{"Создание компании доступно через регистрацию или приглашение"})
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxJSONBody)
	var in domain.Company
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		badRequest(w, "Ожидается JSON с полями inn и name")
		return
	}
	in.Name = strings.TrimSpace(in.Name)
	in.INN = strings.TrimSpace(in.INN)
	in.OGRN = strings.TrimSpace(in.OGRN)
	switch {
	case in.Name == "" || utf8.RuneCountInString(in.Name) > maxCompanyName:
		badRequest(w, fmt.Sprintf("Укажите название компании не длиннее %d символов", maxCompanyName))
		return
	case !innRe.MatchString(in.INN):
		badRequest(w, "ИНН должен содержать 10 или 12 цифр")
		return
	case in.OGRN != "" && !ogrnRe.MatchString(in.OGRN):
		badRequest(w, "ОГРН должен содержать 13 или 15 цифр")
		return
	}
	// ИНН уже зарегистрирован — 200 и существующая компания: новый директор присоединяется к ней.
	c, created, err := s.Store.CreateCompany(r.Context(), in)
	if err != nil {
		s.fail(w, err, "")
		return
	}
	status := http.StatusOK
	if created {
		status = http.StatusCreated
	}
	writeJSON(w, status, c)
}

func (s *Server) getCompany(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(r)
	if !ok {
		badRequest(w, msgBadID)
		return
	}
	if !s.authorizeCompanyID(w, r, id) {
		return
	}
	c, err := s.Store.GetCompany(r.Context(), id)
	if err != nil {
		s.fail(w, err, msgCompanyNotFound)
		return
	}
	writeJSON(w, http.StatusOK, c)
}

// patchProfile принимает {"Б1": {...}, "Г3": {...}} и сливает с текущим профилем.
func (s *Server) patchProfile(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxJSONBody)
	id, ok := pathID(r)
	if !ok {
		badRequest(w, msgBadID)
		return
	}
	if !s.authorizeCompanyID(w, r, id) {
		return
	}
	var patch map[string]json.RawMessage
	if err := json.NewDecoder(r.Body).Decode(&patch); err != nil {
		badRequest(w, "Ожидается объект с кодами элементов профиля")
		return
	}
	c, err := s.Store.PatchProfile(r.Context(), id, patch)
	if err != nil {
		s.fail(w, err, msgCompanyNotFound)
		return
	}
	writeJSON(w, http.StatusOK, c)
}

func (s *Server) listFiles(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(r)
	if !ok {
		badRequest(w, msgBadID)
		return
	}
	if !s.authorizeCompanyID(w, r, id) {
		return
	}
	fs, err := s.Store.ListCompanyFiles(r.Context(), id)
	if err != nil {
		s.fail(w, err, msgCompanyNotFound)
		return
	}
	writeJSON(w, http.StatusOK, fs)
}

const maxUpload = 12 << 20

// uploadFile принимает multipart/form-data с полем "file".
func (s *Server) uploadFile(w http.ResponseWriter, r *http.Request) {
	if s.Files == nil {
		writeJSON(w, http.StatusServiceUnavailable, apiError{"Хранилище файлов не настроено"})
		return
	}
	id, ok := pathID(r)
	if !ok {
		badRequest(w, msgBadID)
		return
	}
	if !s.authorizeCompanyID(w, r, id) {
		return
	}
	// Проверяем компанию до загрузки, чтобы не оставлять в хранилище файлы без записи в БД.
	exists, err := s.Store.CompanyExists(r.Context(), id)
	if err != nil {
		s.fail(w, err, msgCompanyNotFound)
		return
	}
	if !exists {
		writeJSON(w, http.StatusNotFound, apiError{msgCompanyNotFound})
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxUpload)
	file, header, err := r.FormFile("file")
	if err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			writeJSON(w, http.StatusRequestEntityTooLarge, apiError{fmt.Sprintf("Файл больше %d МБ", maxUpload>>20)})
			return
		}
		badRequest(w, "Ожидается multipart/form-data с полем file")
		return
	}
	if r.MultipartForm != nil {
		defer r.MultipartForm.RemoveAll()
	}
	defer file.Close()

	ct := header.Header.Get("Content-Type")
	if ct == "" {
		ct = "application/octet-stream"
	}
	key := fmt.Sprintf("companies/%d/%d-%s", id, time.Now().UnixNano(), path.Base(header.Filename))
	if err := s.Files.Put(r.Context(), key, file, header.Size, ct); err != nil {
		s.fail(w, err, msgCompanyNotFound)
		return
	}
	f, err := s.Store.CreateCompanyFile(r.Context(), domain.CompanyFile{
		CompanyID: id, ObjectKey: key, Filename: header.Filename, ContentType: ct, SizeBytes: header.Size,
	})
	if err != nil {
		s.fail(w, err, msgCompanyNotFound)
		return
	}
	writeJSON(w, http.StatusCreated, f)
}
