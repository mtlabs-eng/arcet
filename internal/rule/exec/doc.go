// Package exec holds the injection rules: third-party controllable context
// interpolated into run blocks, and unsafe interpolation inside shell.
//
// The set of third-party controllable contexts is shared with
// agent/untrusted-prompt-injection — it is the same set, and it is kept in one
// place.
//
// Implemented after milestone 3.
package exec
