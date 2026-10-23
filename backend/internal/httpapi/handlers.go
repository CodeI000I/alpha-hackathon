package httpapi

import (
	"encoding/json"
	"fmt"
	"net/http"
	"path"
	"strconv"
	"time"

	"github.com/devowt/alpha-hackaton/backend/internal/domain"
)

const maxJSONBody = 1 << 20

func (s *Server) listRoles(w http.ResponseWriter, r *http.Request) {
	roles, err := s.Store.ListRoles(r.Context())
	if err != nil {
		s.fail(w, err)
		return
	}
	writeJSON(w, http.StatusOK, roles)
}

func (s *Server) listProfileElements(w http.ResponseWriter, r *http.Request) {
	els, err := s.Store.ListProfileElements(r.Context())
	if err != nil {
		s.fail(w, err)
		return
	}
	writeJSON(w, http.StatusOK, els)
}

func (s *Server) createUser(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxJSONBody)
	var in domain.User
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil || in.Email == "" || in.FullName == "" {
		badRequest(w, "email and fullName are required")
		return
	}
	u, err := s.Store.CreateUser(r.Context(), in)
	if err != nil {
		s.fail(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, u)
}

func (s *Server) getUser(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(r)
	if !ok {
		badRequest(w, "bad id")
		return
	}
	u, err := s.Store.GetUser(r.Context(), id)
	if err != nil {
		s.fail(w, err)
		return
	}
	writeJSON(w, http.StatusOK, u)
}

func (s *Server) setUserRoles(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxJSONBody)
	id, ok := pathID(r)
	if !ok {
		badRequest(w, "bad id")
		return
	}
	var in struct {
		Roles []string `json:"roles"`
	}
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		badRequest(w, "roles: array of role codes expected")
		return
	}
	if err := s.Store.SetUserRoles(r.Context(), id, in.Roles); err != nil {
		s.fail(w, err)
		return
	}
	u, err := s.Store.GetUser(r.Context(), id)
	if err != nil {
		s.fail(w, err)
		return
	}
	writeJSON(w, http.StatusOK, u)
}

func (s *Server) getFeed(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(r)
	if !ok {
		badRequest(w, "bad id")
		return
	}
	limit := 50
	if v, err := strconv.Atoi(r.URL.Query().Get("limit")); err == nil && v > 0 && v <= 200 {
		limit = v
	}
	items, err := s.Store.Feed(r.Context(), id, r.URL.Query().Get("role"), limit)
	if err != nil {
		s.fail(w, err)
		return
	}
	writeJSON(w, http.StatusOK, items)
}

func (s *Server) createCompany(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxJSONBody)
	var in domain.Company
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil || in.INN == "" || in.Name == "" {
		badRequest(w, "inn and name are required")
		return
	}
	c, err := s.Store.CreateCompany(r.Context(), in)
	if err != nil {
		s.fail(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, c)
}

func (s *Server) getCompany(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(r)
	if !ok {
		badRequest(w, "bad id")
		return
	}
	c, err := s.Store.GetCompany(r.Context(), id)
	if err != nil {
		s.fail(w, err)
		return
	}
	writeJSON(w, http.StatusOK, c)
}

// patchProfile принимает {"Б1": {...}, "Г3": {...}} и сливает с текущим профилем.
func (s *Server) patchProfile(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxJSONBody)
	id, ok := pathID(r)
	if !ok {
		badRequest(w, "bad id")
		return
	}
	var patch map[string]json.RawMessage
	if err := json.NewDecoder(r.Body).Decode(&patch); err != nil {
		badRequest(w, "object with profile element codes expected")
		return
	}
	c, err := s.Store.PatchProfile(r.Context(), id, patch)
	if err != nil {
		s.fail(w, err)
		return
	}
	writeJSON(w, http.StatusOK, c)
}

func (s *Server) listFiles(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(r)
	if !ok {
		badRequest(w, "bad id")
		return
	}
	fs, err := s.Store.ListCompanyFiles(r.Context(), id)
	if err != nil {
		s.fail(w, err)
		return
	}
	writeJSON(w, http.StatusOK, fs)
}

const maxUpload = 50 << 20

// uploadFile принимает multipart/form-data с полем "file".
func (s *Server) uploadFile(w http.ResponseWriter, r *http.Request) {
	if s.Files == nil {
		writeJSON(w, http.StatusServiceUnavailable, apiError{"file storage is not configured"})
		return
	}
	id, ok := pathID(r)
	if !ok {
		badRequest(w, "bad id")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxUpload)
	file, header, err := r.FormFile("file")
	if err != nil {
		badRequest(w, "multipart field 'file' expected")
		return
	}
	defer file.Close()

	ct := header.Header.Get("Content-Type")
	if ct == "" {
		ct = "application/octet-stream"
	}
	key := fmt.Sprintf("companies/%d/%d-%s", id, time.Now().UnixNano(), path.Base(header.Filename))
	if err := s.Files.Put(r.Context(), key, file, header.Size, ct); err != nil {
		s.fail(w, err)
		return
	}
	f, err := s.Store.CreateCompanyFile(r.Context(), domain.CompanyFile{
		CompanyID: id, ObjectKey: key, Filename: header.Filename, ContentType: ct, SizeBytes: header.Size,
	})
	if err != nil {
		s.fail(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, f)
}
