// Package agent holds the rules for AI agents running in CI: agents triggered
// by untrusted events, with shell access, write tokens, shared cache or
// third-party controllable input reaching their prompt.
//
// This is the differentiating category. The detection heuristic for "this
// workflow runs an agent" lives in one place here, not spread across the
// rules, because it will change often.
//
// Implemented in milestone 4.
package agent
