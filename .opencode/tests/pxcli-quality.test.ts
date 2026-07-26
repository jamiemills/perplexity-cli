import { describe, expect, it } from "vitest";

import {
  isPythonFile,
  isSkippedFile,
  isDependencyFile,
  getFilePath,
  formatFindings,
  parseRuffJson,
  parseRadonJson,
  parseBanditJson,
  parseTyText,
  parseSafetyJson,
  parsePyrightJson,
  parseSemgrepJson,
  type Finding,
} from "../plugins/pxcli-quality";

// ---------------------------------------------------------------------------
// isPythonFile
// ---------------------------------------------------------------------------

describe("isPythonFile", () => {
  it("matches .py extension", () => {
    expect(isPythonFile("src/main.py")).toBe(true);
  });

  it("rejects non-.py files", () => {
    expect(isPythonFile("src/main.ts")).toBe(false);
  });

  it("rejects .pyc files", () => {
    expect(isPythonFile("__pycache__/main.pyc")).toBe(false);
  });

  it("handles absolute paths", () => {
    expect(isPythonFile("/home/user/project/module.py")).toBe(true);
  });

  it("rejects empty string", () => {
    expect(isPythonFile("")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isSkippedFile
// ---------------------------------------------------------------------------

describe("isSkippedFile", () => {
  it("skips files in tests/ directory", () => {
    expect(isSkippedFile("tests/test_main.py")).toBe(true);
  });

  it("skips test_ prefixed files", () => {
    expect(isSkippedFile("src/test_utils.py")).toBe(true);
  });

  it("skips conftest.py", () => {
    expect(isSkippedFile("tests/conftest.py")).toBe(true);
  });

  it("skips vulture_whitelist.py", () => {
    expect(isSkippedFile("vulture_whitelist.py")).toBe(true);
  });

  it("skips fuzz harness files", () => {
    expect(isSkippedFile("tests/_fuzz_harnesses.py")).toBe(true);
  });

  it("does not skip regular Python files", () => {
    expect(isSkippedFile("src/main.py")).toBe(false);
  });

  it("does not skip files containing 'test' but not matching patterns", () => {
    expect(isSkippedFile("src/protest.py")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isDependencyFile
// ---------------------------------------------------------------------------

describe("isDependencyFile", () => {
  it("matches pyproject.toml", () => {
    expect(isDependencyFile("pyproject.toml")).toBe(true);
  });

  it("matches requirements.txt", () => {
    expect(isDependencyFile("requirements.txt")).toBe(true);
  });

  it("matches requirements-dev.txt", () => {
    expect(isDependencyFile("requirements-dev.txt")).toBe(true);
  });

  it("rejects non-dependency files", () => {
    expect(isDependencyFile("src/main.py")).toBe(false);
  });

  it("rejects similarly-named files", () => {
    expect(isDependencyFile("my-pyproject.toml.backup")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// getFilePath
// ---------------------------------------------------------------------------

describe("getFilePath", () => {
  it("extracts filePath from args", () => {
    expect(getFilePath({ filePath: "src/main.py" })).toBe("src/main.py");
  });

  it("extracts file_path from args", () => {
    expect(getFilePath({ file_path: "src/main.py" })).toBe("src/main.py");
  });

  it("extracts path from args", () => {
    expect(getFilePath({ path: "src/main.py" })).toBe("src/main.py");
  });

  it("prefers filePath over other keys", () => {
    expect(
      getFilePath({
        filePath: "a.py",
        file_path: "b.py",
        path: "c.py",
      }),
    ).toBe("a.py");
  });

  it("returns null for undefined args", () => {
    expect(getFilePath(undefined)).toBeNull();
  });

  it("returns null for empty args", () => {
    expect(getFilePath({})).toBeNull();
  });

  it("returns null for args with no recognised keys", () => {
    expect(getFilePath({ tool: "write" })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// formatFindings
// ---------------------------------------------------------------------------

describe("formatFindings", () => {
  it("returns empty string for no findings", () => {
    expect(formatFindings([])).toBe("");
  });

  it("formats a single finding with line and code", () => {
    const findings: Finding[] = [
      { tool: "ruff", line: 42, code: "F401", message: "unused import", severity: "warning" },
    ];
    const output = formatFindings(findings);
    expect(output).toContain("ruff: L42 F401");
    expect(output).toContain("unused import");
    expect(output).toContain("(1 finding from: ruff)");
  });

  it("formats a finding with line 0 without L prefix", () => {
    const findings: Finding[] = [
      { tool: "bandit", line: 0, code: "B101", message: "assert used", severity: "warning" },
    ];
    const output = formatFindings(findings);
    expect(output).toContain("bandit:  B101");
    expect(output).not.toContain("L0");
  });

  it("formats multiple findings from different tools", () => {
    const findings: Finding[] = [
      { tool: "ruff", line: 10, code: "E501", message: "line too long", severity: "warning" },
      { tool: "radon", line: 25, code: "CC=6", message: "complexity 6", severity: "warning" },
    ];
    const output = formatFindings(findings);
    expect(output).toContain("ruff");
    expect(output).toContain("radon");
    expect(output).toContain("(2 findings from: ruff, radon)");
  });
});

// ---------------------------------------------------------------------------
// parseRuffJson
// ---------------------------------------------------------------------------

describe("parseRuffJson", () => {
  it("parses valid ruff JSON output", () => {
    const json = JSON.stringify([
      { location: { row: 10 }, code: "F401", message: "unused import os" },
      { location: { row: 42 }, code: "E501", message: "line too long" },
    ]);
    const findings = parseRuffJson(json);
    expect(findings).toHaveLength(2);
    expect(findings?.[0]).toMatchObject({
      tool: "ruff",
      line: 10,
      code: "F401",
      message: "unused import os",
      severity: "warning",
    });
  });

  it("handles missing location.row gracefully", () => {
    const json = JSON.stringify([
      { code: "F401", message: "unused import" },
    ]);
    const findings = parseRuffJson(json);
    expect(findings).toHaveLength(1);
    expect(findings?.[0]?.line).toBe(0);
  });

  it("returns null for malformed JSON", () => {
    expect(parseRuffJson("not json at all")).toBeNull();
  });

  it("returns null for non-array JSON", () => {
    expect(parseRuffJson('{"not": "an array"}')).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(parseRuffJson("")).toBeNull();
  });

  it("returns empty findings for empty array", () => {
    const findings = parseRuffJson("[]");
    expect(findings).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// parseRadonJson
// ---------------------------------------------------------------------------

describe("parseRadonJson", () => {
  it("parses valid radon JSON output", () => {
    const json = JSON.stringify({
      "src/main.py": [
        { type: "function", name: "foo", rank: "B", complexity: 6, lineno: 10 },
        { type: "method", name: "bar", rank: "A", complexity: 3, lineno: 20 },
      ],
    });
    const findings = parseRadonJson(json);
    expect(findings).toHaveLength(1);
    expect(findings?.[0]).toMatchObject({
      tool: "radon",
      line: 10,
      code: "CC=6",
      severity: "warning",
    });
  });

  it("excludes A-rank blocks", () => {
    const json = JSON.stringify({
      "src/main.py": [
        { type: "function", name: "simple", rank: "A", complexity: 2, lineno: 5 },
      ],
    });
    const findings = parseRadonJson(json);
    expect(findings).toHaveLength(0);
  });

  it("returns null for malformed JSON", () => {
    expect(parseRadonJson("{invalid")).toBeNull();
  });

  it("returns null for non-object JSON", () => {
    expect(parseRadonJson("[]")).toBeNull();
  });

  it("returns null for null JSON", () => {
    expect(parseRadonJson("null")).toBeNull();
  });

  it("returns empty for object with no blocks", () => {
    const findings = parseRadonJson("{}");
    expect(findings).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// parseBanditJson
// ---------------------------------------------------------------------------

describe("parseBanditJson", () => {
  it("parses valid bandit JSON output", () => {
    const json = JSON.stringify({
      results: [
        {
          line_number: 15,
          test_id: "B101",
          issue_severity: "HIGH",
          issue_text: "assert used",
        },
        {
          line_number: 30,
          test_id: "B104",
          issue_severity: "LOW",
          issue_text: "hardcoded bind",
        },
      ],
    });
    const findings = parseBanditJson(json);
    expect(findings).toHaveLength(2);
    expect(findings?.[0]).toMatchObject({
      tool: "bandit",
      line: 15,
      code: "B101 (HIGH)",
      severity: "error",
    });
    expect(findings?.[1]?.severity).toBe("warning");
  });

  it("returns null for malformed JSON", () => {
    expect(parseBanditJson("garbage")).toBeNull();
  });

  it("returns null when results is not an array", () => {
    expect(parseBanditJson('{"results": {}}')).toBeNull();
  });

  it("returns null when results is missing", () => {
    expect(parseBanditJson("{}")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// parseTyText
// ---------------------------------------------------------------------------

describe("parseTyText", () => {
  it("parses valid ty diagnostic output", () => {
    const output = `error[E001]: type mismatch
  --> src/main.py:10:5
warning[W002]: unused variable
  --> src/utils.py:42:1`;
    const findings = parseTyText(output);
    expect(findings).toHaveLength(2);
    expect(findings[0]).toMatchObject({
      tool: "ty",
      line: 10,
      code: "E001",
      message: "type mismatch",
      severity: "error",
    });
    expect(findings[1]).toMatchObject({
      tool: "ty",
      line: 42,
      code: "W002",
      message: "unused variable",
      severity: "warning",
    });
  });

  it("returns empty array for empty output", () => {
    expect(parseTyText("")).toEqual([]);
  });

  it("returns empty array for output without diagnostics", () => {
    expect(parseTyText("No issues found.")).toEqual([]);
  });

  it("handles output with diagnostics but no location lines", () => {
    const output = `error[E001]: type mismatch
something else`;
    const findings = parseTyText(output);
    expect(findings).toHaveLength(1);
    expect(findings[0]?.line).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// parseSafetyJson
// ---------------------------------------------------------------------------

describe("parseSafetyJson", () => {
  it("parses valid safety JSON output", () => {
    const json = JSON.stringify({
      scan_results: {
        projects: [
          {
            files: [
              {
                results: {
                  dependencies: [
                    {
                      name: "requests",
                      known_vulnerabilities: [
                        {
                          vulnerability_id: "CVE-2024-001",
                          advisory: "Security issue in requests",
                        },
                      ],
                    },
                  ],
                },
              },
            ],
          },
        ],
      },
    });
    const findings = parseSafetyJson(json);
    expect(findings).toHaveLength(1);
    expect(findings?.[0]).toMatchObject({
      tool: "safety",
      code: "CVE-2024-001",
      severity: "error",
    });
  });

  it("returns null for malformed JSON", () => {
    expect(parseSafetyJson("{broken")).toBeNull();
  });

  it("returns null when scan_results is missing", () => {
    expect(parseSafetyJson("{}")).toBeNull();
  });

  it("returns null when projects is not an array", () => {
    expect(parseSafetyJson('{"scan_results": {"projects": "nope"}}')).toBeNull();
  });

  it("returns empty array when no vulnerabilities found", () => {
    const json = JSON.stringify({
      scan_results: {
        projects: [
          {
            files: [
              {
                results: {
                  dependencies: [
                    { name: "safe-dep", known_vulnerabilities: [] },
                  ],
                },
              },
            ],
          },
        ],
      },
    });
    const findings = parseSafetyJson(json);
    expect(findings).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// parsePyrightJson
// ---------------------------------------------------------------------------

describe("parsePyrightJson", () => {
  it("parses valid pyright JSON output", () => {
    const json = JSON.stringify({
      generalDiagnostics: [
        {
          rule: "reportUnknownMemberType",
          message: "Type of 'foo' is unknown",
          severity: "error",
          range: { start: { line: 4 } },
        },
        {
          rule: "reportUnusedVariable",
          message: 'Variable "x" is not accessed',
          severity: "warning",
          range: { start: { line: 10 } },
        },
      ],
    });
    const findings = parsePyrightJson(json);
    expect(findings).toHaveLength(2);
    expect(findings?.[0]).toMatchObject({
      tool: "pyright",
      line: 5,
      code: "reportUnknownMemberType",
      severity: "error",
    });
    expect(findings?.[1]?.severity).toBe("warning");
  });

  it("returns null for malformed JSON", () => {
    expect(parsePyrightJson("bad json")).toBeNull();
  });

  it("returns null when generalDiagnostics is not an array", () => {
    expect(parsePyrightJson('{"generalDiagnostics": "not array"}')).toBeNull();
  });

  it("returns null when generalDiagnostics is missing", () => {
    expect(parsePyrightJson("{}")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// parseSemgrepJson
// ---------------------------------------------------------------------------

describe("parseSemgrepJson", () => {
  it("parses valid semgrep JSON output", () => {
    const json = JSON.stringify({
      results: [
        {
          check_id: "python.lang.security.use-defusedxml",
          start: { line: 15 },
          extra: {
            message: "Use of insecure XML parser",
            severity: "ERROR",
          },
        },
        {
          check_id: "python.lang.correctness",
          start: { line: 30 },
          extra: {
            message: "Possible None reference",
            severity: "WARNING",
          },
        },
        {
          check_id: "python.lang.best-practice",
          start: { line: 50 },
          extra: {
            message: "Consider using context manager",
            severity: "INFO",
          },
        },
      ],
    });
    const findings = parseSemgrepJson(json);
    expect(findings).toHaveLength(3);
    expect(findings?.[0]).toMatchObject({
      tool: "semgrep",
      line: 15,
      code: "python.lang.security.use-defusedxml",
      severity: "error",
    });
    expect(findings?.[1]?.severity).toBe("warning");
    expect(findings?.[2]?.severity).toBe("info");
  });

  it("returns null for malformed JSON", () => {
    expect(parseSemgrepJson("not-json")).toBeNull();
  });

  it("returns null when results is not an array", () => {
    expect(parseSemgrepJson('{"results": "nope"}')).toBeNull();
  });

  it("returns null when results is missing", () => {
    expect(parseSemgrepJson("{}")).toBeNull();
  });

  it("handles missing start.line gracefully", () => {
    const json = JSON.stringify({
      results: [
        {
          check_id: "test",
          extra: { message: "test", severity: "INFO" },
        },
      ],
    });
    const findings = parseSemgrepJson(json);
    expect(findings).toHaveLength(1);
    expect(findings?.[0]?.line).toBe(0);
  });

  it("handles severity defaulting to info", () => {
    const json = JSON.stringify({
      results: [
        {
          check_id: "test",
          start: { line: 1 },
          extra: { message: "test" },
        },
      ],
    });
    const findings = parseSemgrepJson(json);
    expect(findings).toHaveLength(1);
    expect(findings?.[0]?.severity).toBe("info");
  });
});
