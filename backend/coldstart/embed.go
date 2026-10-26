// Package coldstart carries the frozen news snapshot through the normal image build.
package coldstart

import "embed"

// FS uses the existing migration lock/ledger; the snapshot is installed once.
//
//go:embed *.sql
var FS embed.FS
