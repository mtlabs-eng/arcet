package main

import (
	"errors"
	"fmt"
)

// The exit code contract. This is the whole of it — every exit path in the
// program goes through these four constants, because anyone who puts arcet in
// CI branches on them. See CLAUDE.md, "Exit codes".
//
// The distinction that matters most is 1 versus 2. "I analysed your workflows
// and found problems" and "I could not analyse your workflows" are different
// outcomes, and a pipeline that cannot tell them apart will eventually treat a
// broken tool as a clean audit.
type exitCode int

const (
	// exitClean means the analysis completed and nothing reached the threshold.
	exitClean exitCode = 0
	// exitFindings means the analysis completed and findings reached the threshold.
	exitFindings exitCode = 1
	// exitToolError means arcet failed: unreadable file, invalid YAML, recovered panic.
	exitToolError exitCode = 2
	// exitConfigError means the invocation or the configuration was wrong.
	exitConfigError exitCode = 3
)

// configError marks an error as the user's configuration or arguments being
// wrong, rather than arcet failing. It is the only thing that selects
// exitConfigError, so the classification lives in one place instead of being
// re-decided at each call site.
type configError struct{ err error }

func (e *configError) Error() string { return e.err.Error() }
func (e *configError) Unwrap() error { return e.err }

// errConfig builds a configError with the usual formatting verbs.
func errConfig(format string, a ...any) error {
	return &configError{err: fmt.Errorf(format, a...)}
}

// codeFor maps a non-nil error to its exit code.
//
// Anything not explicitly marked as a configuration problem is a tool failure.
// That default is deliberate: misreporting our own bug as the user's mistake
// sends them looking in the wrong place.
func codeFor(err error) exitCode {
	if err == nil {
		return exitClean
	}
	var ce *configError
	if errors.As(err, &ce) {
		return exitConfigError
	}
	return exitToolError
}
