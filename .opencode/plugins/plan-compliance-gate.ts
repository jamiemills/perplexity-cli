/**
 * plan-compliance-gate -- OpenCode plugin for quality plan enforcement.
 *
 * Intercepts `git commit` commands and delegates validation of the exact
 * canonical quality plan to the project's canonical Make target. Every commit
 * attempt is revalidated. If no canonical plan exists, commits are allowed.
 */

import type { Plugin } from "@opencode-ai/plugin";
import { existsSync } from "node:fs";
import { join } from "node:path";

const GIT_COMMIT_RE = /(?:^|[\s;&|])["']?(?:[^\s;&|"'`]*\/)?git["']?(?:\s+(?!commit(?:\s|$))[^\s;&|]+)*\s+commit(?:\s|$)/;
const COMMIT_WORD_RE = /(?:^|[^\w-])commit(?:$|[^\w-])/;
const PLAN_RELATIVE_PATH = ".claude/plans/quality-plan.md";

export function isGitCommit(command: string): boolean {
  const normalised = command.replace(/\\(?=[A-Za-z])/g, "");
  return GIT_COMMIT_RE.test(normalised) || COMMIT_WORD_RE.test(normalised);
}

const PLAN_BLOCK_MESSAGE = `Commit blocked: the canonical quality plan validation failed.

Invoke @quality-plan-reviewer manually to analyse the failures and suggest fixes.

To resolve manually:
  1. Read '.claude/plans/quality-plan.md'.
  2. Address any [FAIL] items in the plan's Fix Plan section.
  3. Verify with 'make plan-check PLAN=.claude/plans/quality-plan.md'.
  4. Retry the commit after validation passes.`;

export const PlanComplianceGatePlugin: Plugin = async ({ client, $, directory }) => {
  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "bash") return;

      const command: string = output.args.command ?? "";
      if (!isGitCommit(command)) return;

      const planPath = join(directory, PLAN_RELATIVE_PATH);
      if (!existsSync(planPath)) {
        await client.app.log({
          body: {
            service: "plan-compliance-gate",
            level: "debug",
            message: "No canonical quality plan found; allowing commit.",
          },
        });
        return;
      }

      const result = await $`make plan-check PLAN=.claude/plans/quality-plan.md`
        .cwd(directory)
        .quiet()
        .nothrow();
      if (result.exitCode === 0) {
        await client.app.log({
          body: {
            service: "plan-compliance-gate",
            level: "info",
            message: "Canonical quality plan validation passed; allowing commit.",
          },
        });
        return;
      }

      const detail = result.stderr.toString().trim() || result.stdout.toString().trim();
      await client.app.log({
        body: {
          service: "plan-compliance-gate",
          level: "warn",
          message: `Canonical quality plan validation failed${detail ? `: ${detail}` : ""}`,
        },
      });
      throw new Error(PLAN_BLOCK_MESSAGE);
    },
  };
};
