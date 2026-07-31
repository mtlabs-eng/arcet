// Package finding holds the Finding type, its severity scale and the
// positional evidence attached to it.
//
// Milestone 2 adds Finding itself. Severity lands here first because the
// --fail-on flag needs it, and a threshold type defined twice is a threshold
// that will eventually disagree with itself.
package finding

import (
	"fmt"
	"strings"
)

// Severity is the internal severity scale. It is ordered: a higher value is
// more severe, so a threshold test is a single comparison.
//
// The zero value is deliberately invalid. An unset severity is a bug, and it
// should look like one rather than silently reading as "low".
type Severity int

const (
	SeverityLow Severity = iota + 1
	SeverityMedium
	SeverityHigh
	SeverityCritical
)

// DefaultThreshold is the severity at or above which findings make the tool
// exit 1. See docs/rules.md, "Severidades".
const DefaultThreshold = SeverityMedium

// severityNames is the single source of truth for the string form, in
// ascending order of severity. String and ParseSeverity both read it, so they
// cannot drift apart.
var severityNames = map[Severity]string{
	SeverityLow:      "low",
	SeverityMedium:   "medium",
	SeverityHigh:     "high",
	SeverityCritical: "critical",
}

// SeverityNames lists every valid severity from least to most severe. Used in
// help text and error messages.
var SeverityNames = []string{"low", "medium", "high", "critical"}

func (s Severity) String() string {
	if name, ok := severityNames[s]; ok {
		return name
	}
	return fmt.Sprintf("Severity(%d)", int(s))
}

// Valid reports whether s is one of the defined severities.
func (s Severity) Valid() bool {
	_, ok := severityNames[s]
	return ok
}

// ParseSeverity converts the string form into a Severity. The input is matched
// exactly: accepting "HIGH" or "hi" here would mean accepting them in
// .arcet.yml and in suppression comments too, and that is contract we have not
// agreed to.
func ParseSeverity(s string) (Severity, error) {
	for sev, name := range severityNames {
		if name == s {
			return sev, nil
		}
	}
	return 0, fmt.Errorf("unknown severity %q (want one of: %s)", s, strings.Join(SeverityNames, ", "))
}

// AtLeast reports whether s meets or exceeds the threshold.
func (s Severity) AtLeast(threshold Severity) bool {
	return s >= threshold
}
