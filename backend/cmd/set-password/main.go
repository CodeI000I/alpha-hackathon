// set-password bootstraps or resets a known user's password without putting it in shell history.
package main

import (
	"context"
	"fmt"
	"io"
	"os"
	"strings"

	"golang.org/x/crypto/bcrypt"

	"github.com/devowt/alpha-hackaton/backend/internal/storage/postgres"
)

func run() error {
	if len(os.Args) != 2 || strings.TrimSpace(os.Args[1]) == "" {
		return fmt.Errorf("usage: set-password <existing-user-email> (password is read from stdin)")
	}
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		return fmt.Errorf("DATABASE_URL is required")
	}
	fmt.Fprintln(os.Stderr, "Enter new password on stdin (10–72 bytes):")
	password, err := io.ReadAll(io.LimitReader(os.Stdin, 74))
	if err != nil {
		return err
	}
	password = []byte(strings.TrimSuffix(strings.TrimSuffix(string(password), "\n"), "\r"))
	if len(password) < 10 || len(password) > 72 {
		return fmt.Errorf("password must be between 10 and 72 bytes")
	}
	hash, err := bcrypt.GenerateFromPassword(password, bcrypt.DefaultCost)
	if err != nil {
		return err
	}
	ctx := context.Background()
	store, err := postgres.New(ctx, dsn)
	if err != nil {
		return err
	}
	defer store.Close()
	if err := store.SetPasswordByEmail(ctx, strings.TrimSpace(os.Args[1]), string(hash)); err != nil {
		if err == postgres.ErrNotFound {
			return fmt.Errorf("no existing account matched")
		}
		return err
	}
	fmt.Fprintln(os.Stdout, "Password updated; existing sessions were revoked.")
	return nil
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
