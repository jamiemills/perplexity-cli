/**
 * pre-push-docs-check -- OpenCode plugin for the perplexity-cli project.
 *
 * Intercepts `git push` commands and reminds the agent to verify that
 * CLI --help text and README.md are consistent with any code changes
 * made during the session.
 *
 * On the first push attempt, the plugin blocks execution and returns
 * an instruction to check documentation.  The agent is expected to
 * review and update if needed, then retry the push, which passes
 * through unblocked.
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

const DOCS_CHECK_MESSAGE = `Before pushing, verify that documentation is up to date.

Check the following:

1. CLI --help text (src/perplexity_cli/commands.py)
   - Option help strings, command docstrings, and example output
     must reflect any new or changed flags, commands, or behaviour.

2. README.md
   - Features list, command reference, options tables, and usage
     examples must be consistent with the current CLI surface.

If either needs updating, make the changes and then retry the push.`;

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

export const PrePushDocsCheckPlugin: Plugin = async ({ client }) => {
  /**
   * Tracks whether the docs-check reminder has been issued for the
   * current push cycle.  Reset after a push is allowed through so
   * that subsequent pushes (after further code changes) also trigger
   * a check.
   */
  let pushPending = false;

  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "bash") return;

      const command: string = output.args.command ?? "";
      if (!isGitPush(command)) return;

      if (pushPending) {
        // The agent has already been reminded and is retrying.
        // Allow this push through and reset for the next cycle.
        pushPending = false;

        await client.app.log({
          body: {
            service: "pre-push-docs-check",
            level: "info",
            message: "Docs check completed; allowing git push.",
          },
        });
        return;
      }

      // First push attempt in this cycle -- block and remind.
      pushPending = true;

      await client.app.log({
        body: {
          service: "pre-push-docs-check",
          level: "warn",
          message: "Intercepted git push; requesting documentation review.",
        },
      });

      throw new Error(DOCS_CHECK_MESSAGE);
    },
  };
};
