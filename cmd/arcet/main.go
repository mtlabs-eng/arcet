// Command arcet statically audits CI/CD workflows.
//
// It reads workflow files, applies rules and reports findings with positional
// evidence. It does not execute workflows, does not make network requests and
// does not modify the files it analyses. See CLAUDE.md for the full set of
// product invariants.
package main

import (
	"errors"
	"fmt"
	"io"
	"os"
	"runtime/debug"
)

// version is overridden at build time with
// -ldflags "-X main.version=v0.1.0". The default is what a `go build` from a
// working tree produces.
var version = "dev"

// errNotImplemented is returned by the analysis pipeline until milestone 1
// lands.
//
// It maps to exit 2, never exit 0. A half-built binary that exits 0 on a repo
// it never actually read would sit in someone's CI reporting a clean audit,
// which is a worse failure than not running at all.
var errNotImplemented = errors.New("analysis is not implemented yet (milestone 1); this build can only report its version")

func main() {
	os.Exit(int(run(os.Args[1:], os.Stdout, os.Stderr)))
}

// run is main without the process exit, so that tests can drive the real
// argument handling and assert on the real exit codes.
func run(args []string, stdout, stderr io.Writer) (code exitCode) {
	// A panic anywhere below is a tool failure, and the contract says tool
	// failure is exit 2. Without this, the Go runtime would exit 2 as well but
	// only by coincidence, and after printing a stack trace that reads as a
	// crash rather than as a result.
	defer func() {
		if r := recover(); r != nil {
			fmt.Fprintf(stderr, "arcet: internal error: %v\n", r)
			code = exitToolError
		}
	}()

	opts, done, err := parseFlags(args, stdout, stderr)
	if err != nil {
		fmt.Fprintf(stderr, "arcet: %v\n", err)
		return codeFor(err)
	}
	if done {
		return exitClean
	}

	code, err = analyseFn(opts, stdout)
	if err != nil {
		fmt.Fprintf(stderr, "arcet: %v\n", err)
		return codeFor(err)
	}
	return code
}

// analyseFn is the seam run uses to reach the pipeline. Tests replace it to
// prove that a panic below this line still leaves through the exit code
// contract instead of crashing the process.
var analyseFn = analyse

// analyse runs the pipeline: parse the workflows, apply the rules, write the
// report. On success it returns exitClean or exitFindings depending on the
// --fail-on threshold.
//
// Milestone 1 replaces the body with the real implementation.
func analyse(opts *options, stdout io.Writer) (exitCode, error) {
	_ = opts
	_ = stdout
	return exitToolError, errNotImplemented
}

// versionString reports the build version, enriched with VCS metadata when the
// binary was built straight from a working tree rather than by a release
// build.
func versionString() string {
	if version != "dev" {
		return version
	}
	info, ok := debug.ReadBuildInfo()
	if !ok {
		return version
	}
	var revision, modified string
	for _, setting := range info.Settings {
		switch setting.Key {
		case "vcs.revision":
			revision = setting.Value
		case "vcs.modified":
			modified = setting.Value
		}
	}
	if revision == "" {
		return version
	}
	if len(revision) > 12 {
		revision = revision[:12]
	}
	if modified == "true" {
		return fmt.Sprintf("%s (%s, dirty)", version, revision)
	}
	return fmt.Sprintf("%s (%s)", version, revision)
}
