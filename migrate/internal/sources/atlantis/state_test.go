package atlantis

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/mattrobinsonsre/terrapod/migrate/internal/writer"
)

const validState = `{"version":4,"lineage":"abc-123","serial":7,"terraform_version":"1.12.0","outputs":{},"resources":[]}`

func TestReadStateFromDir_ImplicitLocalBackend(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "main.tf", "terraform {}\n")
	writeFile(t, dir, "terraform.tfstate", validState)

	raw, lineage, serial, err := ReadStateFromDir(context.Background(), dir, StateOptions{})
	if err != nil {
		t.Fatalf("ReadStateFromDir: %v", err)
	}
	if string(raw) != validState {
		t.Errorf("raw state mismatch: got %q", string(raw))
	}
	if lineage != "abc-123" {
		t.Errorf("lineage = %q, want %q", lineage, "abc-123")
	}
	if serial != 7 {
		t.Errorf("serial = %d, want 7", serial)
	}
}

func TestReadStateFromDir_ExplicitLocalBackend(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "main.tf", `
terraform {
  backend "local" {
    path = "state/my.tfstate"
  }
}
`)
	if err := os.MkdirAll(filepath.Join(dir, "state"), 0o755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, dir, "state/my.tfstate", validState)

	raw, lineage, serial, err := ReadStateFromDir(context.Background(), dir, StateOptions{})
	if err != nil {
		t.Fatalf("ReadStateFromDir: %v", err)
	}
	if string(raw) != validState {
		t.Errorf("raw state mismatch")
	}
	if lineage != "abc-123" {
		t.Errorf("lineage = %q", lineage)
	}
	if serial != 7 {
		t.Errorf("serial = %d", serial)
	}
}

func TestReadStateFromDir_NoStateFile(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "main.tf", "terraform {}\n")

	_, _, _, err := ReadStateFromDir(context.Background(), dir, StateOptions{})
	if err == nil {
		t.Fatal("expected error for missing state file")
	}
	var noState *writer.ErrNoStateForWorkspace
	if !errors.As(err, &noState) {
		t.Errorf("expected ErrNoStateForWorkspace, got: %v", err)
	}
}

func TestReadStateFromDir_EmptyStateFile(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "main.tf", "terraform {}\n")
	writeFile(t, dir, "terraform.tfstate", "")

	_, _, _, err := ReadStateFromDir(context.Background(), dir, StateOptions{})
	if err == nil {
		t.Fatal("expected error for empty state file")
	}
	var noState *writer.ErrNoStateForWorkspace
	if !errors.As(err, &noState) {
		t.Errorf("expected ErrNoStateForWorkspace, got: %v", err)
	}
}

func TestReadStateFromDir_InvalidJSON(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "main.tf", "terraform {}\n")
	writeFile(t, dir, "terraform.tfstate", `{"lineage": broken}`)

	_, _, _, err := ReadStateFromDir(context.Background(), dir, StateOptions{})
	if err == nil {
		t.Fatal("expected error for invalid JSON")
	}
}

func TestReadStateFromDir_MissingLineage(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "main.tf", "terraform {}\n")
	writeFile(t, dir, "terraform.tfstate", `{"version":4,"serial":1}`)

	_, _, _, err := ReadStateFromDir(context.Background(), dir, StateOptions{})
	if err == nil {
		t.Fatal("expected error for missing lineage")
	}
}
