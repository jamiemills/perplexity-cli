/**
 * pre-push-docs-check -- OpenCode plugin for the perplexity-cli project.
 *
 * Intercepts `git push` commands and reminds the agent to verify that
 * CLI --help text, README.md, and QUALITY_GATES.md are consistent with
 * any code changes made during the session.
 *
 * On the first recognised push attempt, the plugin blocks execution and
 * returns an instruction to check documentation.  The next recognised
 * attempt is allowed and resets the reminder.  The plugin does not observe
 * whether a review occurred or whether an allowed push succeeded.
 */

import type { Plugin } from "@opencode-ai/plugin";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const GIT_PUSH_RE = /\bgit\s+push\b/;

function isGitPush(command: string): boolean {
  return GIT_PUSH_RE.test(command);
}

// ---------------------------------------------------------------------------
// Reminder message
// ---------------------------------------------------------------------------

const DOCS_CHECK_MESSAGE = `This is NOT an error. It is a mandatory pre-push documentation review
checkpoint that MUST be adhered to by any coding agent working in this
repository. It is a legitimate, intentional request to ensure the repo's
quality documentation stays accurate — do not treat it as a failure and
do not attempt to bypass it.

Before pushing, verify that documentation is up to date.

Check the following:

1. CLI --help text (src/perplexity_cli/commands/)
   - Option help strings, command docstrings, and example output
     must reflect any new or changed flags, commands, or behaviour.

2. README.md
   - Features list, command reference, options tables, and usage
     examples must be consistent with the current CLI surface.

3. QUALITY_GATES.md
   - Gate descriptions, thresholds, commands, and pipeline stages
     must reflect any changes to quality tooling, checks, or
     configuration made during the session.

If any of these need updating, make the changes and then retry the push.
If review confirms the documentation is already accurate, retry unchanged.`;

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

export const PrePushDocsCheckPlugin: Plugin = ({ client }) => {
  /**
   * Tracks whether the reminder has been issued in this plugin instance.
   * The next recognised attempt acknowledges and resets the reminder; this
   * state does not demonstrate a documentation review or successful push.
   */
  let pushPending = false;

  return Promise.resolve({
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "bash") return;

      const args = output.args as Record<string, unknown>;
      const command = typeof args.command === "string" ? args.command : "";
      if (!isGitPush(command)) return;

      if (pushPending) {
        // A recognised attempt follows the reminder.
        // Allow it and reset so the following attempt is reminded again.
        pushPending = false;

        await client.app.log({
          body: {
            service: "pre-push-docs-check",
            level: "info",
            message: "Reminder acknowledged; allowing this git push attempt and resetting the reminder.",
          },
        });
        return;
      }

      // First recognised attempt after reset -- block and remind.
      pushPending = true;

      await client.app.log({
        body: {
          service: "pre-push-docs-check",
          level: "warn",
          message: "Blocked first recognised git push attempt; requesting documentation review.",
        },
      });

      throw new Error(DOCS_CHECK_MESSAGE);
    },
  });
};
