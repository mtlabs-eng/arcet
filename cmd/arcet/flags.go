package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"arcet.dev/arcet/internal/finding"
)

// outputFormats are the report formats accepted by --format.
//
// Milestone 2 builds the reporters themselves in internal/report; when it
// does, this list moves there so that adding a format cannot leave the flag
// validation behind.
var outputFormats = []string{"text", "json", "sarif"}

// options is the validated invocation. Every field here has already been
// checked, so nothing downstream needs to re-validate a flag.
type options struct {
	format string
	// output is the report destination. Empty means stdout.
	output string
	// failOn is the severity at or above which findings produce exit 1.
	failOn finding.Severity
	// config is an explicit .arcet.yml path. Empty means the default lookup.
	config string
	// paths are the workflow files or directories to audit.
	paths []string
}

// parseFlags validates argv and builds the options.
//
// The done return reports that the invocation was fully handled and the
// program should exit cleanly — --version and --help are requests for output,
// not audits, and neither should look like a clean audit to a caller that only
// reads the exit code. Both are exit 0 because the user got what they asked
// for.
func parseFlags(args []string, stdout, stderr io.Writer) (opts *options, done bool, err error) {
	fs := flag.NewFlagSet("arcet", flag.ContinueOnError)
	// We print every diagnostic ourselves, so the flag package's own output is
	// suppressed rather than interleaved with it.
	fs.SetOutput(io.Discard)

	var (
		format      = fs.String("format", "text", "report format: "+strings.Join(outputFormats, ", "))
		output      = fs.String("output", "", "write the report to this file instead of stdout")
		failOn      = fs.String("fail-on", finding.DefaultThreshold.String(), "minimum severity that exits 1: "+strings.Join(finding.SeverityNames, ", "))
		configPath  = fs.String("config", "", "path to .arcet.yml")
		showVersion = fs.Bool("version", false, "print the version and exit")
	)

	if err := fs.Parse(args); err != nil {
		// -h and --help arrive here as flag.ErrHelp. That is a successful
		// invocation, so the help text goes to stdout, not stderr.
		if errors.Is(err, flag.ErrHelp) {
			writeUsage(stdout)
			return nil, true, nil
		}
		writeUsage(stderr)
		return nil, false, errConfig("%w", err)
	}

	if *showVersion {
		fmt.Fprintf(stdout, "arcet %s\n", versionString())
		return nil, true, nil
	}

	opts = &options{output: *output, config: *configPath, paths: fs.Args()}

	if !validFormat(*format) {
		return nil, false, errConfig("unknown --format %q (want one of: %s)", *format, strings.Join(outputFormats, ", "))
	}
	opts.format = *format

	severity, err := finding.ParseSeverity(*failOn)
	if err != nil {
		return nil, false, errConfig("invalid --fail-on: %w", err)
	}
	opts.failOn = severity

	// An explicit --config that is not there is a mistake worth stopping for.
	// Silently falling back to the defaults would hide a typo in a CI file and
	// report a pass under rules nobody meant to run.
	if opts.config != "" {
		if _, err := os.Stat(opts.config); err != nil {
			return nil, false, errConfig("cannot read --config %s: %w", opts.config, err)
		}
	}

	if len(opts.paths) == 0 {
		writeUsage(stderr)
		return nil, false, errConfig("no paths given: pass at least one workflow file or directory")
	}

	return opts, false, nil
}

func validFormat(f string) bool {
	for _, known := range outputFormats {
		if known == f {
			return true
		}
	}
	return false
}

// writeUsage prints the help text. It documents the exit codes because they
// are the part of the interface people actually integrate against.
func writeUsage(w io.Writer) {
	fmt.Fprint(w, `arcet — static auditor for CI/CD workflows

Usage:
  arcet [flags] <path>...

Paths may be workflow files or directories. arcet reads them; it never
executes them, and it makes no network requests.

Flags:
  --format string    report format: text, json, sarif (default "text")
  --output string    write the report to this file instead of stdout
  --fail-on string   minimum severity that exits 1: low, medium, high,
                     critical (default "medium")
  --config string    path to .arcet.yml
  --version          print the version and exit
  --help             print this help and exit

Exit codes:
  0  analysis completed, nothing at or above the --fail-on threshold
  1  analysis completed, findings at or above the threshold
  2  arcet failed (unreadable file, invalid YAML, internal error)
  3  bad arguments or bad configuration
`)
}
