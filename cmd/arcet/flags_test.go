package main

import (
	"bytes"
	"path/filepath"
	"reflect"
	"testing"

	"arcet.dev/arcet/internal/finding"
)

func TestParseFlagsDefaults(t *testing.T) {
	opts, done, err := parseFlags([]string{"a.yml"}, &bytes.Buffer{}, &bytes.Buffer{})
	if err != nil {
		t.Fatalf("parseFlags returned %v, want nil", err)
	}
	if done {
		t.Fatal("parseFlags reported done for a normal invocation")
	}
	if opts.format != "text" {
		t.Errorf("format = %q, want %q", opts.format, "text")
	}
	if opts.failOn != finding.DefaultThreshold {
		t.Errorf("failOn = %v, want %v", opts.failOn, finding.DefaultThreshold)
	}
	if opts.output != "" {
		t.Errorf("output = %q, want it empty (stdout)", opts.output)
	}
	if opts.config != "" {
		t.Errorf("config = %q, want it empty (default lookup)", opts.config)
	}
	if !reflect.DeepEqual(opts.paths, []string{"a.yml"}) {
		t.Errorf("paths = %v, want [a.yml]", opts.paths)
	}
}

func TestParseFlagsValues(t *testing.T) {
	dir := t.TempDir()
	cfg := filepath.Join(dir, ".arcet.yml")
	writeFile(t, cfg, "")
	out := filepath.Join(dir, "report.sarif")

	args := []string{
		"--format", "sarif",
		"--output", out,
		"--fail-on", "critical",
		"--config", cfg,
		".github/workflows/", "extra.yml",
	}
	opts, done, err := parseFlags(args, &bytes.Buffer{}, &bytes.Buffer{})
	if err != nil || done {
		t.Fatalf("parseFlags returned (done=%v, err=%v), want (false, nil)", done, err)
	}
	if opts.format != "sarif" {
		t.Errorf("format = %q, want %q", opts.format, "sarif")
	}
	if opts.output != out {
		t.Errorf("output = %q, want %q", opts.output, out)
	}
	if opts.failOn != finding.SeverityCritical {
		t.Errorf("failOn = %v, want %v", opts.failOn, finding.SeverityCritical)
	}
	if opts.config != cfg {
		t.Errorf("config = %q, want %q", opts.config, cfg)
	}
	want := []string{".github/workflows/", "extra.yml"}
	if !reflect.DeepEqual(opts.paths, want) {
		t.Errorf("paths = %v, want %v", opts.paths, want)
	}
}

// TestParseFlagsEverySeverityAccepted keeps the flag in step with the severity
// scale: a severity that exists in finding but is rejected by --fail-on would
// be a silent hole in the threshold.
func TestParseFlagsEverySeverityAccepted(t *testing.T) {
	for _, name := range finding.SeverityNames {
		opts, _, err := parseFlags([]string{"--fail-on", name, "a.yml"}, &bytes.Buffer{}, &bytes.Buffer{})
		if err != nil {
			t.Errorf("--fail-on %s returned %v, want nil", name, err)
			continue
		}
		if got := opts.failOn.String(); got != name {
			t.Errorf("--fail-on %s parsed to %q", name, got)
		}
	}
}

// TestParseFlagsErrorsAreConfigErrors checks the classification, not just the
// failure: these must reach exit 3, and anything unclassified would reach
// exit 2 and read as arcet being broken.
func TestParseFlagsErrorsAreConfigErrors(t *testing.T) {
	tests := []struct {
		name string
		args []string
	}{
		{"no paths", nil},
		{"unknown flag", []string{"--nope", "a.yml"}},
		{"unknown format", []string{"--format", "yaml", "a.yml"}},
		{"unknown severity", []string{"--fail-on", "fatal", "a.yml"}},
		{"missing config", []string{"--config", "/no/such/file.yml", "a.yml"}},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, _, err := parseFlags(tt.args, &bytes.Buffer{}, &bytes.Buffer{})
			if err == nil {
				t.Fatalf("parseFlags(%q) returned nil, want an error", tt.args)
			}
			if got := codeFor(err); got != exitConfigError {
				t.Errorf("codeFor(%v) = %d, want %d", err, got, exitConfigError)
			}
		})
	}
}

func TestParseFlagsHelpAndVersionAreDone(t *testing.T) {
	for _, args := range [][]string{{"--help"}, {"-h"}, {"--version"}} {
		opts, done, err := parseFlags(args, &bytes.Buffer{}, &bytes.Buffer{})
		if err != nil {
			t.Errorf("parseFlags(%q) returned %v, want nil", args, err)
		}
		if !done {
			t.Errorf("parseFlags(%q) reported done=false, want true", args)
		}
		if opts != nil {
			t.Errorf("parseFlags(%q) returned options %+v, want nil", args, opts)
		}
	}
}

// TestUsageDocumentsEveryFlag stops the help text drifting away from the flag
// set. Undocumented flags are how a CLI's real interface and its stated one
// come apart.
func TestUsageDocumentsEveryFlag(t *testing.T) {
	var buf bytes.Buffer
	writeUsage(&buf)
	usage := buf.String()

	for _, flagName := range []string{"--format", "--output", "--fail-on", "--config", "--version", "--help"} {
		if !bytes.Contains([]byte(usage), []byte(flagName)) {
			t.Errorf("usage text does not document %s", flagName)
		}
	}
	for _, format := range outputFormats {
		if !bytes.Contains([]byte(usage), []byte(format)) {
			t.Errorf("usage text does not mention the %s format", format)
		}
	}
	for _, code := range []string{"0", "1", "2", "3"} {
		if !bytes.Contains([]byte(usage), []byte("  "+code+"  ")) {
			t.Errorf("usage text does not document exit code %s", code)
		}
	}
}
