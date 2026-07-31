// Package trigger holds the rules for dangerous events: pull_request_target
// checking out fork code, workflow_run consuming untrusted artefacts,
// unfiltered issue_comment and secrets reachable from fork pull requests.
//
// Implemented after milestone 3.
package trigger
