package main

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestRunExitCodes pins the exit code contract to the actual argument
// handling. These codes are what CI pipelines branch on, so they are asserted
// end to end through run rather than unit-tested per helper.
func TestRunExitCodes(t *testing.T) {
	// An existing file, so that "no findings yet" is the only reason to fail
	// rather than "path does not exist".
	workflow := filepath.Join(t.TempDir(), "ci.yml")
	writeFile(t, workflow, "name: ci\n")

	existingConfig := filepath.Join(t.TempDir(), ".arcet.yml")
	writeFile(t, existingConfig, "")

	tests := []struct {
		name string
		args []string
		want exitCode
	}{
		// Handled invocations: the user asked for output and got it.
		{"version", []string{"--version"}, exitClean},
		{"help long", []string{"--help"}, exitClean},
		{"help short", []string{"-h"}, exitClean},

		// Configuration and argument errors, all exit 3.
		{"no paths", nil, exitConfigError},
		{"unknown flag", []string{"--nope", workflow}, exitConfigError},
		{"unknown format", []string{"--format", "xml", workflow}, exitConfigError},
		{"empty format", []string{"--format", "", workflow}, exitConfigError},
		{"unknown severity", []string{"--fail-on", "none", workflow}, exitConfigError},
		{"severity wrong case", []string{"--fail-on", "HIGH", workflow}, exitConfigError},
		{"missing config file", []string{"--config", "/no/such/.arcet.yml", workflow}, exitConfigError},

		// Valid invocations. Milestone 0 has no analysis, so these are tool
		// errors — never exit 0, which would read as a clean audit.
		{"valid text", []string{workflow}, exitToolError},
		{"valid sarif", []string{"--format", "sarif", workflow}, exitToolError},
		{"valid fail-on low", []string{"--fail-on", "low", workflow}, exitToolError},
		{"valid config", []string{"--config", existingConfig, workflow}, exitToolError},
		{"several paths", []string{workflow, workflow}, exitToolError},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var stdout, stderr bytes.Buffer
			if got := run(tt.args, &stdout, &stderr); got != tt.want {
				t.Errorf("run(%q) = %d, want %d\nstdout: %s\nstderr: %s",
					tt.args, got, tt.want, stdout.String(), stderr.String())
			}
		})
	}
}

// TestRunNeverExitsCleanWithoutAnalysis guards the property that matters most
// while the pipeline is a stub: no argument combination may produce exit 0 on
// a path, because a caller reading only the exit code would take that as a
// passing audit.
func TestRunNeverExitsCleanWithoutAnalysis(t *testing.T) {
	workflow := filepath.Join(t.TempDir(), "ci.yml")
	writeFile(t, workflow, "name: ci\n")

	for _, format := range outputFormats {
		for _, severity := range []string{"low", "medium", "high", "critical"} {
			args := []string{"--format", format, "--fail-on", severity, workflow}
			var stdout, stderr bytes.Buffer
			if got := run(args, &stdout, &stderr); got == exitClean {
				t.Errorf("run(%q) = exitClean, want a non-zero code while analysis is a stub", args)
			}
		}
	}
}

func TestVersionGoesToStdout(t *testing.T) {
	var stdout, stderr bytes.Buffer
	if got := run([]string{"--version"}, &stdout, &stderr); got != exitClean {
		t.Fatalf("run(--version) = %d, want %d", got, exitClean)
	}
	if !strings.HasPrefix(stdout.String(), "arcet ") {
		t.Errorf("stdout = %q, want it to start with %q", stdout.String(), "arcet ")
	}
	if stderr.Len() != 0 {
		t.Errorf("stderr = %q, want it empty", stderr.String())
	}
}

// TestHelpStreams checks that --help is treated as a successful request and
// goes to stdout, while a usage error goes to stderr. Anyone piping the help
// into a pager depends on the first; anyone reading CI logs depends on the
// second.
func TestHelpStreams(t *testing.T) {
	t.Run("help to stdout", func(t *testing.T) {
		var stdout, stderr bytes.Buffer
		run([]string{"--help"}, &stdout, &stderr)
		if !strings.Contains(stdout.String(), "Usage:") {
			t.Errorf("stdout = %q, want it to contain the usage text", stdout.String())
		}
		if stderr.Len() != 0 {
			t.Errorf("stderr = %q, want it empty", stderr.String())
		}
	})

	t.Run("usage error to stderr", func(t *testing.T) {
		var stdout, stderr bytes.Buffer
		run(nil, &stdout, &stderr)
		if stdout.Len() != 0 {
			t.Errorf("stdout = %q, want it empty", stdout.String())
		}
		if !strings.Contains(stderr.String(), "Usage:") {
			t.Errorf("stderr = %q, want it to contain the usage text", stderr.String())
		}
	})
}

// TestHelpDoesNotMentionAttribution enforces CLAUDE.md, "Atribuição": nothing
// on the user's path advertises anything.
func TestHelpDoesNotMentionAttribution(t *testing.T) {
	var stdout, stderr bytes.Buffer
	run([]string{"--help"}, &stdout, &stderr)
	for _, forbidden := range []string{"Opsyron", "MTLabs"} {
		if strings.Contains(stdout.String(), forbidden) {
			t.Errorf("help text mentions %q; see CLAUDE.md, \"Atribuição\"", forbidden)
		}
	}
}

// TestRunRecoversPanic proves that a panic in the pipeline leaves through the
// exit code contract as a tool error instead of crashing the process with a
// stack trace.
func TestRunRecoversPanic(t *testing.T) {
	workflow := filepath.Join(t.TempDir(), "ci.yml")
	writeFile(t, workflow, "name: ci\n")

	original := analyseFn
	t.Cleanup(func() { analyseFn = original })
	analyseFn = func(*options, io.Writer) (exitCode, error) {
		panic("boom")
	}

	var stdout, stderr bytes.Buffer
	if got := run([]string{workflow}, &stdout, &stderr); got != exitToolError {
		t.Errorf("run after panic = %d, want %d", got, exitToolError)
	}
	if !strings.Contains(stderr.String(), "boom") {
		t.Errorf("stderr = %q, want it to report the panic value", stderr.String())
	}
}

// TestAnalyseIsStubbed fails once the pipeline lands, as a reminder that the
// milestone 0 stub and the tests that assume it both have to go.
func TestAnalyseIsStubbed(t *testing.T) {
	code, err := analyse(&options{}, &bytes.Buffer{})
	if !errors.Is(err, errNotImplemented) {
		t.Fatalf("analyse returned %v; if the pipeline landed, delete this test and the stub assumptions above", err)
	}
	if code == exitClean {
		t.Errorf("analyse returned exitClean alongside an error")
	}
}

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatalf("write %s: %v", path, err)
	}
}
