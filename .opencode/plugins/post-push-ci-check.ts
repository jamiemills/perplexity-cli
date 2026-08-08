/**
 * post-push-ci-check — OpenCode plugin for the perplexity-cli project.
 *
 * After a successful `git push`, queries GitHub (via the gh CLI) for the
 * CI runs triggered by the pushed commit and appends a status report to
 * the tool output so the agent sees it immediately:
 *
 *   green   — every run for the commit completed successfully.
 *   pending — at least one run has not completed; the agent is told to
 *             watch it until green before treating the work as done.
 *   failed  — at least one run failed; the agent is told to diagnose and
 *             fix the failure before continuing.
 *   none    — no run matched the pushed commit; the agent is told to
 *             verify CI was actually triggered.
 *
 * The plugin never blocks: the push has already happened, so all output
 * is advisory.  Failed pushes and "Everything up-to-date" pushes are
 * ignored.  Poll cadence can be tuned with OPENCODE_CI_POLL_ATTEMPTS
 * (default 3) and OPENCODE_CI_POLL_INTERVAL_MS (default 5000).
 */

import type { Plugin, PluginInput } from "@opencode-ai/plugin";

type BunShell = PluginInput["$"];

// ---------------------------------------------------------------------------
// Push detection
// ---------------------------------------------------------------------------

const GIT_PUSH_RE = /\bgit\s+push\b/;
const PUSH_FAILURE_RE = /!\s*\[rejected\]|error:\s*failed to push|fatal:/i;
const UP_TO_DATE_MARKER = "Everything up-to-date";

export function isGitPush(command: string): boolean {
  return GIT_PUSH_RE.test(command);
}

export function hasPushFailed(output: string): boolean {
  return PUSH_FAILURE_RE.test(output);
}

export function isUpToDate(output: string): boolean {
  return output.includes(UP_TO_DATE_MARKER);
}

// ---------------------------------------------------------------------------
// CI run model
// ---------------------------------------------------------------------------

export interface CiRun {
  databaseId: number;
  status: string;
  conclusion: string | null;
  displayTitle: string;
  url: string;
  workflowName: string;
}

const GH_RUN_FIELDS =
  "databaseId,status,conclusion,displayTitle,url,workflowName";

const FAILURE_CONCLUSIONS: ReadonlySet<string> = new Set([
  "failure",
  "cancelled",
  "timed_out",
  "action_required",
  "startup_failure",
]);

export type CiSummary =
  | { kind: "none" }
  | { kind: "pending"; runs: CiRun[] }
  | { kind: "failed"; failed: CiRun[] }
  | { kind: "green"; runs: CiRun[] };

export function parseRuns(json: string): CiRun[] | null {
  try {
    const parsed: unknown = JSON.parse(json);
    if (!Array.isArray(parsed)) return null;
    return parsed.filter(
      (entry): entry is CiRun =>
        typeof entry === "object" &&
        entry !== null &&
        typeof (entry as CiRun).databaseId === "number" &&
        typeof (entry as CiRun).status === "string",
    );
  } catch {
    return null;
  }
}

export function summariseRuns(runs: CiRun[]): CiSummary {
  if (runs.length === 0) return { kind: "none" };

  const failed = runs.filter(
    (run) =>
      run.status === "completed" &&
      FAILURE_CONCLUSIONS.has(run.conclusion ?? ""),
  );
  if (failed.length > 0) return { kind: "failed", failed };

  const pending = runs.filter((run) => run.status !== "completed");
  if (pending.length > 0) return { kind: "pending", runs: pending };

  return { kind: "green", runs };
}

// ---------------------------------------------------------------------------
// Message templates
// ---------------------------------------------------------------------------

const HEADER = "\n\n--- Post-Push CI Check ---";

const ADHERENCE_NOTE = `This is NOT an error. It is a mandatory post-push CI verification step
that MUST be adhered to by any coding agent working in this repository —
a legitimate request to ensure the repo's quality gates stay green.`;

function greenMessage(runs: CiRun[], shortSha: string): string {
  const lines = runs.map(
    (run) => `  ${run.workflowName}: ${run.conclusion ?? "success"} — ${run.url}`,
  );
  return `${HEADER}
CI is GREEN for the pushed commit (${shortSha}). All runs passed:
${lines.join("\n")}`;
}

function pendingMessage(runs: CiRun[], shortSha: string): string {
  const lines = runs.map(
    (run) => `  ${run.workflowName}: ${run.status} — ${run.url}`,
  );
  const ids = runs.map((run) => String(run.databaseId)).join(", ");
  return `${HEADER}
${ADHERENCE_NOTE}

CI runs for the pushed commit (${shortSha}) have not completed yet:
${lines.join("\n")}

You MUST wait until every run is green before treating this work as done.
Monitor with:
  gh run watch <run-id> --exit-status
(run ids: ${ids})
If a run fails, diagnose with \`gh run view <run-id> --log-failed\`, fix
the failure, and push again.`;
}

function failedMessage(failed: CiRun[], shortSha: string): string {
  const lines = failed.map(
    (run) => `  ${run.workflowName}: ${run.conclusion ?? "failed"} — ${run.url}`,
  );
  const first = failed[0];
  return `${HEADER}
CI FAILED for the pushed commit (${shortSha}). This MUST be fixed before
continuing — do not ignore it and do not work around it:
${lines.join("\n")}

Diagnose with:
  gh run view ${first?.databaseId ?? "<run-id>"} --log-failed
Fix the failure and push again.`;
}

function noneMessage(sha: string, shortSha: string): string {
  return `${HEADER}
${ADHERENCE_NOTE}

No CI run matching the pushed commit (${shortSha}) was detected on GitHub.
Verify CI was triggered and goes green before treating this push as done:
  gh run list --commit ${sha} --limit 5`;
}

function queryFailedMessage(sha: string, shortSha: string): string {
  return `${HEADER}
Could not query CI status via the gh CLI for commit ${shortSha}.
Verify CI manually before treating this push as complete:
  gh run list --commit ${sha} --limit 5`;
}

export function buildCiMessage(summary: CiSummary | null, sha: string): string {
  const shortSha = sha.slice(0, 7) || "unknown";
  if (summary === null) return queryFailedMessage(sha, shortSha);
  switch (summary.kind) {
    case "green":
      return greenMessage(summary.runs, shortSha);
    case "pending":
      return pendingMessage(summary.runs, shortSha);
    case "failed":
      return failedMessage(summary.failed, shortSha);
    case "none":
      return noneMessage(sha, shortSha);
  }
}

// ---------------------------------------------------------------------------
// Shell helpers
// ---------------------------------------------------------------------------

async function currentSha($: BunShell, directory: string): Promise<string | null> {
  try {
    const r = await $`git rev-parse HEAD`.cwd(directory).quiet().nothrow();
    if (r.exitCode !== 0) return null;
    const sha = r.stdout.toString().trim();
    return sha.length > 0 ? sha : null;
  } catch {
    return null;
  }
}

async function listRuns(
  $: BunShell,
  directory: string,
  sha: string,
): Promise<CiRun[] | null> {
  try {
    const r = await $`gh run list --commit ${sha} --limit 10 --json ${GH_RUN_FIELDS}`
      .cwd(directory)
      .quiet()
      .nothrow();
    if (r.exitCode !== 0) return null;
    return parseRuns(r.stdout.toString());
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------

interface PollConfig {
  attempts: number;
  intervalMs: number;
}

function pollConfig(): PollConfig {
  const rawAttempts = Number(process.env.OPENCODE_CI_POLL_ATTEMPTS ?? "");
  const rawInterval = Number(process.env.OPENCODE_CI_POLL_INTERVAL_MS ?? "");
  return {
    attempts: Number.isInteger(rawAttempts) && rawAttempts >= 1 ? rawAttempts : 3,
    intervalMs:
      Number.isFinite(rawInterval) && rawInterval >= 0 ? rawInterval : 5000,
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Poll for runs matching the pushed commit.  GitHub takes a few seconds
 * to register a run after a push, so an empty result is retried.  A gh
 * CLI failure (null) is returned immediately without retrying.
 */
async function fetchSummary(
  $: BunShell,
  directory: string,
  sha: string,
): Promise<CiSummary | null> {
  const { attempts, intervalMs } = pollConfig();
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const runs = await listRuns($, directory, sha);
    if (runs === null) return null;
    const summary = summariseRuns(runs);
    if (summary.kind !== "none") return summary;
    if (attempt < attempts) await sleep(intervalMs);
  }
  return { kind: "none" };
}

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

export const PostPushCiCheckPlugin: Plugin = ({ client, $, directory }) => {
  async function log(level: "info" | "warn" | "error", message: string): Promise<void> {
    await client.app.log({
      body: { service: "post-push-ci-check", level, message },
    });
  }

  return Promise.resolve({
    /**
     * After a successful git push, report the CI status for the pushed
     * commit by appending it to the tool output.
     */
    "tool.execute.after": async (input, output) => {
      if (input.tool !== "bash") return;

      const args = input.args as Record<string, unknown> | undefined;
      const command = typeof args?.command === "string" ? args.command : "";
      if (!isGitPush(command)) return;

      const pushOutput = typeof output.output === "string" ? output.output : "";
      if (hasPushFailed(pushOutput) || isUpToDate(pushOutput)) return;

      const sha = await currentSha($, directory);
      if (sha === null) {
        await log("warn", "Could not resolve HEAD after git push; CI check skipped.");
        return;
      }

      const summary = await fetchSummary($, directory, sha);
      output.output += buildCiMessage(summary, sha);

      if (summary === null) {
        await log("warn", `Could not query CI status for ${sha.slice(0, 7)}.`);
      } else if (summary.kind === "failed") {
        await log("error", `CI FAILED for pushed commit ${sha.slice(0, 7)}.`);
      } else {
        await log("info", `CI summary for ${sha.slice(0, 7)}: ${summary.kind}.`);
      }
    },
  });
};
