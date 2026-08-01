import { describe, expect, it } from "vitest";

import type { Event } from "@opencode-ai/sdk";
import type { Hooks, PluginInput } from "@opencode-ai/plugin";

import {
  isPythonFile,
  isSkippedFile,
  isDependencyFile,
  getFilePath,
  getPatchFilePaths,
  formatFindings,
  parseRuffJson,
  parseRadonJson,
  parseBanditJson,
  parseTyText,
  parseSafetyJson,
  parsePyrightJson,
  parseSemgrepJson,
  PxcliQualityPlugin,
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
// getPatchFilePaths
// ---------------------------------------------------------------------------

describe("getPatchFilePaths", () => {
  it("extracts paths from Add/Update/Delete sections", () => {
    const patch = `*** Add File: src/main.py
+code
*** Update File: src/module.py
+code
*** Delete File: src/old.py
-content`;
    expect(getPatchFilePaths(patch)).toEqual([
      "src/main.py",
      "src/module.py",
      "src/old.py",
    ]);
  });

  it("extracts both paths from Move sections", () => {
    const patch = `*** Move File: src/old.py → src/new.py
+content`;
    expect(getPatchFilePaths(patch)).toEqual(["src/old.py", "src/new.py"]);
  });

  it("returns empty for text without file sections", () => {
    expect(getPatchFilePaths("no sections here")).toEqual([]);
  });

  it("returns empty for empty patch text", () => {
    expect(getPatchFilePaths("")).toEqual([]);
  });

  it("de-duplicates repeated paths", () => {
    const patch = `*** Update File: src/main.py
+code
*** Update File: src/main.py
+more`;
    expect(getPatchFilePaths(patch)).toEqual(["src/main.py"]);
  });

  it("ignores an empty Move destination", () => {
    const patch = `*** Move File: src/old.py →
+content`;
    expect(getPatchFilePaths(patch)).toEqual(["src/old.py"]);
  });

  it("ignores an empty Move source", () => {
    const patch = `*** Move File: → src/new.py
+content`;
    expect(getPatchFilePaths(patch)).toEqual(["src/new.py"]);
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

  it("omits the code segment when the code is empty", () => {
    const findings: Finding[] = [
      { tool: "ruff", line: 10, code: "", message: "generic finding", severity: "warning" },
    ];
    const output = formatFindings(findings);
    expect(output).toContain("ruff: L10 — generic finding");
    expect(output).toContain("L10 — generic finding");
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

  it("skips top-level values that are not block arrays", () => {
    const json = JSON.stringify({ "src/main.py": "not an array" });
    const findings = parseRadonJson(json);
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

  it("uses a placeholder severity when issue_severity is empty", () => {
    const json = JSON.stringify({
      results: [
        {
          line_number: 1,
          test_id: "B101",
          issue_severity: "",
          issue_text: "no severity",
        },
      ],
    });
    const findings = parseBanditJson(json);
    expect(findings?.[0]?.code).toBe("B101 (?)");
    expect(findings?.[0]?.severity).toBe("warning");
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

  it("handles a diagnostic as the final line with no location", () => {
    const output = "warning[W002]: dangling diagnostic";
    const findings = parseTyText(output);
    expect(findings).toHaveLength(1);
    expect(findings[0]).toMatchObject({
      tool: "ty",
      line: 0,
      code: "W002",
      severity: "warning",
    });
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

  it("skips projects whose files is not an array", () => {
    const json = JSON.stringify({
      scan_results: { projects: [{ files: "nope" }] },
    });
    expect(parseSafetyJson(json)).toEqual([]);
  });

  it("skips files whose dependencies is not an array", () => {
    const json = JSON.stringify({
      scan_results: {
        projects: [{ files: [{ results: { dependencies: "nope" } }] }],
      },
    });
    expect(parseSafetyJson(json)).toEqual([]);
  });

  it("skips dependencies without a known_vulnerabilities array", () => {
    const json = JSON.stringify({
      scan_results: {
        projects: [
          {
            files: [
              { results: { dependencies: [{ name: "x", known_vulnerabilities: "nope" }] } },
            ],
          },
        ],
      },
    });
    expect(parseSafetyJson(json)).toEqual([]);
  });

  it("falls back to a generic advisory and vulnerability_id", () => {
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
                        { vulnerability_id: "CVE-2024-7", CVE: "CVE-OLD" },
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
    expect(findings?.[0]?.code).toBe("CVE-2024-7");
    expect(findings?.[0]?.message).toContain("requests — CVE-2024-7");
  });

  it("falls back to the CVE when no vulnerability_id exists", () => {
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
                        { CVE: "CVE-1999-0001", advisory: "old bug" },
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
    expect(findings?.[0]?.code).toBe("CVE-1999-0001");
  });

  it("uses a generic message when no advisory fields are present", () => {
    const json = JSON.stringify({
      scan_results: {
        projects: [
          {
            files: [
              {
                results: {
                  dependencies: [
                    { name: "requests", known_vulnerabilities: [{}] },
                  ],
                },
              },
            ],
          },
        ],
      },
    });
    const findings = parseSafetyJson(json);
    expect(findings?.[0]?.message).toBe("requests — vulnerability found");
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

  it("defaults the line to 0 when range.start.line is missing", () => {
    const json = JSON.stringify({
      generalDiagnostics: [
        {
          rule: "reportUnused",
          message: "unused",
          severity: "warning",
          range: { start: {} },
        },
      ],
    });
    const findings = parsePyrightJson(json);
    expect(findings?.[0]).toMatchObject({ tool: "pyright", line: 0 });
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

// ---------------------------------------------------------------------------
// Hook-level tests (PxcliQualityPlugin factory)
// ---------------------------------------------------------------------------

interface LogEntry {
  service: string;
  level: string;
  message: string;
}

interface ShellCall {
  command: string;
  cwd?: string;
}

interface ShellResult {
  exitCode?: number;
  stdout?: string;
  stderr?: string;
}

function createFakeShell(
  handler: (command: string) => ShellResult | undefined,
): { shell: PluginInput["$"]; calls: ShellCall[] } {
  const calls: ShellCall[] = [];

  const shell = (
    strings: TemplateStringsArray,
    ...expressions: unknown[]
  ): unknown => {
    let command = "";
    for (let index = 0; index < strings.length; index += 1) {
      command += strings[index] ?? "";
      const expression = expressions[index];
      if (expression === undefined) continue;
      if (typeof expression === "string") {
        command += expression;
      } else if (
        typeof expression === "number" ||
        typeof expression === "boolean" ||
        typeof expression === "bigint"
      ) {
        command += String(expression);
      } else if (Array.isArray(expression)) {
        command += expression.map((item) => item as string).join(" ");
      }
    }

    const call: ShellCall = { command };
    calls.push(call);

    const base = Promise.resolve().then(() => {
      const result = handler(command);
      return {
        exitCode: result?.exitCode ?? 0,
        stdout: Buffer.from(result?.stdout ?? ""),
        stderr: Buffer.from(result?.stderr ?? ""),
      };
    });
    void base.catch(() => undefined);

    const chained = Object.assign(base, {
      cwd: (dir: string): unknown => {
        call.cwd = dir;
        return chained;
      },
      quiet: (): unknown => chained,
      nothrow: (): unknown => chained,
      throws: (): unknown => chained,
      env: (): unknown => chained,
    });

    return chained;
  };

  return { shell: shell as unknown as PluginInput["$"], calls };
}

async function createPxcliFixture(
  handler: (command: string) => ShellResult | undefined,
  directory: string,
): Promise<{ hooks: Hooks; logs: LogEntry[]; calls: ShellCall[] }> {
  const logs: LogEntry[] = [];
  const client = {
    app: {
      log: (input: { body: LogEntry }): Promise<void> => {
        logs.push(input.body);
        return Promise.resolve();
      },
    },
  } as unknown as PluginInput["client"];

  const fake = createFakeShell(handler);
  const hooks = await PxcliQualityPlugin({
    client,
    $: fake.shell,
    directory,
  } as unknown as PluginInput);

  return { hooks, logs, calls: fake.calls };
}

const idleEvent: Event = {
  type: "session.idle",
  properties: { sessionID: "session-1" },
};

function cleanPerFileHandler(): (command: string) => ShellResult {
  return (command: string): ShellResult => {
    if (command.startsWith("uv run ruff check")) {
      return {
        exitCode: 0,
        stdout: JSON.stringify([
          {
            location: { row: 5 },
            code: "F401",
            message: "unused import os",
          },
        ]),
        stderr: "",
      };
    }
    if (command.startsWith("uv run radon cc")) {
      return { exitCode: 0, stdout: JSON.stringify({ "src/main.py": [] }), stderr: "" };
    }
    if (command.startsWith("uv run bandit")) {
      return { exitCode: 0, stdout: JSON.stringify({ results: [] }), stderr: "" };
    }
    if (command.startsWith("uv run ty check")) {
      return { exitCode: 0, stdout: "No issues found", stderr: "" };
    }
    return { exitCode: 0, stdout: "", stderr: "" };
  };
}

describe("PxcliQualityPlugin hooks", () => {
  it("injects the conventions block into the system prompt", async () => {
    const { hooks } = await createPxcliFixture(cleanPerFileHandler(), "/fake/dir");
    const output = { system: [] as string[] };
    const transformInput = {
      sessionID: "s",
      model: {},
    } as unknown as Parameters<
      NonNullable<Hooks["experimental.chat.system.transform"]>
    >[0];
    await hooks["experimental.chat.system.transform"]?.(transformInput, output);
    expect(output.system).toHaveLength(1);
    expect(output.system[0]).toContain("Python Coding Conventions (pxcli project)");
    expect(output.system[0]).toContain("cyclomatic complexity");
  });

  it("dispatches all four per-file tools after a write to a python file", async () => {
    const { hooks, calls } = await createPxcliFixture(cleanPerFileHandler(), "/fake/dir");
    const output = { title: "write", output: "wrote", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "src/main.py" } },
      output,
    );
    expect(calls.map((call) => call.command)).toEqual([
      "uv run ruff check src/main.py --output-format=json --no-fix",
      "uv run radon cc src/main.py -j",
      "uv run bandit src/main.py -f json -c pyproject.toml",
      "uv run ty check src/main.py",
    ]);
    expect(output.output).toContain("--- Quality Check ---");
    expect(output.output).toContain("ruff: L5 F401 — unused import os");
  });

  it("dispatches the same checks after an edit to a python file", async () => {
    const { hooks, calls } = await createPxcliFixture(cleanPerFileHandler(), "/fake/dir");
    const output = { title: "edit", output: "edited", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "edit", sessionID: "s", callID: "c", args: { filePath: "src/main.py" } },
      output,
    );
    expect(calls).toHaveLength(4);
    expect(output.output).toContain("--- Quality Check ---");
  });

  it("runs the safety scan with the correct argv after editing a dependency file", async () => {
    const { hooks, calls } = await createPxcliFixture((command) => {
      if (command.startsWith("uvx --from safety==3.8.1 safety scan --target /fake/dir")) {
        return {
          exitCode: 0,
          stdout: JSON.stringify({
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
                                vulnerability_id: "CVE-2024-1",
                                advisory: "security issue",
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
          }),
          stderr: "",
        };
      }
      return { exitCode: 0, stdout: "", stderr: "" };
    }, "/fake/dir");
    const output = { title: "edit", output: "edited", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "edit", sessionID: "s", callID: "c", args: { filePath: "pyproject.toml" } },
      output,
    );
    expect(calls).toHaveLength(1);
    expect(calls[0]?.command).toContain("--target /fake/dir");
    expect(calls[0]?.command).toContain("--output json");
    expect(output.output).toContain("--- Dependency Security Check ---");
    expect(output.output).toContain("CVE-2024-1");
  });

  it("marks a tool unavailable on failure and caches the failure", async () => {
    let ruffCalls = 0;
    const { hooks, calls, logs } = await createPxcliFixture((command) => {
      if (command.startsWith("uv run ruff check")) {
        ruffCalls += 1;
        return { exitCode: 1, stdout: "boom", stderr: "bad output" };
      }
      if (command.startsWith("uv run radon cc")) {
        return { exitCode: 0, stdout: JSON.stringify({ "src/a.py": [] }), stderr: "" };
      }
      if (command.startsWith("uv run bandit")) {
        return { exitCode: 0, stdout: JSON.stringify({ results: [] }), stderr: "" };
      }
      if (command.startsWith("uv run ty check")) {
        return { exitCode: 0, stdout: "ok", stderr: "" };
      }
      return { exitCode: 0, stdout: "", stderr: "" };
    }, "/fake/dir");

    const first = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "src/a.py" } },
      first,
    );
    expect(ruffCalls).toBe(1);
    expect(first.output).toContain("ruff:  TOOL_FAILURE");
    expect(logs.some((entry) => entry.level === "warn" && entry.message.includes("ruff failed"))).toBe(true);

    const second = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "src/b.py" } },
      second,
    );
    expect(ruffCalls).toBe(1);
    expect(calls.filter((call) => call.command.startsWith("uv run ruff"))).toHaveLength(1);
    expect(second.output).toContain("ruff:  TOOL_FAILURE");
    const ruffWarns = logs.filter((entry) => entry.message.includes("ruff failed"));
    expect(ruffWarns).toHaveLength(1);
  });

  it("marks a tool unavailable when exit-code-0 output is malformed", async () => {
    const { hooks } = await createPxcliFixture((command) => {
      if (command.startsWith("uv run ruff check")) {
        return { exitCode: 0, stdout: "{broken json", stderr: "" };
      }
      if (command.startsWith("uv run radon cc")) {
        return { exitCode: 0, stdout: JSON.stringify({ "src/main.py": [] }), stderr: "" };
      }
      if (command.startsWith("uv run bandit")) {
        return { exitCode: 0, stdout: JSON.stringify({ results: [] }), stderr: "" };
      }
      if (command.startsWith("uv run ty check")) {
        return { exitCode: 0, stdout: "ok", stderr: "" };
      }
      return { exitCode: 0, stdout: "", stderr: "" };
    }, "/fake/dir");
    const output = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "src/main.py" } },
      output,
    );
    expect(output.output).toContain("TOOL_FAILURE");
    expect(output.output).toContain("exit code 0; output could not be parsed");
  });

  it("triggers checks on python and dependency files via apply_patch", async () => {
    const { hooks, calls } = await createPxcliFixture((command) => {
      if (command.startsWith("uv run ruff check")) {
        return { exitCode: 0, stdout: JSON.stringify([]), stderr: "" };
      }
      if (command.startsWith("uv run radon cc")) {
        return { exitCode: 0, stdout: JSON.stringify({ "src/main.py": [] }), stderr: "" };
      }
      if (command.startsWith("uv run bandit")) {
        return { exitCode: 0, stdout: JSON.stringify({ results: [] }), stderr: "" };
      }
      if (command.startsWith("uv run ty check")) {
        return { exitCode: 0, stdout: "ok", stderr: "" };
      }
      if (command.startsWith("uvx --from safety==3.8.1")) {
        return {
          exitCode: 0,
          stdout: JSON.stringify({
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
                              { vulnerability_id: "CVE-2024-2", advisory: "issue" },
                            ],
                          },
                        ],
                      },
                    },
                  ],
                },
              ],
            },
          }),
          stderr: "",
        };
      }
      return { exitCode: 0, stdout: "", stderr: "" };
    }, "/fake/dir");

    const patchText = `*** Update File: src/main.py
+print("x")
*** Update File: src/module.py
+def f(): pass
*** Add File: pyproject.toml
+[deps]
`;
    const output = { title: "apply_patch", output: "patched", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "apply_patch", sessionID: "s", callID: "c", args: { patchText } },
      output,
    );

    const commands = calls.map((call) => call.command);
    expect(commands.some((cmd) => cmd.includes("ruff check src/main.py"))).toBe(true);
    expect(commands.some((cmd) => cmd.includes("ruff check src/module.py"))).toBe(true);
    expect(commands.some((cmd) => cmd.startsWith("uvx --from safety==3.8.1"))).toBe(true);
    expect(output.output).toContain("--- Dependency Security Check ---");
    expect(output.output).toContain("CVE-2024-2");
  });

  it("skips checks for skipped and non-python files", async () => {
    const { hooks, calls } = await createPxcliFixture(cleanPerFileHandler(), "/fake/dir");
    const output = { title: "write", output: "unchanged", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "tests/test_main.py" } },
      output,
    );
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "src/not_python.ts" } },
      output,
    );
    expect(calls).toHaveLength(0);
    expect(output.output).toBe("unchanged");
  });

  it("does nothing for unrelated tools", async () => {
    const { hooks, calls } = await createPxcliFixture(cleanPerFileHandler(), "/fake/dir");
    const output = { title: "bash", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "bash", sessionID: "s", callID: "c", args: { command: "echo hi" } },
      output,
    );
    expect(calls).toHaveLength(0);
    expect(output.output).toBe("");
  });

  it("returns early when write args lack a file path", async () => {
    const { hooks, calls } = await createPxcliFixture(cleanPerFileHandler(), "/fake/dir");
    const output = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: {} },
      output,
    );
    expect(calls).toHaveLength(0);
  });

  it("session idle runs semgrep+pyright on modified files then clears the set", async () => {
    const { hooks, logs } = await createPxcliFixture((command) => {
      if (command.startsWith("uv run ruff check")) {
        return {
          exitCode: 0,
          stdout: JSON.stringify([
            { location: { row: 1 }, code: "F401", message: "unused" },
          ]),
          stderr: "",
        };
      }
      if (command.startsWith("uv run radon cc")) {
        return { exitCode: 0, stdout: JSON.stringify({ "src/main.py": [] }), stderr: "" };
      }
      if (command.startsWith("uv run bandit")) {
        return { exitCode: 0, stdout: JSON.stringify({ results: [] }), stderr: "" };
      }
      if (command.startsWith("uv run ty check")) {
        return { exitCode: 0, stdout: "ok", stderr: "" };
      }
      if (command.startsWith("make semgrep-json")) {
        return {
          exitCode: 1,
          stdout: JSON.stringify({
            results: [
              {
                check_id: "python.lang.security.eval",
                start: { line: 3 },
                extra: { message: "eval used", severity: "ERROR" },
              },
            ],
          }),
          stderr: "",
        };
      }
      if (command.startsWith("uv run pyright --outputjson")) {
        return {
          exitCode: 1,
          stdout: JSON.stringify({
            generalDiagnostics: [
              {
                rule: "reportEval",
                message: "eval is unsafe",
                severity: "error",
                range: { start: { line: 0 } },
              },
            ],
          }),
          stderr: "",
        };
      }
      return { exitCode: 0, stdout: "", stderr: "" };
    }, "/fake/dir");

    const output = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "src/main.py" } },
      output,
    );

    await hooks.event?.({ event: idleEvent });
    expect(logs).toHaveLength(1);
    expect(logs[0]?.level).toBe("warn");
    expect(logs[0]?.message).toContain("semgrep");
    expect(logs[0]?.message).toContain("pyright");
    expect(logs[0]?.message).toContain("1 modified file(s)");

    await hooks.event?.({ event: idleEvent });
    expect(logs).toHaveLength(1);
  });

  it("session idle logs info when all checks pass", async () => {
    const { hooks, logs } = await createPxcliFixture((command) => {
      if (command.startsWith("uv run ruff check")) {
        return { exitCode: 0, stdout: JSON.stringify([]), stderr: "" };
      }
      if (command.startsWith("uv run radon cc")) {
        return { exitCode: 0, stdout: JSON.stringify({ "src/main.py": [] }), stderr: "" };
      }
      if (command.startsWith("uv run bandit")) {
        return { exitCode: 0, stdout: JSON.stringify({ results: [] }), stderr: "" };
      }
      if (command.startsWith("uv run ty check")) {
        return { exitCode: 0, stdout: "ok", stderr: "" };
      }
      if (command.startsWith("make semgrep-json")) {
        return { exitCode: 0, stdout: JSON.stringify({ results: [] }), stderr: "" };
      }
      if (command.startsWith("uv run pyright --outputjson")) {
        return {
          exitCode: 0,
          stdout: JSON.stringify({ generalDiagnostics: [] }),
          stderr: "",
        };
      }
      return { exitCode: 0, stdout: "", stderr: "" };
    }, "/fake/dir");

    const output = { title: "edit", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "edit", sessionID: "s", callID: "c", args: { filePath: "src/main.py" } },
      output,
    );

    await hooks.event?.({ event: idleEvent });
    expect(logs).toHaveLength(1);
    expect(logs[0]?.level).toBe("info");
    expect(logs[0]?.message).toContain("all 1 modified file(s) pass semgrep + pyright");
  });

  it("does not mutate output when a dependency scan finds no vulnerabilities", async () => {
    const { hooks, calls } = await createPxcliFixture((command) => {
      if (command.startsWith("uvx --from safety==3.8.1")) {
        return {
          exitCode: 0,
          stdout: JSON.stringify({ scan_results: { projects: [] } }),
          stderr: "",
        };
      }
      return { exitCode: 0, stdout: "", stderr: "" };
    }, "/fake/dir");
    const output = { title: "write", output: "unchanged", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "requirements.txt" } },
      output,
    );
    expect(calls).toHaveLength(1);
    expect(output.output).toBe("unchanged");
  });

  it("pluralises the dependency security summary for multiple vulnerabilities", async () => {
    const { hooks } = await createPxcliFixture((command) => {
      if (command.startsWith("uvx --from safety==3.8.1")) {
        return {
          exitCode: 0,
          stdout: JSON.stringify({
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
                              { vulnerability_id: "CVE-2024-1", advisory: "a" },
                              { vulnerability_id: "CVE-2024-2", advisory: "b" },
                            ],
                          },
                        ],
                      },
                    },
                  ],
                },
              ],
            },
          }),
          stderr: "",
        };
      }
      return { exitCode: 0, stdout: "", stderr: "" };
    }, "/fake/dir");
    const output = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "pyproject.toml" } },
      output,
    );
    expect(output.output).toContain("(2 vulnerabilities found)");
    expect(output.output).not.toContain("vulnerability found)");
  });

  it("does nothing for apply_patch without patch text", async () => {
    const { hooks, calls } = await createPxcliFixture(cleanPerFileHandler(), "/fake/dir");
    const output = { title: "apply_patch", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "apply_patch", sessionID: "s", callID: "c", args: {} },
      output,
    );
    expect(calls).toHaveLength(0);
    expect(output.output).toBe("");
  });

  it("does nothing for apply_patch with no file sections", async () => {
    const { hooks, calls } = await createPxcliFixture(cleanPerFileHandler(), "/fake/dir");
    const output = { title: "apply_patch", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      {
        tool: "apply_patch",
        sessionID: "s",
        callID: "c",
        args: { patchText: "*** Summary\n+no file sections" },
      },
      output,
    );
    expect(calls).toHaveLength(0);
  });

  it("ignores events that are not session.idle", async () => {
    const { hooks, logs } = await createPxcliFixture(cleanPerFileHandler(), "/fake/dir");
    const output = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "src/main.py" } },
      output,
    );
    await hooks.event?.({ event: { type: "session.compacted" } as Event });
    expect(logs).toHaveLength(0);
  });

  it("marks all per-file tools unavailable when the shell throws, then short-circuits", async () => {
    let ruffCalls = 0;
    let radonCalls = 0;
    let banditCalls = 0;
    let tyCalls = 0;
    const { hooks, logs } = await createPxcliFixture((command) => {
      if (command.startsWith("uv run ruff check")) {
        ruffCalls += 1;
        throw new Error("ruff exploded");
      }
      if (command.startsWith("uv run radon cc")) {
        radonCalls += 1;
        throw new Error("radon exploded");
      }
      if (command.startsWith("uv run bandit")) {
        banditCalls += 1;
        throw new Error("bandit exploded");
      }
      if (command.startsWith("uv run ty check")) {
        tyCalls += 1;
        throw new Error("ty exploded");
      }
      return { exitCode: 0, stdout: "", stderr: "" };
    }, "/fake/dir");

    const first = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "src/a.py" } },
      first,
    );
    expect(ruffCalls).toBe(1);
    expect(radonCalls).toBe(1);
    expect(banditCalls).toBe(1);
    expect(tyCalls).toBe(1);
    expect(first.output).toContain("ruff:  TOOL_FAILURE");
    expect(first.output).toContain("radon:  TOOL_FAILURE");
    expect(first.output).toContain("bandit:  TOOL_FAILURE");
    expect(first.output).toContain("ty:  TOOL_FAILURE");
    expect(logs.filter((entry) => entry.level === "warn")).toHaveLength(4);

    const second = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "src/b.py" } },
      second,
    );
    expect(ruffCalls).toBe(1);
    expect(radonCalls).toBe(1);
    expect(banditCalls).toBe(1);
    expect(tyCalls).toBe(1);
    expect(second.output).toContain("TOOL_FAILURE");
    expect(logs.filter((entry) => entry.level === "warn")).toHaveLength(4);
  });

  it("marks safety unavailable on shell throw and caches it", async () => {
    let safetyCalls = 0;
    const { hooks, logs } = await createPxcliFixture((command) => {
      if (command.startsWith("uvx --from safety==3.8.1")) {
        safetyCalls += 1;
        throw new Error("safety exploded");
      }
      return { exitCode: 0, stdout: "", stderr: "" };
    }, "/fake/dir");

    const first = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "pyproject.toml" } },
      first,
    );
    expect(safetyCalls).toBe(1);
    expect(first.output).toContain("TOOL_FAILURE");

    const second = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "requirements.txt" } },
      second,
    );
    expect(safetyCalls).toBe(1);
    expect(second.output).toContain("TOOL_FAILURE");
    expect(logs.filter((entry) => entry.level === "warn")).toHaveLength(1);
  });

  it("handles shell rejections across all tools", async () => {
    const { hooks, logs } = await createPxcliFixture((command) => {
      if (command.startsWith("uv run ruff check")) throw new Error("ruff exploded");
      if (command.startsWith("uv run radon cc")) throw new Error("radon exploded");
      if (command.startsWith("uv run bandit")) throw new Error("bandit exploded");
      if (command.startsWith("uv run ty check")) throw new Error("ty exploded");
      if (command.startsWith("uvx --from safety==3.8.1")) throw new Error("safety exploded");
      if (command.startsWith("make semgrep-json")) throw new Error("semgrep exploded");
      if (command.startsWith("uv run pyright --outputjson")) throw new Error("pyright exploded");
      return { exitCode: 0, stdout: "", stderr: "" };
    }, "/fake/dir");

    const output = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "src/main.py" } },
      output,
    );
    expect(output.output).toContain("ruff exploded");
    expect(output.output).toContain("radon exploded");
    expect(output.output).toContain("bandit exploded");
    expect(output.output).toContain("ty exploded");

    const depOutput = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "pyproject.toml" } },
      depOutput,
    );
    expect(depOutput.output).toContain("safety exploded");

    await hooks.event?.({ event: idleEvent });
    const summaries = logs.filter((entry) => entry.message.includes("Session idle analysis"));
    expect(summaries[0]?.message).toContain("semgrep exploded");
    expect(summaries[0]?.message).toContain("pyright exploded");
  });

  it("marks semgrep and pyright unavailable on shell throw and caches them", async () => {
    let semgrepCalls = 0;
    let pyrightCalls = 0;
    const { hooks, logs } = await createPxcliFixture((command) => {
      if (command.startsWith("uv run ruff check")) {
        return { exitCode: 0, stdout: JSON.stringify([]), stderr: "" };
      }
      if (command.startsWith("uv run radon cc")) {
        return { exitCode: 0, stdout: JSON.stringify({ "src/a.py": [] }), stderr: "" };
      }
      if (command.startsWith("uv run bandit")) {
        return { exitCode: 0, stdout: JSON.stringify({ results: [] }), stderr: "" };
      }
      if (command.startsWith("uv run ty check")) {
        return { exitCode: 0, stdout: "ok", stderr: "" };
      }
      if (command.startsWith("make semgrep-json")) {
        semgrepCalls += 1;
        throw new Error("semgrep exploded");
      }
      if (command.startsWith("uv run pyright --outputjson")) {
        pyrightCalls += 1;
        throw new Error("pyright exploded");
      }
      return { exitCode: 0, stdout: "", stderr: "" };
    }, "/fake/dir");

    const first = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "src/a.py" } },
      first,
    );
    await hooks.event?.({ event: idleEvent });
    expect(semgrepCalls).toBe(1);
    expect(pyrightCalls).toBe(1);
    const firstSummaries = logs.filter((entry) => entry.message.includes("Session idle analysis"));
    expect(firstSummaries).toHaveLength(1);
    expect(firstSummaries[0]?.level).toBe("warn");
    expect(firstSummaries[0]?.message).toContain("semgrep:  TOOL_FAILURE");
    expect(firstSummaries[0]?.message).toContain("pyright:  TOOL_FAILURE");

    const second = { title: "write", output: "", metadata: {} };
    await hooks["tool.execute.after"]?.(
      { tool: "write", sessionID: "s", callID: "c", args: { filePath: "src/b.py" } },
      second,
    );
    await hooks.event?.({ event: idleEvent });
    expect(semgrepCalls).toBe(1);
    expect(pyrightCalls).toBe(1);
    const allSummaries = logs.filter((entry) => entry.message.includes("Session idle analysis"));
    expect(allSummaries).toHaveLength(2);
    expect(allSummaries[1]?.level).toBe("warn");
  });
});
