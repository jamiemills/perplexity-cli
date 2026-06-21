/**
 * plan-compliance-gate -- OpenCode plugin for quality plan enforcement.
 *
 * Intercepts `git commit` commands and blocks them when the latest
 * quality plan under `.claude/plans/` reports `Result: FAIL` in its
 * Analyzer Compliance Review section.
 *
 * On the first commit attempt, the plugin reads the plan file, checks
 * for compliance, and blocks with a message.  The agent is expected to
 * address the failures (or run the quality-plan-reviewer subagent) and
 * retry the commit, which passes through unblocked.
 *
 * If no plan file exists, commits are allowed through (no plan = no
 * compliance check required).
 */

import type { Plugin } from "@opencode-ai/plugin";
import { readFileSync, existsSync } from "fs";
import { join } from "path";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const GIT_COMMIT_RE = /git\s+commit/;

function isGitCommit(command: string): boolean {
  return GIT_COMMIT_RE.test(command);
}

function readPlan(directory: string): string | null {
  const planPath = join(directory, ".claude", "plans", "quality-plan.md");
  try {
    if (!existsSync(planPath)) return null;
    return readFileSync(planPath, "utf-8");
  } catch {
    return null;
  }
}

function planIsFailing(text: string): boolean {
  // Extract the Analyzer Compliance Review section
  const reviewStart = text.indexOf("## Analyzer Compliance Review");
  if (reviewStart < 0) return false;

  const nextSection = text.indexOf("\n## ", reviewStart + 5);
  const review = nextSection > 0
    ? text.slice(reviewStart, nextSection)
    : text.slice(reviewStart);

  // Check for FAIL markers in the review section
  const hasFail = review.includes("[FAIL]");
  const resultFail =
    review.includes("Result: FAIL") ||
    review.includes("- Result: FAIL");

  return hasFail || resultFail;
}

// ---------------------------------------------------------------------------
// Block message
// ---------------------------------------------------------------------------

const PLAN_BLOCK_MESSAGE = `Commit blocked: the quality plan reports failures.

The latest quality plan under .claude/plans/ reports Result: FAIL or
contains [FAIL] items in the Analyzer Compliance Review.  A build phase
must not consume this plan until all categories pass.

To resolve:
  1. Run 'make quality-plan' to regenerate the plan with current data.
  2. Address any [FAIL] items in the plan's Fix Plan section.
  3. Verify with 'make plan-check'.
  4. Invoke the quality-plan-reviewer subagent to validate.
  5. Retry the commit once the plan reports Result: PASS.

If the failures are pre-existing and intentional (remediation plan),
update the plan's Analyzer Compliance Review to reflect current state
before retrying.`;

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

export const PlanComplianceGatePlugin: Plugin = async ({ client, directory }) => {
  let commitBlocked = false;

  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "bash") return;

      const command: string = output.args.command ?? "";
      if (!isGitCommit(command)) return;

      if (commitBlocked) {
        // Already reminded; allow retry.
        commitBlocked = false;

        await client.app.log({
          body: {
            service: "plan-compliance-gate",
            level: "info",
            message: "Plan compliance check passed (retry allowed).",
          },
        });
        return;
      }

      const plan = readPlan(directory);
      if (plan === null) {
        // No plan file exists — nothing to check.
        await client.app.log({
          body: {
            service: "plan-compliance-gate",
            level: "debug",
            message: "No quality plan found; allowing commit.",
          },
        });
        return;
      }

      if (!planIsFailing(plan)) {
        // Plan exists and passes.
        await client.app.log({
          body: {
            service: "plan-compliance-gate",
            level: "info",
            message: "Quality plan compliance: PASS. Allowing commit.",
          },
        });
        return;
      }

      // Plan is failing — block the commit.
      commitBlocked = true;

      await client.app.log({
        body: {
          service: "plan-compliance-gate",
          level: "warn",
          message: "Intercepted git commit; quality plan reports FAIL.",
        },
      });

      throw new Error(PLAN_BLOCK_MESSAGE);
    },
  };
};
