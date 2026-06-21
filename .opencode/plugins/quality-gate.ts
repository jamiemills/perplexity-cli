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

import type { Plugin } from "@opencode-ai/plugin";

// ---------------------------------------------------------------------------
// Protected files
// ---------------------------------------------------------------------------

const PROTECTED_DIRS = ["scripts/", "Makefile"];

function isProtectedFile(filePath: string): boolean {
  if (!filePath) return false;
  return PROTECTED_DIRS.some(
    (p) => filePath === p || filePath.endsWith(`/${p}`) || filePath.includes(`/${p}/`),
  );
}

// ---------------------------------------------------------------------------
// Bypass detection
// ---------------------------------------------------------------------------

const BYPASS_PATTERNS: { re: RegExp; label: string }[] = [
  { re: /--exclude\b/,              label: "--exclude" },
  { re: /--exclude-rule\b/,          label: "--exclude-rule" },
  { re: /#\s*nosec\b/i,              label: "# nosec" },
  { re: /#\s*pragma:\s*no\s*cover/i, label: "# pragma: no cover" },
  { re: /#\s*type:\s*ignore/i,       label: "# type: ignore" },
];

const GATE_REFERENCES = [
  "--max-flagged",
  "--min-coverage",
  "--min-confidence",
  "fail_under",
  "-n ",
];

function countMatches(text: string, re: RegExp): number {
  return (text.match(new RegExp(re.source, "g")) || []).length;
}

function isAddingBypass(oldStr: string, newStr: string): string | null {
  for (const { re, label } of BYPASS_PATTERNS) {
    if (countMatches(newStr, re) > countMatches(oldStr, re)) {
      return `added ${label} bypass`;
    }
  }

  const oldSev = oldStr.match(/--severity\s+(\w+)/g) || [];
  const newSev = newStr.match(/--severity\s+(\w+)/g) || [];
  if (oldSev.length > newSev.length) {
    return "removed severity level(s) from --severity flag";
  }

  for (const gate of GATE_REFERENCES) {
    if (oldStr.includes(gate) && !newStr.includes(gate)) {
      return `removed ${gate.trim()} gate reference`;
    }
  }

  return null;
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
  $: any,
  filePath: string,
): Promise<string> {
  try {
    const r = await $`cat ${filePath}`.quiet().nothrow();
    return r.stdout?.toString() ?? "";
  } catch {
    return "";
  }
}

// ---------------------------------------------------------------------------
// Post-turn helpers
// ---------------------------------------------------------------------------

async function getModifiedProtected(
  $: any,
  directory: string,
): Promise<string[]> {
  try {
    const r = await $`git diff --name-only -- scripts/ Makefile`
      .cwd(directory)
      .quiet()
      .nothrow();

    const stdout = r.stdout?.toString() ?? "";
    return stdout
      .split("\n")
      .map((l: string) => l.trim())
      .filter(Boolean);
  } catch {
    return [];
  }
}

async function verifyGateIntact(
  $: any,
  directory: string,
): Promise<string | null> {
  try {
    const r = await $`make coupling-check`
      .cwd(directory)
      .quiet()
      .nothrow();

    if (r.exitCode === 0) {
      return "coupling-check PASSED — the coupling budget gate may have been bypassed.";
    }
  } catch {
    // coupling-check failing is the expected healthy state
  }
  return null;
}

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

export const QualityGatePlugin: Plugin = async ({ client, $, directory }) => {
  return {
    // --- Pre-turn ---

    "tool.execute.before": async (input, output) => {
      // --- write: read current content, compare with new, check for bypasses ---
      if (input.tool === "write") {
        const filePath: string = input.args.filePath ?? "";
        if (!isProtectedFile(filePath)) return;

        const newContent: string = input.args.content ?? "";
        if (!newContent) return;

        const oldContent = await readCurrentContent($, filePath);
        const reason = isAddingBypass(oldContent, newContent);
        if (!reason) return;

        await client.app.log({
          body: {
            service: "quality-gate",
            level: "warn",
            message: `Blocked write to ${filePath}: ${reason}`,
          },
        });
        throw new Error(blockMessage(reason));
      }

      // --- edit: semantic bypass detection ---
      if (input.tool === "edit") {
        const filePath: string = input.args.filePath ?? "";
        if (!isProtectedFile(filePath)) return;

        const oldStr: string = input.args.oldString ?? "";
        const newStr: string = input.args.newString ?? "";
        if (!oldStr && !newStr) return;

        const reason = isAddingBypass(oldStr, newStr);
        if (!reason) return;

        await client.app.log({
          body: {
            service: "quality-gate",
            level: "warn",
            message: `Blocked edit to ${filePath}: ${reason}`,
          },
        });
        throw new Error(blockMessage(reason));
      }
    },

    // --- Post-turn ---

    event: async ({ event }) => {
      if (event.type !== "session.idle") return;

      const modified = await getModifiedProtected($, directory);
      const gateWarning = await verifyGateIntact($, directory);

      if (modified.length === 0 && gateWarning === null) return;

      const lines: string[] = [];
      if (modified.length > 0) {
        lines.push("Protected files modified this turn:");
        modified.forEach((f: string) => lines.push(`  - ${f}`));
      }
      if (gateWarning !== null) {
        lines.push(`\n${gateWarning}`);
      }
      lines.push(
        "\nIf any gate was unintentionally loosened, revert the changes.",
        "If the changes are approved, commit them and verify all gates.",
      );

      await client.app.log({
        body: {
          service: "quality-gate",
          level: "warn",
          message: lines.join("\n"),
        },
      });
    },
  };
};
