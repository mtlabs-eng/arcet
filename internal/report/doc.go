// Package report renders findings as text, JSON and SARIF 2.1.0.
//
// The SARIF output carries properties.security-severity, which is what makes
// GitHub show Critical/High/Medium/Low in code scanning. See docs/rules.md,
// "Severidades".
//
// Implemented in milestone 2.
package report
