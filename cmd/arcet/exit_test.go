package main

import (
	"errors"
	"fmt"
	"testing"
)

func TestExitCodeValues(t *testing.T) {
	// These numbers are the public contract. Changing one silently breaks
	// every pipeline that branches on it, so they are asserted literally.
	tests := []struct {
		code exitCode
		want int
	}{
		{exitClean, 0},
		{exitFindings, 1},
		{exitToolError, 2},
		{exitConfigError, 3},
	}
	for _, tt := range tests {
		if int(tt.code) != tt.want {
			t.Errorf("exit code = %d, want %d", int(tt.code), tt.want)
		}
	}
}

func TestCodeFor(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want exitCode
	}{
		{"nil", nil, exitClean},
		{"plain error", errors.New("boom"), exitToolError},
		{"config error", errConfig("bad flag"), exitConfigError},
		{"wrapped config error", fmt.Errorf("loading: %w", errConfig("bad flag")), exitConfigError},
		{"config error wrapping a plain error", errConfig("bad flag: %w", errors.New("boom")), exitConfigError},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := codeFor(tt.err); got != tt.want {
				t.Errorf("codeFor(%v) = %d, want %d", tt.err, got, tt.want)
			}
		})
	}
}

// TestConfigErrorUnwraps keeps errors.Is working through the classification
// wrapper, so that a caller can still test for a specific underlying cause.
func TestConfigErrorUnwraps(t *testing.T) {
	sentinel := errors.New("sentinel")
	err := errConfig("context: %w", sentinel)
	if !errors.Is(err, sentinel) {
		t.Errorf("errors.Is(%v, sentinel) = false, want true", err)
	}
	if got, want := err.Error(), "context: sentinel"; got != want {
		t.Errorf("Error() = %q, want %q", got, want)
	}
}
