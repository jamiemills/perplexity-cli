/**
 * pxcli-quality — OpenCode quality plugin for the perplexity-cli project.
 *
 * Provides three hooks:
 *   1. System prompt injection — coding conventions for every interaction
 *   2. Reactive quality checks — ruff, radon, bandit, ty after Python file edits
 *   3. Session idle analysis — semgrep, pyright on all modified files
 *
 * Additionally triggers a safety scan when pyproject.toml is edited.
 */

import type { Plugin } from "@opencode-ai/plugin";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Finding {
  tool: string;
  line: number;
  code: string;
  message: string;
  severity: "error" | "warning" | "info";
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CONVENTIONS_BLOCK = `## Python Coding Conventions (pxcli project)

When writing or modifying Python files in this project, follow these conventions:

### Complexity & Structure
1. Keep cyclomatic complexity <= 5 per function. Extract helper functions for complex logic.
2. Maximum 4 parameters per function. For more, group into a \`@dataclass(frozen=True, slots=True)\`.
3. Google-style docstrings for all public functions, classes, and modules. Not required for tests, \`__init__\`, or magic methods.
4. Type annotations on all function signatures (parameters and return types).
5. Use \`TYPE_CHECKING\` + \`from __future__ import annotations\` for import-only types.

### Logging & Output
6. Use \`%s\`-style lazy formatting in logger calls — never f-strings (e.g. \`logger.info("Processing %s", item)\`).
7. Use \`logger\`, not \`print()\`, for all non-CLI output.
8. Never log tokens, cookies, or credentials.

### Error Handling
9. Never bare \`except:\` or \`except Exception: pass\` — always log something meaningful.
10. Use \`raise X from Y\` in except blocks to preserve tracebacks.

### Security
11. Never use \`eval()\` or \`exec()\`.
12. Never use \`subprocess\` with \`shell=True\`.
13. Never hardcode passwords, secrets, or API keys in source code.
14. Use \`secrets\` module for security-sensitive randomness, not \`random\`.

### Style
15. No single-letter variables except \`e\`, \`f\`, \`i\`, \`j\`, \`k\`, \`v\`, \`x\`, \`y\`, \`n\`.
16. Never use \`from x import *\` (wildcard imports).
17. Use \`is None\` / \`is not None\`, not \`== None\` / \`!= None\`.
18. Delete commented-out code — git remembers.
19. British English in comments and docstrings.

### Dependencies
20. When adding dependencies, pin minimum version floors (\`>=\`) to avoid known-vulnerable ranges.`;

const SKIPPED_PATHS = [
  "/tests/",
  "/test_",
  "conftest.py",
  "vulture_whitelist.py",
  "_fuzz_harnesses.py",
];

const DEPENDENCY_FILES = ["pyproject.toml", "requirements.txt", "requirements-dev.txt"];

// ---------------------------------------------------------------------------
// File classification helpers
// ---------------------------------------------------------------------------

export function isPythonFile(filePath: string): boolean {
  return filePath.endsWith(".py");
}

export function isSkippedFile(filePath: string): boolean {
  return SKIPPED_PATHS.some((pattern) => filePath.includes(pattern));
}

export function isDependencyFile(filePath: string): boolean {
  return DEPENDENCY_FILES.some((name) => filePath.endsWith(name));
}

export function getFilePath(args: Record<string, unknown> | undefined): string | null {
  if (!args) return null;
  const candidates = [args.filePath, args.file_path, args.path];
  for (const candidate of candidates) {
    if (typeof candidate === "string") return candidate;
  }
  return null;
}

const PATCH_SECTION_RE = /^\*\*\* (?:Add|Update|Delete|Move) File: (.+)$/;
const MOVE_ARROW_RE = /(.*?)\s*(?:→|->)\s*(.*)/;

/**
 * Extract the file paths touched by an apply_patch patch text.
 *
 * Move sections yield both the source and destination paths. Duplicate paths
 * are de-duplicated so a file patched twice is only checked once.
 */
export function getPatchFilePaths(patchText: string): string[] {
  const paths: string[] = [];
  for (const line of patchText.split("\n")) {
    const match = PATCH_SECTION_RE.exec(line);
    if (!match) continue;
    const rawPath = (match[1] ?? "").trim();
    const arrow = MOVE_ARROW_RE.exec(rawPath);
    if (arrow) {
      const from = (arrow[1] ?? "").trim();
      const to = (arrow[2] ?? "").trim();
      if (from) paths.push(from);
      if (to) paths.push(to);
    } else {
      paths.push(rawPath);
    }
  }
  return [...new Set(paths)];
}

// ---------------------------------------------------------------------------
// Output formatting
// ---------------------------------------------------------------------------

export function formatFindings(findings: Finding[]): string {
  if (findings.length === 0) return "";

  const lines = findings.map((f) => {
    const loc = f.line > 0 ? `L${f.line}` : "";
    const code = f.code ? ` ${f.code}` : "";
    return `${f.tool}: ${loc}${code} — ${f.message}`;
  });

  const toolsUsed = [...new Set(findings.map((f) => f.tool))];
  const count = findings.length;
  const summary = `(${count} finding${count === 1 ? "" : "s"} from: ${toolsUsed.join(", ")})`;

  return `\n\n--- Quality Check ---\n${lines.join("\n")}\n${summary}`;
}

// ---------------------------------------------------------------------------
// Output parsers
// ---------------------------------------------------------------------------

type JsonObject = Record<string, unknown>;

function asObject(value: unknown): JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asStringOptional(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function asNumber(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

function parseJson(stdout: string): unknown {
  return JSON.parse(stdout);
}

export function parseRuffJson(stdout: string): Finding[] | null {
  try {
    const items = parseJson(stdout);
    if (!Array.isArray(items)) return null;
    return items.map((item: unknown): Finding => {
      const obj = asObject(item);
      const location = asObject(obj.location);
      return {
        tool: "ruff",
        line: asNumber(location.row),
        code: asString(obj.code),
        message: asString(obj.message),
        severity: "warning",
      };
    });
  } catch {
    return null;
  }
}

export function parseRadonJson(stdout: string): Finding[] | null {
  try {
    const data = parseJson(stdout);
    if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
    const findings: Finding[] = [];
    for (const blocks of Object.values(data)) {
      if (!Array.isArray(blocks)) continue;
      for (const block of blocks) {
        const obj = asObject(block);
        const rank = asString(obj.rank);
        if (!rank || rank === "A") continue;
        const complexity = asNumber(obj.complexity);
        findings.push({
          tool: "radon",
          line: asNumber(obj.lineno),
          code: `CC=${complexity}`,
          message: `${asString(obj.type)} '${asString(obj.name)}' ${rank}-grade (complexity ${complexity}, target <=5)`,
          severity: "warning",
        });
      }
    }
    return findings;
  } catch {
    return null;
  }
}

export function parseBanditJson(stdout: string): Finding[] | null {
  try {
    const data = asObject(parseJson(stdout));
    const results = data.results;
    if (!Array.isArray(results)) return null;
    return results.map((r: unknown): Finding => {
      const obj = asObject(r);
      const severity = asString(obj.issue_severity);
      return {
        tool: "bandit",
        line: asNumber(obj.line_number),
        code: `${asString(obj.test_id)} (${severity || "?"})`,
        message: asString(obj.issue_text),
        severity: severity === "HIGH" ? "error" : "warning",
      };
    });
  } catch {
    return null;
  }
}

export function parseTyText(stdout: string): Finding[] {
  const findings: Finding[] = [];
  const diagnosticRe = /^(error|warning)\[([^\]]+)]:\s*(.+)/;
  const locationRe = /^\s*-->\s*.*?:(\d+):(\d+)/;

  const lines = stdout.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const currentLine = lines[i] ?? "";
    const match = diagnosticRe.exec(currentLine);
    if (!match) continue;

    const severity = match[1] === "error" ? "error" : "warning";
    const code = match[2] ?? "";
    const message = match[3] ?? "";
    let line = 0;

    if (i + 1 < lines.length) {
      const locMatch = locationRe.exec(lines[i + 1] ?? "");
      if (locMatch) {
        line = parseInt(locMatch[1] ?? "0", 10);
      }
    }

    findings.push({ tool: "ty", line, code, message, severity });
  }
  return findings;
}

export function parseSafetyJson(stdout: string): Finding[] | null {
  try {
    const data = asObject(parseJson(stdout));
    const scanResults = asObject(data.scan_results);
    const projects = scanResults.projects;
    if (!Array.isArray(projects)) return null;
    const findings: Finding[] = [];
    for (const project of projects) {
      const projectObj = asObject(project);
      const files = projectObj.files;
      if (!Array.isArray(files)) continue;
      for (const file of files) {
        const resultsObj = asObject(asObject(file).results);
        const deps = resultsObj.dependencies;
        if (!Array.isArray(deps)) continue;
        for (const dep of deps) {
          const depObj = asObject(dep);
          const vulns = depObj.known_vulnerabilities;
          if (!Array.isArray(vulns)) continue;
          for (const v of vulns) {
            const vObj = asObject(v);
            const name = asString(depObj.name);
            const advisory =
              asStringOptional(vObj.advisory)
              ?? asStringOptional(vObj.vulnerability_id)
              ?? "vulnerability found";
            findings.push({
              tool: "safety",
              line: 0,
              code: asStringOptional(vObj.vulnerability_id) ?? asString(vObj.CVE),
              message: `${name} — ${advisory}`,
              severity: "error",
            });
          }
        }
      }
    }
    return findings;
  } catch {
    return null;
  }
}

export function parsePyrightJson(stdout: string): Finding[] | null {
  try {
    const data = asObject(parseJson(stdout));
    const diagnostics = data.generalDiagnostics;
    if (!Array.isArray(diagnostics)) return null;
    return diagnostics.map((d: unknown): Finding => {
      const obj = asObject(d);
      const range = asObject(obj.range);
      const start = asObject(range.start);
      const startLine = typeof start.line === "number" ? start.line : -1;
      return {
        tool: "pyright",
        line: startLine + 1,
        code: asString(obj.rule),
        message: asString(obj.message),
        severity: asString(obj.severity) === "error" ? "error" : "warning",
      };
    });
  } catch {
    return null;
  }
}

export function parseSemgrepJson(stdout: string): Finding[] | null {
  try {
    const data = asObject(parseJson(stdout));
    const results = data.results;
    if (!Array.isArray(results)) return null;
    return results.map((r: unknown): Finding => {
      const obj = asObject(r);
      const start = asObject(obj.start);
      const extra = asObject(obj.extra);
      const severity = asString(extra.severity);
      return {
        tool: "semgrep",
        line: asNumber(start.line),
        code: asString(obj.check_id),
        message: asString(extra.message),
        severity:
          severity === "ERROR"
            ? "error"
            : severity === "WARNING"
              ? "warning"
              : "info",
      };
    });
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

export const PxcliQualityPlugin: Plugin = ({ client, $, directory }) => {
  /** Python files modified during this session, consumed by session-idle analysis. */
  const modifiedFiles = new Set<string>();

  /**
   * Per-tool availability flag.
   *   null  = not yet checked
   *   true  = available
   *   false = unavailable (logged once, skipped thereafter)
   */
  const toolOk: Record<string, boolean | null> = {
    ruff: null,
    radon: null,
    bandit: null,
    ty: null,
    safety: null,
    semgrep: null,
    pyright: null,
  };
  const toolErrors: Record<string, string> = {};

  function toolFailure(name: string, detail: string): Finding[] {
    return [{
      tool: name,
      line: 0,
      code: "TOOL_FAILURE",
      message: detail || "tool failed without diagnostic output",
      severity: "error",
    }];
  }

  function unavailable(name: string): Finding[] | null {
    return toolOk[name] === false
      ? toolFailure(name, toolErrors[name] ?? "tool is unavailable")
      : null;
  }

  /** Log a tool-unavailable warning once and mark it as unavailable. */
  async function markUnavailable(name: string, errMsg: string): Promise<void> {
    toolErrors[name] = errMsg;
    if (toolOk[name] !== false) {
      toolOk[name] = false;
      await client.app.log({
        body: {
          service: "pxcli-quality",
          level: "warn",
          message: `${name} failed; reporting a tool error. ${errMsg}`,
        },
      });
    }
  }

  async function checkedFindings(
    name: string,
    exitCode: number,
    stderr: string,
    parsed: Finding[] | null,
  ): Promise<Finding[]> {
    if (parsed !== null && (exitCode === 0 || parsed.length > 0)) {
      toolOk[name] = true;
      return parsed;
    }

    const detail = stderr.trim() || `exit code ${exitCode}; output could not be parsed`;
    await markUnavailable(name, detail);
    return toolFailure(name, detail);
  }

  // -----------------------------------------------------------------------
  // Per-file checks (run after every Python file write/edit)
  // -----------------------------------------------------------------------

  async function checkRuff(filePath: string): Promise<Finding[]> {
    const priorFailure = unavailable("ruff");
    if (priorFailure) return priorFailure;
    try {
      const r = await $`uv run ruff check ${filePath} --output-format=json --no-fix`
        .quiet()
        .nothrow();
      return await checkedFindings("ruff", r.exitCode, r.stderr.toString(), parseRuffJson(r.stdout.toString()));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      await markUnavailable("ruff", message);
      return toolFailure("ruff", message);
    }
  }

  async function checkRadon(filePath: string): Promise<Finding[]> {
    const priorFailure = unavailable("radon");
    if (priorFailure) return priorFailure;
    try {
      const r = await $`uv run radon cc ${filePath} -j`.quiet().nothrow();
      return await checkedFindings("radon", r.exitCode, r.stderr.toString(), parseRadonJson(r.stdout.toString()));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      await markUnavailable("radon", message);
      return toolFailure("radon", message);
    }
  }

  async function checkBandit(filePath: string): Promise<Finding[]> {
    const priorFailure = unavailable("bandit");
    if (priorFailure) return priorFailure;
    try {
      const r = await $`uv run bandit ${filePath} -f json -c pyproject.toml`
        .quiet()
        .nothrow();
      return await checkedFindings("bandit", r.exitCode, r.stderr.toString(), parseBanditJson(r.stdout.toString()));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      await markUnavailable("bandit", message);
      return toolFailure("bandit", message);
    }
  }

  async function checkTy(filePath: string): Promise<Finding[]> {
    const priorFailure = unavailable("ty");
    if (priorFailure) return priorFailure;
    try {
      const r = await $`uv run ty check ${filePath}`.quiet().nothrow();
      const combined = `${r.stdout.toString()}\n${r.stderr.toString()}`;
      return await checkedFindings("ty", r.exitCode, r.stderr.toString(), parseTyText(combined));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      await markUnavailable("ty", message);
      return toolFailure("ty", message);
    }
  }

  // -----------------------------------------------------------------------
  // Safety scan (run after pyproject.toml / requirements edits)
  // -----------------------------------------------------------------------

  async function checkSafety(): Promise<Finding[]> {
    const priorFailure = unavailable("safety");
    if (priorFailure) return priorFailure;
    try {
      const r = await $`uvx --from safety==3.8.1 safety scan --target ${directory} --output json`
        .quiet()
        .nothrow();
      return await checkedFindings("safety", r.exitCode, r.stderr.toString(), parseSafetyJson(r.stdout.toString()));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      await markUnavailable("safety", message);
      return toolFailure("safety", message);
    }
  }

  // -----------------------------------------------------------------------
  // Session-idle checks (semgrep + pyright across modified files)
  // -----------------------------------------------------------------------

  async function checkSemgrep(files: string[]): Promise<Finding[]> {
    if (files.length === 0) return [];
    const priorFailure = unavailable("semgrep");
    if (priorFailure) return priorFailure;
    try {
      const targets = files.join(" ");
      const r = await $`make semgrep-json SEMGREP_TARGETS=${targets}`
        .cwd(directory)
        .quiet()
        .nothrow();
      return await checkedFindings("semgrep", r.exitCode, r.stderr.toString(), parseSemgrepJson(r.stdout.toString()));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      await markUnavailable("semgrep", message);
      return toolFailure("semgrep", message);
    }
  }

  async function checkPyright(files: string[]): Promise<Finding[]> {
    if (files.length === 0) return [];
    const priorFailure = unavailable("pyright");
    if (priorFailure) return priorFailure;
    try {
      const r = await $`uv run pyright --outputjson ${files}`.quiet().nothrow();
      return await checkedFindings("pyright", r.exitCode, r.stderr.toString(), parsePyrightJson(r.stdout.toString()));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      await markUnavailable("pyright", message);
      return toolFailure("pyright", message);
    }
  }

  // -----------------------------------------------------------------------
  // Hook implementations
  // -----------------------------------------------------------------------

  /**
   * Run the applicable quality checks for a single touched file and append
   * any findings to the tool output so the LLM sees them immediately.
   */
  async function checkToolResult(
    filePath: string,
    output: { output: string },
  ): Promise<void> {
    // --- Python file quality checks ---
    if (isPythonFile(filePath) && !isSkippedFile(filePath)) {
      modifiedFiles.add(filePath);

      // Run all four tools in parallel
      const [ruffFindings, radonFindings, banditFindings, tyFindings] =
        await Promise.all([
          checkRuff(filePath),
          checkRadon(filePath),
          checkBandit(filePath),
          checkTy(filePath),
        ]);

      const allFindings = [
        ...ruffFindings,
        ...radonFindings,
        ...banditFindings,
        ...tyFindings,
      ];

      if (allFindings.length > 0) {
        output.output += formatFindings(allFindings);
      }
      return;
    }

    // --- Dependency file security check ---
    if (isDependencyFile(filePath)) {
      const findings = await checkSafety();
      if (findings.length > 0) {
        const lines = findings.map(
          (f) => `safety: ${f.code} — ${f.message}`,
        );
        const count = findings.length;
        output.output +=
          `\n\n--- Dependency Security Check ---\n` +
          `${lines.join("\n")}\n` +
          `(${count} vulnerabilit${count === 1 ? "y" : "ies"} found)`;
      }
    }
  }

  return Promise.resolve({
    /**
     * Inject coding conventions into the system prompt.
     */
    "experimental.chat.system.transform": (_input, output) => {
      output.system.push(CONVENTIONS_BLOCK);
      return Promise.resolve();
    },

    /**
     * After a file write/edit/apply_patch, run quality checks and append
     * findings to the tool output so the LLM sees them immediately.
     */
    "tool.execute.after": async (input, output) => {
      const args = input.args as Record<string, unknown> | undefined;

      // Edits applied through a patch must not bypass the checks.
      if (input.tool === "apply_patch") {
        const patchText = typeof args?.patchText === "string" ? args.patchText : "";
        const paths = getPatchFilePaths(patchText);
        if (paths.length > 0) {
          await Promise.all(paths.map((path) => checkToolResult(path, output)));
        }
        return;
      }

      if (input.tool !== "write" && input.tool !== "edit") return;

      const filePath = getFilePath(args);
      if (!filePath) return;
      await checkToolResult(filePath, output);
    },

    /**
     * On session idle, run semgrep + pyright on all modified files
     * and log the results.
     */
    event: async ({ event }) => {
      if (event.type !== "session.idle") return;
      if (modifiedFiles.size === 0) return;

      const files = [...modifiedFiles];
      modifiedFiles.clear();

      // Run both tools in parallel
      const [semgrepFindings, pyrightFindings] = await Promise.all([
        checkSemgrep(files),
        checkPyright(files),
      ]);

      const allFindings = [...semgrepFindings, ...pyrightFindings];

      if (allFindings.length > 0) {
        const toolNames = [...new Set(allFindings.map((f) => f.tool))];
        const summary = allFindings
          .map((f) => {
            const loc = f.line > 0 ? `L${f.line}` : "";
            return `  ${f.tool}: ${loc} ${f.code} — ${f.message}`;
          })
          .join("\n");

        await client.app.log({
          body: {
            service: "pxcli-quality",
            level: "warn",
            message:
              `Session idle analysis: ${allFindings.length} finding(s) from ` +
              `${toolNames.join(", ")} across ${files.length} modified file(s):\n${summary}`,
          },
        });
      } else {
        await client.app.log({
          body: {
            service: "pxcli-quality",
            level: "info",
            message: `Session idle analysis: all ${files.length} modified file(s) pass semgrep + pyright.`,
          },
        });
      }
    },
  });
};
