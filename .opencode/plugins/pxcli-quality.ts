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

interface Finding {
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

// Semgrep is installed outside the project venv
const SEMGREP_BIN = "/Users/jamie.mills/.local/bin/semgrep";

// ---------------------------------------------------------------------------
// File classification helpers
// ---------------------------------------------------------------------------

function isPythonFile(filePath: string): boolean {
  return filePath.endsWith(".py");
}

function isSkippedFile(filePath: string): boolean {
  return SKIPPED_PATHS.some((pattern) => filePath.includes(pattern));
}

function isDependencyFile(filePath: string): boolean {
  return DEPENDENCY_FILES.some((name) => filePath.endsWith(name));
}

function getFilePath(args: any): string | null {
  if (!args) return null;
  return args.filePath ?? args.file_path ?? args.path ?? null;
}

// ---------------------------------------------------------------------------
// Output formatting
// ---------------------------------------------------------------------------

function formatFindings(findings: Finding[]): string {
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

function parseRuffJson(stdout: string): Finding[] {
  try {
    const items = JSON.parse(stdout);
    if (!Array.isArray(items)) return [];
    return items.map((item: any) => ({
      tool: "ruff",
      line: item.location?.row ?? 0,
      code: item.code ?? "",
      message: item.message ?? "",
      severity: "warning" as const,
    }));
  } catch {
    return [];
  }
}

function parseRadonJson(stdout: string): Finding[] {
  try {
    const data = JSON.parse(stdout);
    const findings: Finding[] = [];
    for (const blocks of Object.values(data)) {
      if (!Array.isArray(blocks)) continue;
      for (const block of blocks as any[]) {
        if (block.rank && block.rank !== "A") {
          findings.push({
            tool: "radon",
            line: block.lineno ?? 0,
            code: `CC=${block.complexity}`,
            message: `${block.type} '${block.name}' ${block.rank}-grade (complexity ${block.complexity}, target <=5)`,
            severity: "warning",
          });
        }
      }
    }
    return findings;
  } catch {
    return [];
  }
}

function parseBanditJson(stdout: string): Finding[] {
  try {
    const data = JSON.parse(stdout);
    const results = data.results;
    if (!Array.isArray(results)) return [];
    return results.map((r: any) => ({
      tool: "bandit",
      line: r.line_number ?? 0,
      code: `${r.test_id ?? ""} (${r.issue_severity ?? "?"})`,
      message: r.issue_text ?? "",
      severity: r.issue_severity === "HIGH" ? ("error" as const) : ("warning" as const),
    }));
  } catch {
    return [];
  }
}

function parseTyText(stdout: string): Finding[] {
  const findings: Finding[] = [];
  const diagnosticRe = /^(error|warning)\[([^\]]+)]:\s*(.+)/;
  const locationRe = /^\s*-->\s*.*?:(\d+):(\d+)/;

  const lines = stdout.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const match = diagnosticRe.exec(lines[i]);
    if (!match) continue;

    const severity = match[1] === "error" ? ("error" as const) : ("warning" as const);
    const code = match[2];
    const message = match[3];
    let line = 0;

    if (i + 1 < lines.length) {
      const locMatch = locationRe.exec(lines[i + 1]);
      if (locMatch) {
        line = parseInt(locMatch[1], 10);
      }
    }

    findings.push({ tool: "ty", line, code, message, severity });
  }
  return findings;
}

function parseSafetyJson(stdout: string): Finding[] {
  try {
    const data = JSON.parse(stdout);
    const findings: Finding[] = [];
    const projects = data.scan_results?.projects ?? [];
    for (const project of projects) {
      for (const file of project.files ?? []) {
        for (const dep of file.results?.dependencies ?? []) {
          for (const v of dep.known_vulnerabilities ?? []) {
            findings.push({
              tool: "safety",
              line: 0,
              code: v.vulnerability_id ?? v.CVE ?? "",
              message: `${dep.name} — ${v.advisory ?? v.vulnerability_id ?? "vulnerability found"}`,
              severity: "error",
            });
          }
        }
      }
    }
    return findings;
  } catch {
    return [];
  }
}

function parsePyrightJson(stdout: string): Finding[] {
  try {
    const data = JSON.parse(stdout);
    const diagnostics = data.generalDiagnostics ?? [];
    return diagnostics.map((d: any) => ({
      tool: "pyright",
      line: (d.range?.start?.line ?? -1) + 1,
      code: d.rule ?? "",
      message: d.message ?? "",
      severity: d.severity === "error" ? ("error" as const) : ("warning" as const),
    }));
  } catch {
    return [];
  }
}

function parseSemgrepJson(stdout: string): Finding[] {
  try {
    const data = JSON.parse(stdout);
    return (data.results ?? []).map((r: any) => ({
      tool: "semgrep",
      line: r.start?.line ?? 0,
      code: r.check_id ?? "",
      message: r.extra?.message ?? "",
      severity:
        r.extra?.severity === "ERROR"
          ? ("error" as const)
          : r.extra?.severity === "WARNING"
            ? ("warning" as const)
            : ("info" as const),
    }));
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

export const PxcliQualityPlugin: Plugin = async ({ client, $, directory }) => {
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

  /** Log a tool-unavailable warning once and mark it as unavailable. */
  async function markUnavailable(name: string, errMsg: string): Promise<void> {
    if (toolOk[name] !== false) {
      toolOk[name] = false;
      await client.app.log({
        body: {
          service: "pxcli-quality",
          level: "warn",
          message: `${name} not available — skipping. ${errMsg}`,
        },
      });
    }
  }

  // -----------------------------------------------------------------------
  // Per-file checks (run after every Python file write/edit)
  // -----------------------------------------------------------------------

  async function checkRuff(filePath: string): Promise<Finding[]> {
    if (toolOk["ruff"] === false) return [];
    try {
      const r = await $`uv run ruff check ${filePath} --output-format=json --no-fix`
        .quiet()
        .nothrow();
      toolOk["ruff"] = true;
      return parseRuffJson(r.stdout.toString());
    } catch (err: any) {
      await markUnavailable("ruff", err.message ?? "");
      return [];
    }
  }

  async function checkRadon(filePath: string): Promise<Finding[]> {
    if (toolOk["radon"] === false) return [];
    try {
      const r = await $`uv run radon cc ${filePath} -j`.quiet().nothrow();
      toolOk["radon"] = true;
      return parseRadonJson(r.stdout.toString());
    } catch (err: any) {
      await markUnavailable("radon", err.message ?? "");
      return [];
    }
  }

  async function checkBandit(filePath: string): Promise<Finding[]> {
    if (toolOk["bandit"] === false) return [];
    try {
      const r = await $`uv run bandit ${filePath} -f json -c pyproject.toml`
        .quiet()
        .nothrow();
      toolOk["bandit"] = true;
      return parseBanditJson(r.stdout.toString());
    } catch (err: any) {
      await markUnavailable("bandit", err.message ?? "");
      return [];
    }
  }

  async function checkTy(filePath: string): Promise<Finding[]> {
    if (toolOk["ty"] === false) return [];
    try {
      const r = await $`uv run ty check ${filePath}`.quiet().nothrow();
      toolOk["ty"] = true;
      return parseTyText(r.stdout.toString());
    } catch (err: any) {
      await markUnavailable("ty", err.message ?? "");
      return [];
    }
  }

  // -----------------------------------------------------------------------
  // Safety scan (run after pyproject.toml / requirements edits)
  // -----------------------------------------------------------------------

  async function checkSafety(): Promise<Finding[]> {
    if (toolOk["safety"] === false) return [];
    try {
      const r = await $`uvx safety scan --target ${directory} --output json`
        .quiet()
        .nothrow();
      toolOk["safety"] = true;
      return parseSafetyJson(r.stdout.toString());
    } catch (err: any) {
      await markUnavailable("safety", err.message ?? "");
      return [];
    }
  }

  // -----------------------------------------------------------------------
  // Session-idle checks (semgrep + pyright across modified files)
  // -----------------------------------------------------------------------

  async function checkSemgrep(files: string[]): Promise<Finding[]> {
    if (toolOk["semgrep"] === false || files.length === 0) return [];
    try {
      const configPath = `${directory}/.semgrep.yml`;
      const r = await $`${SEMGREP_BIN} --config ${configPath} ${files} --json --severity ERROR --severity WARNING`
        .quiet()
        .nothrow();
      toolOk["semgrep"] = true;
      return parseSemgrepJson(r.stdout.toString());
    } catch (err: any) {
      await markUnavailable("semgrep", err.message ?? "");
      return [];
    }
  }

  async function checkPyright(files: string[]): Promise<Finding[]> {
    if (toolOk["pyright"] === false || files.length === 0) return [];
    try {
      const r = await $`uv run pyright --outputjson ${files}`.quiet().nothrow();
      toolOk["pyright"] = true;
      return parsePyrightJson(r.stdout.toString());
    } catch (err: any) {
      await markUnavailable("pyright", err.message ?? "");
      return [];
    }
  }

  // -----------------------------------------------------------------------
  // Hook implementations
  // -----------------------------------------------------------------------

  return {
    /**
     * Inject coding conventions into the system prompt.
     */
    "experimental.chat.system.transform": async (_input, output) => {
      output.system.push(CONVENTIONS_BLOCK);
    },

    /**
     * After a file write/edit, run quality checks and append findings
     * to the tool output so the LLM sees them immediately.
     */
    "tool.execute.after": async (input, output) => {
      if (input.tool !== "write" && input.tool !== "edit") return;

      const filePath = getFilePath(input.args);
      if (!filePath) return;

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
  };
};
