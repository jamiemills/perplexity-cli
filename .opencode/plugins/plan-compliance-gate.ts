/**
 * plan-compliance-gate — OpenCode plugin for the perplexity-cli project.
 *
 * Complements pre-push-docs-check.ts by guarding `git commit` with the
 * Analyzer Compliance Review defined in .claude/analyzer-prevention-plan.md
 * section 14.
 *
 * On the first `git commit` of a cycle it reads the most recently written
 * plan under .claude/plans/.  If that plan's Analyzer Compliance Review or
 * Generated Plan Self-Review is `Result: FAIL`, the commit is blocked and the
 * author is directed to the quality-plan-reviewer subagent.  Otherwise a
 * reminder is shown and the retry passes through.
 */

import type { Plugin } from "@opencode-ai/plugin";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const GIT_COMMIT_RE = /\bgit\s+commit\b/;

function isGitCommit(command: string): boolean {
  return GIT_COMMIT_RE.test(command);
}

interface PlanStatus {
  path: string;
  failed: boolean;
}

function newestPlanStatus(plansDir: string): PlanStatus | null {
  let entries: string[];
  try {
    entries = readdirSync(plansDir).filter((n) => n.endsWith(".md"));
  } catch {
    return null;
  }
  let newest: PlanStatus | null = null;
  let newestMtime = 0;
  for (const name of entries) {
    const fullPath = join(plansDir, name);
    const mtime = statSync(fullPath).mtimeMs;
    if (mtime <= newestMtime) continue;
    const text = readFileSync(fullPath, "utf8");
    const failed = /Result:\s*FAIL/i.test(text);
    newest = { path: fullPath, failed };
    newestMtime = mtime;
  }
  return newest;
}

// ---------------------------------------------------------------------------
// Reminder message
// ---------------------------------------------------------------------------

const REMINDER = `Before committing, confirm plan compliance.

If a plan is in play, it must show:
  - Analyzer Compliance Review: Result PASS
  - Generated Plan Self-Review:   Result PASS

A failing plan must be re-reviewed by the quality-plan-reviewer subagent
before implementation proceeds. If no plan applies to these changes, retry
the commit to continue.`;

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

export const PlanComplianceGatePlugin: Plugin = async ({ client }) => {
  let commitPending = false;

  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "bash") return;

      const command: string = output.args.command ?? "";
      if (!isGitCommit(command)) return;

      if (commitPending) {
        commitPending = false;
        await client.app.log({
          body: {
            service: "plan-compliance-gate",
            level: "info",
            message: "Plan compliance acknowledged; allowing git commit.",
          },
        });
        return;
      }

      commitPending = true;
      const status = newestPlanStatus(".claude/plans");
      const level = status?.failed ? "warn" : "info";
      const message = status?.failed
        ? `Latest plan ${status.path} has Result: FAIL — resolve via the quality-plan-reviewer subagent before committing.`
        : "No failing plan detected — confirm compliance if a plan applies.";

      await client.app.log({ body: { service: "plan-compliance-gate", level, message } });
      throw new Error(`${message}\n\n${REMINDER}`);
    },
  };
};
