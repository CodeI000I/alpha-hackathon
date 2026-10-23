package httpapi

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestLegacyJSONRequestsAreBoundedBeforeStorage(t *testing.T) {
	s := &Server{}
	for _, tc := range []struct {
		name    string
		handler http.HandlerFunc
		body    string
	}{
		{"user", s.createUser, `{"email":"test@example.com","fullName":"Test","padding":"`},
		{"company", s.createCompany, `{"inn":"1234567890","name":"Test","padding":"`},
		{"roles", s.setUserRoles, `{"roles":[],"padding":"`},
		{"profile", s.patchProfile, `{"padding":"`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(tc.body+strings.Repeat("x", 1<<20)+`"}`))
			r.SetPathValue("id", "1")
			w := httptest.NewRecorder()
			// A nil Store deliberately catches any attempt to persist the oversized input.
			defer func() {
				if value := recover(); value != nil {
					t.Fatalf("oversized input reached storage: %v", value)
				}
			}()
			tc.handler(w, r)
			if w.Code < 400 || w.Code >= 500 {
				t.Fatalf("got HTTP %d, want client input error", w.Code)
			}
		})
	}
}
