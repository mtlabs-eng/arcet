// Package secret holds the credential exposure rules: secrets echoed or
// written to files, secrets in global env instead of the step that needs them,
// and secrets passed to unpinned third-party actions.
//
// Implemented after milestone 3.
package secret
