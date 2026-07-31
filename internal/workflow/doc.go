// Package workflow parses GitHub Actions workflow files into a tree in which
// every node still knows its line and column.
//
// It is built on yaml.Node rather than unmarshalling into structs, because
// unmarshalling discards position and position is half the product. See
// CLAUDE.md, "Restrição técnica central".
//
// Implemented in milestone 1.
package workflow
