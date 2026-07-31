package finding

import "testing"

func TestParseSeverity(t *testing.T) {
	tests := []struct {
		in      string
		want    Severity
		wantErr bool
	}{
		{"low", SeverityLow, false},
		{"medium", SeverityMedium, false},
		{"high", SeverityHigh, false},
		{"critical", SeverityCritical, false},

		// Negative cases. The parser is exact on purpose: whatever it accepts
		// here it also accepts in .arcet.yml and in suppression comments.
		{"", 0, true},
		{"HIGH", 0, true},
		{"High", 0, true},
		{" high", 0, true},
		{"high ", 0, true},
		{"fatal", 0, true},
		{"none", 0, true},
		{"info", 0, true},
		{"3", 0, true},
	}

	for _, tt := range tests {
		got, err := ParseSeverity(tt.in)
		if (err != nil) != tt.wantErr {
			t.Errorf("ParseSeverity(%q) error = %v, wantErr %v", tt.in, err, tt.wantErr)
			continue
		}
		if got != tt.want {
			t.Errorf("ParseSeverity(%q) = %v, want %v", tt.in, got, tt.want)
		}
	}
}

// TestSeverityRoundTrip keeps String and ParseSeverity inverse to each other.
// They are what the text, JSON and SARIF reporters will all agree through.
func TestSeverityRoundTrip(t *testing.T) {
	for _, name := range SeverityNames {
		sev, err := ParseSeverity(name)
		if err != nil {
			t.Fatalf("ParseSeverity(%q) returned %v", name, err)
		}
		if got := sev.String(); got != name {
			t.Errorf("%q -> %v -> %q, want the original", name, sev, got)
		}
	}
}

// TestSeverityNamesCoverEveryValue stops the help text and the parser drifting
// apart when a severity is added.
func TestSeverityNamesCoverEveryValue(t *testing.T) {
	if len(SeverityNames) != len(severityNames) {
		t.Fatalf("SeverityNames has %d entries, severityNames has %d", len(SeverityNames), len(severityNames))
	}
	for _, name := range SeverityNames {
		if _, err := ParseSeverity(name); err != nil {
			t.Errorf("SeverityNames lists %q but ParseSeverity rejects it", name)
		}
	}
}

// TestSeverityOrdering is what makes the --fail-on threshold a single
// comparison. If the constants were ever reordered, every threshold in the
// tool would invert silently.
func TestSeverityOrdering(t *testing.T) {
	ordered := []Severity{SeverityLow, SeverityMedium, SeverityHigh, SeverityCritical}
	for i := 1; i < len(ordered); i++ {
		if !(ordered[i-1] < ordered[i]) {
			t.Errorf("%v is not less severe than %v", ordered[i-1], ordered[i])
		}
	}
}

func TestAtLeast(t *testing.T) {
	tests := []struct {
		sev       Severity
		threshold Severity
		want      bool
	}{
		{SeverityCritical, SeverityMedium, true},
		{SeverityHigh, SeverityMedium, true},
		{SeverityMedium, SeverityMedium, true},
		{SeverityLow, SeverityMedium, false},
		{SeverityLow, SeverityLow, true},
		{SeverityHigh, SeverityCritical, false},
	}
	for _, tt := range tests {
		if got := tt.sev.AtLeast(tt.threshold); got != tt.want {
			t.Errorf("%v.AtLeast(%v) = %v, want %v", tt.sev, tt.threshold, got, tt.want)
		}
	}
}

// TestZeroValueIsInvalid protects the choice to start the scale at 1. If the
// zero value were a real severity, a struct field nobody set would read as a
// genuine finding severity.
func TestZeroValueIsInvalid(t *testing.T) {
	var unset Severity
	if unset.Valid() {
		t.Error("the zero Severity reports itself as valid")
	}
	if got := unset.String(); got != "Severity(0)" {
		t.Errorf("zero Severity String() = %q, want it to look wrong", got)
	}
}

func TestDefaultThreshold(t *testing.T) {
	// docs/rules.md states medium. The doc and the code are the same contract.
	if DefaultThreshold != SeverityMedium {
		t.Errorf("DefaultThreshold = %v, want medium (docs/rules.md)", DefaultThreshold)
	}
}
