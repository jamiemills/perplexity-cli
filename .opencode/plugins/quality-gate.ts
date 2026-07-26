/**
 * quality-gate — OpenCode plugin for the perplexity-cli project.
 *
 * Numeric thresholds and check toggles are locked in quality/gates.conf
 * (denied to agents via opencode.jsonc).  Agents have full edit rights
 * to scripts/ and Makefile; this plugin enforces that changes cannot
 * loosen checks:
 *
 *   Pre-turn  — blocks edits/writes that add bypass patterns, remove
 *               gate references, or drop severity levels.
 *   Post-turn — flags any uncommitted changes to protected files and
 *               verifies the coupling gate is still intact.
 *
 * Human override: set OPENCODE_DISABLE_QUALITY_GATE=1.
 */

import type { Plugin, PluginInput } from "@opencode-ai/plugin";
import { readFile } from "node:fs/promises";
import { isAbsolute, resolve } from "node:path";

type BunShell = PluginInput["$"];

// ---------------------------------------------------------------------------
// Protected files
// ---------------------------------------------------------------------------

export const PROTECTED_DIRS = ["scripts/", "Makefile"];

export function isProtectedFile(filePath: string): boolean {
  const normalised = filePath.replace(/\\/g, "/").replace(/^\.\//, "");
  return PROTECTED_DIRS.some((path) =>
    path.endsWith("/")
      ? normalised.startsWith(path) || normalised.includes(`/${path}`)
      : normalised === path || normalised.endsWith(`/${path}`),
  );
}

// ---------------------------------------------------------------------------
// Bypass detection
// ---------------------------------------------------------------------------

export const BYPASS_PATTERNS: readonly { re: RegExp; label: string }[] = [
  { re: /--exclude(?!-)\b/,          label: "--exclude" },
  { re: /--exclude-rule\b/,          label: "--exclude-rule" },
  { re: /#\s*nosec\b/i,              label: "# nosec" },
  { re: /#\s*pragma:\s*no\s*cover/i, label: "# pragma: no cover" },
  { re: /#\s*type:\s*ignore/i,       label: "# type: ignore" },
];

export const GATE_REFERENCES: readonly { re: RegExp; label: string }[] = [
  { re: /--max-flagged\b/, label: "--max-flagged" },
  { re: /--min-coverage\b/, label: "--min-coverage" },
  { re: /--min-confidence\b/, label: "--min-confidence" },
  { re: /\bfail_under\b/, label: "fail_under" },
  { re: /\bradon\s+(?:cc|mi)[^\n]*\s-n(?:\s|$)/, label: "radon -n" },
  { re: /\$\(MIN_COVERAGE\)/, label: "MIN_COVERAGE locked threshold" },
  { re: /\$\(MIN_CONFIDENCE\)/, label: "MIN_CONFIDENCE locked threshold" },
  { re: /\$\(MAX_FLAGGED\)/, label: "MAX_FLAGGED locked threshold" },
  { re: /\$\(SEMGREP_SEVERITY\)/, label: "SEMGREP_SEVERITY locked threshold" },
];

export function countMatches(text: string, re: RegExp): number {
  return (text.match(new RegExp(re.source, re.flags.replace("g", "") + "g")) ?? []).length;
}

export function isAddingBypass(oldStr: string, newStr: string): string | null {
  for (const { re, label } of BYPASS_PATTERNS) {
    const additions = newStr
      .split("\n")
      .filter((line) => re.test(line) && !isJustifiedSuppression(line, label));
    const removals = oldStr
      .split("\n")
      .filter((line) => re.test(line) && !isJustifiedSuppression(line, label));
    if (additions.length > removals.length) {
      return `added ${label} bypass`;
    }
  }

  const oldSev = oldStr.match(/--severity\s+(\w+)/g) ?? [];
  const newSev = newStr.match(/--severity\s+(\w+)/g) ?? [];
  if (oldSev.length > newSev.length) {
    return "removed severity level(s) from --severity flag";
  }

  for (const gate of GATE_REFERENCES) {
    if (countMatches(oldStr, gate.re) > countMatches(newStr, gate.re)) {
      return `removed ${gate.label} gate reference`;
    }
  }

  return null;
}

export function isJustifiedSuppression(line: string, label: string): boolean {
  if (label === "# nosec") {
    return /#\s*nosec\s+[A-Z]\d{3}\s+(?:-|\u2014|:)\s*\S/i.test(line);
  }
  if (label === "# pragma: no cover") {
    return /#\s*pragma:\s*no\s*cover\s+(?:-|\u2014|:)\s*\S/i.test(line);
  }
  if (label === "# type: ignore") {
    return /#\s*type:\s*ignore\[[^\]]+\]\s+(?:-|\u2014|:)\s*\S/i.test(line);
  }
  return false;
}

export interface PatchChange {
  added: string[];
  removed: string[];
}

export function protectedPatchChanges(patchText: string): Map<string, PatchChange> {
  const changes = new Map<string, PatchChange>();
  let current: PatchChange | null = null;

  for (const line of patchText.split("\n")) {
    const fileMatch = /^\*\*\* (?:Add|Update|Delete) File: (.+)$/.exec(line);
    if (fileMatch) {
      const filePath = (fileMatch[1] ?? "").trim();
      current = isProtectedFile(filePath) ? { added: [], removed: [] } : null;
      if (current) changes.set(filePath, current);
      continue;
    }
    if (line.startsWith("*** ")) {
      current = null;
      continue;
    }
    if (current && line.startsWith("+") && !line.startsWith("+++")) {
      current.added.push(line.slice(1));
    } else if (current && line.startsWith("-") && !line.startsWith("---")) {
      current.removed.push(line.slice(1));
    }
  }
  return changes;
}

// ---------------------------------------------------------------------------
// Message templates
// ---------------------------------------------------------------------------

function blockMessage(reason: string): string {
  return `This change was blocked by the quality-gate plugin.

Reason: ${reason}

Quality infrastructure (scripts/ and Makefile) can only be tightened.
Adding bypass rules, # nosec comments, or removing gate references
is blocked.  To relax a numeric threshold, edit quality/gates.conf
(human-only, locked via opencode.jsonc).

To override this block: set OPENCODE_DISABLE_QUALITY_GATE=1.`;
}

// ---------------------------------------------------------------------------
// File reader for write-tool comparison
// ---------------------------------------------------------------------------

async function readCurrentContent(
  directory: string,
  filePath: string,
): Promise<string> {
  try {
    const resolvedPath = isAbsolute(filePath) ? filePath : resolve(directory, filePath);
    return await readFile(resolvedPath, "utf8");
  } catch (error: unknown) {
    if (typeof error === "object" && error !== null && "code" in error && (error as NodeJS.ErrnoException).code === "ENOENT") {
      return "";
    }
    throw error;
  }
}

// ---------------------------------------------------------------------------
// Post-turn helpers
// ---------------------------------------------------------------------------

async function getModifiedProtected(
  $: BunShell,
  directory: string,
): Promise<string[]> {
  try {
    const r = await $`git status --porcelain -- scripts/ Makefile`
      .cwd(directory)
      .quiet()
      .nothrow();

    if (r.exitCode !== 0) return [];
    const stdout = r.stdout.toString();
    return stdout
      .split("\n")
      .map((line: string) => line.slice(3).split(" -> ").at(-1)?.trim() ?? "")
      .filter(Boolean);
  } catch {
    return [];
  }
}

async function verifyGateIntact(
  $: BunShell,
  directory: string,
): Promise<string | null> {
  try {
    const r = await $`make coupling-check`
      .cwd(directory)
      .quiet()
      .nothrow();

    if (r.exitCode === 0) return null;
    const detail = r.stderr.toString().trim() || r.stdout.toString().trim();
    return `coupling-check FAILED${detail ? `: ${detail}` : ""}`;
  } catch (error: unknown) {
    return `coupling-check could not run: ${String(error)}`;
  }
}

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Tool argument helpers
// ---------------------------------------------------------------------------

type ToolArgs = Record<string, unknown>;

function argString(args: ToolArgs, key: string): string {
  return typeof args[key] === "string" ? args[key] : "";
}

function argStringOrElse(args: ToolArgs, primary: string, fallback: string): string {
  return argString(args, primary) || argString(args, fallback);
}

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

export const QualityGatePlugin: Plugin = ({ client, $, directory }) => {
  if (process.env.OPENCODE_DISABLE_QUALITY_GATE === "1") {
    return Promise.resolve({});
  }

  async function block(filePath: string, reason: string): Promise<never> {
    await client.app.log({
      body: {
        service: "quality-gate",
        level: "warn",
        message: `Blocked change to ${filePath}: ${reason}`,
      },
    });
    throw new Error(blockMessage(reason));
  }

  return Promise.resolve({
    // --- Pre-turn ---

    "tool.execute.before": async (input, output) => {
      const args = output.args as ToolArgs;

      // --- write: read current content, compare with new, check for bypasses ---
      if (input.tool === "write") {
        const filePath = argString(args, "filePath");
        if (!isProtectedFile(filePath)) return;

        const newContent = argString(args, "content");
        if (!newContent) return;

        const oldContent = await readCurrentContent(directory, filePath);
        const reason = isAddingBypass(oldContent, newContent);
        if (!reason) return;

        await block(filePath, reason);
      }

      // --- edit: semantic bypass detection ---
      if (input.tool === "edit") {
        const filePath = argString(args, "filePath");
        if (!isProtectedFile(filePath)) return;

        const oldStr = argString(args, "oldString");
        const newStr = argString(args, "newString");
        if (!oldStr && !newStr) return;

        const reason = isAddingBypass(oldStr, newStr);
        if (!reason) return;

        await block(filePath, reason);
      }

      if (input.tool === "apply_patch") {
        const patchText = argStringOrElse(args, "patchText", "patch");
        for (const [filePath, change] of protectedPatchChanges(patchText)) {
          const reason = isAddingBypass(change.removed.join("\n"), change.added.join("\n"));
          if (reason) await block(filePath, reason);
        }
      }
    },

    // --- Post-turn ---

    event: async ({ event }) => {
      if (event.type !== "session.idle") return;

      const modified = await getModifiedProtected($, directory);
      if (modified.length === 0) return;
      const gateWarning = await verifyGateIntact($, directory);

      const lines: string[] = [];
      if (modified.length > 0) {
        lines.push("Protected files modified this turn:");
        modified.forEach((f: string) => lines.push(`  - ${f}`));
      }
      if (gateWarning !== null) {
        lines.push(`\n${gateWarning}`);
      } else {
        lines.push("\ncoupling-check passed.");
      }
      lines.push(
        "\nIf any gate was unintentionally loosened, revert the changes.",
        "If the changes are approved, commit them and verify all gates.",
      );

      await client.app.log({
        body: {
          service: "quality-gate",
          level: gateWarning === null ? "info" : "warn",
          message: lines.join("\n"),
        },
      });
    },
  });
};
