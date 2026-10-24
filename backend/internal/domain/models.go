// Package domain содержит модели, которыми backend обменивается с фронтендом (JSON).
package domain

import (
	"encoding/json"
	"time"
)

type Role struct {
	ID       int16    `json:"id"`
	Code     string   `json:"code"`
	Name     string   `json:"name"`
	Question string   `json:"question"`
	Focus    string   `json:"focus"`
	Elements []string `json:"elements"` // коды элементов профиля, важных для роли
}

type ProfileElement struct {
	Code        string `json:"code"`
	Block       string `json:"block"`
	Name        string `json:"name"`
	Description string `json:"description"`
	Purpose     string `json:"purpose"`
}

type User struct {
	ID        int64     `json:"id"`
	CompanyID *int64    `json:"companyId"`
	Email     string    `json:"email"`
	FullName  string    `json:"fullName"`
	Roles     []string  `json:"roles"` // коды ролей
	CreatedAt time.Time `json:"createdAt"`
}

type Company struct {
	ID        int64                      `json:"id"`
	INN       string                     `json:"inn"`
	OGRN      string                     `json:"ogrn"`
	Name      string                     `json:"name"`
	Profile   map[string]json.RawMessage `json:"profile"` // код элемента → данные
	CreatedAt time.Time                  `json:"createdAt"`
	UpdatedAt time.Time                  `json:"updatedAt"`
}

type NewsItem struct {
	ID          int64     `json:"id"`
	SourceID    string    `json:"sourceId"`
	ExternalID  string    `json:"-"`
	URL         string    `json:"url"`
	Title       string    `json:"title"`
	Summary     string    `json:"summary"`
	Body        string    `json:"body,omitempty"`
	PublishedAt time.Time `json:"publishedAt"`
}

type FeedItem struct {
	ID        int64      `json:"id"`
	Role      string     `json:"role"`
	Kind      string     `json:"kind"` // event | risk | opportunity
	Score     float32    `json:"score"`
	Insight   string     `json:"insight"`
	Elements  []string   `json:"elements"`
	News      NewsItem   `json:"news"`
	CreatedAt time.Time  `json:"createdAt"`
	ReadAt    *time.Time `json:"readAt"`
}

type CompanyFile struct {
	ID          int64     `json:"id"`
	CompanyID   int64     `json:"companyId"`
	Filename    string    `json:"filename"`
	ContentType string    `json:"contentType"`
	SizeBytes   int64     `json:"sizeBytes"`
	ObjectKey   string    `json:"-"`
	CreatedAt   time.Time `json:"createdAt"`
}
