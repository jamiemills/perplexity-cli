import type { Hooks, PluginInput } from "@opencode-ai/plugin";
import { describe, expect, it } from "vitest";

import {
  buildCiMessage,
  hasPushFailed,
  isGitPush,
  isUpToDate,
  parseRuns,
  PostPushCiCheckPlugin,
  summariseRuns,
} from "../plugins/post-push-ci-check";
import type { CiRun } from "../plugins/post-push-ci-check";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const HEAD_SHA = "abc123def4567890abc123def4567890abc12345";

function makeRun(overrides: Partial<CiRun> = {}): CiRun {
  return {
    databaseId: 42,
    status: "completed",
    conclusion: "success",
    displayTitle: "CI",
    url: "https://github.com/example/repo/actions/runs/42",
    workflowName: "CI",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Fake shell harness (mirrors pxcli-quality.test.ts)
// ---------------------------------------------------------------------------

interface LogEntry {
  service: string;
  level: string;
  message: string;
}

interface ShellCall {
  command: string;
  cwd?: string;
}

interface ShellResult {
  exitCode?: number;
  stdout?: string;
  stderr?: string;
}

function createFakeShell(
  handler: (command: string) => ShellResult | undefined,
): { shell: PluginInput["$"]; calls: ShellCall[] } {
  const calls: ShellCall[] = [];

  const shell = (
    strings: TemplateStringsArray,
    ...expressions: unknown[]
  ): unknown => {
    let command = "";
    for (let index = 0; index < strings.length; index += 1) {
      command += strings[index] ?? "";
      const expression = expressions[index];
      if (expression === undefined) continue;
      if (typeof expression === "string") {
        command += expression;
      } else if (
        typeof expression === "number" ||
        typeof expression === "boolean" ||
        typeof expression === "bigint"
      ) {
        command += String(expression);
      } else if (Array.isArray(expression)) {
        command += expression.map((item) => item as string).join(" ");
      }
    }

    const call: ShellCall = { command };
    calls.push(call);

    const base = Promise.resolve().then(() => {
      const result = handler(command);
      return {
        exitCode: result?.exitCode ?? 0,
        stdout: Buffer.from(result?.stdout ?? ""),
        stderr: Buffer.from(result?.stderr ?? ""),
      };
    });
    void base.catch(() => undefined);

    const chained = Object.assign(base, {
      cwd: (dir: string): unknown => {
        call.cwd = dir;
        return chained;
      },
      quiet: (): unknown => chained,
      nothrow: (): unknown => chained,
      throws: (): unknown => chained,
      env: (): unknown => chained,
    });

    return chained;
  };

  return { shell: shell as unknown as PluginInput["$"], calls };
}

interface Harness {
  hooks: Hooks;
  logs: LogEntry[];
  calls: ShellCall[];
}

async function createHarness(
  handler: (command: string) => ShellResult | undefined,
): Promise<Harness> {
  const logs: LogEntry[] = [];
  const client = {
    app: {
      log: (input: { body: LogEntry }): Promise<void> => {
        logs.push(input.body);
        return Promise.resolve();
      },
    },
  } as unknown as PluginInput["client"];

  const fake = createFakeShell(handler);
  const hooks = await PostPushCiCheckPlugin({
    client,
    $: fake.shell,
    directory: "/repo",
  } as unknown as PluginInput);

  return { hooks, logs, calls: fake.calls };
}

function bashOutput(command: string, output: string): {
  input: { tool: string; sessionID: string; callID: string; args: { command: string } };
  output: { title: string; output: string; metadata: Record<string, never> };
} {
  return {
    input: { tool: "bash", sessionID: "session", callID: "call", args: { command } },
    output: { title: "bash", output, metadata: {} },
  };
}

function runsJson(runs: CiRun[]): string {
  return JSON.stringify(runs);
}

function shaHandler(
  ghHandler: (command: string) => ShellResult | undefined,
): (command: string) => ShellResult | undefined {
  return (command: string) => {
    if (command === "git rev-parse HEAD") {
      return { exitCode: 0, stdout: `${HEAD_SHA}\n` };
    }
    return ghHandler(command);
  };
}

// ---------------------------------------------------------------------------
// Environment-controlled poll cadence
// ---------------------------------------------------------------------------

/**
 * Speed up polling for hook tests: two attempts with no delay.  Set
 * inside each test rather than in beforeEach, matching the style of the
 * other plugin test suites.
 */
function useFastPoll(): void {
  process.env.OPENCODE_CI_POLL_ATTEMPTS = "2";
  process.env.OPENCODE_CI_POLL_INTERVAL_MS = "0";
}

describe("PostPushCiCheckPlugin", () => {
  // -------------------------------------------------------------------------
  // Trigger filtering
  // -------------------------------------------------------------------------

  it("ignores non-bash tools", async () => {
    const { hooks, calls } = await createHarness(() => undefined);
    const output = { title: "read", output: "data", metadata: {} };

    await hooks["tool.execute.after"]?.(
      { tool: "read", sessionID: "s", callID: "c", args: { command: "git push" } },
      output,
    );

    expect(output.output).toBe("data");
    expect(calls).toEqual([]);
  });

  it("ignores bash commands that are not git push", async () => {
    const { hooks, calls } = await createHarness(() => undefined);
    const { input, output } = bashOutput("git status", "ok");

    await hooks["tool.execute.after"]?.(input, output);

    expect(output.output).toBe("ok");
    expect(calls).toEqual([]);
  });

  it("ignores failed pushes", async () => {
    const { hooks, calls } = await createHarness(() => undefined);
    const { input, output } = bashOutput(
      "git push",
      "To github.com:example/repo.git\n ! [rejected] main -> main (non-fast-forward)\nerror: failed to push some refs",
    );

    await hooks["tool.execute.after"]?.(input, output);

    expect(output.output).not.toContain("--- Post-Push CI Check ---");
    expect(calls).toEqual([]);
  });

  it("ignores pushes where everything is up-to-date", async () => {
    const { hooks, calls } = await createHarness(() => undefined);
    const { input, output } = bashOutput("git push", "Everything up-to-date");

    await hooks["tool.execute.after"]?.(input, output);

    expect(output.output).not.toContain("--- Post-Push CI Check ---");
    expect(calls).toEqual([]);
  });

  // -------------------------------------------------------------------------
  // CI status reporting
  // -------------------------------------------------------------------------

  it("appends a green report when every run succeeded", async () => {
    useFastPoll();
    const { hooks, logs } = await createHarness(
      shaHandler(() => ({ exitCode: 0, stdout: runsJson([makeRun()]) })),
    );
    const { input, output } = bashOutput("git push", "To github.com:example/repo.git\n   abc123..def456 main -> main");

    await hooks["tool.execute.after"]?.(input, output);

    expect(output.output).toContain("--- Post-Push CI Check ---");
    expect(output.output).toContain("CI is GREEN");
    expect(output.output).toContain(HEAD_SHA.slice(0, 7));
    expect(logs.some((entry) => entry.level === "info")).toBe(true);
  });

  it("appends a pending report with watch instructions when a run is in progress", async () => {
    useFastPoll();
    const pending = makeRun({ status: "in_progress", conclusion: null });
    const { hooks } = await createHarness(
      shaHandler(() => ({ exitCode: 0, stdout: runsJson([pending]) })),
    );
    const { input, output } = bashOutput("git push", "pushed");

    await hooks["tool.execute.after"]?.(input, output);

    expect(output.output).toContain("have not completed yet");
    expect(output.output).toContain("gh run watch <run-id> --exit-status");
    expect(output.output).toContain("MUST be adhered to by any coding agent");
    expect(output.output).toContain("NOT an error");
  });

  it("appends a failure report when a run failed", async () => {
    useFastPoll();
    const failed = makeRun({ conclusion: "failure", databaseId: 99 });
    const { hooks, logs } = await createHarness(
      shaHandler(() => ({ exitCode: 0, stdout: runsJson([failed]) })),
    );
    const { input, output } = bashOutput("git push", "pushed");

    await hooks["tool.execute.after"]?.(input, output);

    expect(output.output).toContain("CI FAILED");
    expect(output.output).toContain("gh run view 99 --log-failed");
    expect(logs.some((entry) => entry.level === "error")).toBe(true);
  });

  it("reports when no CI run is detected after polling", async () => {
    useFastPoll();
    const { hooks, calls } = await createHarness(
      shaHandler(() => ({ exitCode: 0, stdout: "[]" })),
    );
    const { input, output } = bashOutput("git push", "pushed");

    await hooks["tool.execute.after"]?.(input, output);

    expect(output.output).toContain("No CI run matching the pushed commit");
    const ghCalls = calls.filter((call) => call.command.startsWith("gh run list"));
    expect(ghCalls).toHaveLength(2);
  });

  it("reports when the gh CLI query fails", async () => {
    useFastPoll();
    const { hooks, logs } = await createHarness(
      shaHandler(() => ({ exitCode: 1, stderr: "gh: not logged in" })),
    );
    const { input, output } = bashOutput("git push", "pushed");

    await hooks["tool.execute.after"]?.(input, output);

    expect(output.output).toContain("Could not query CI status");
    expect(logs.some((entry) => entry.level === "warn")).toBe(true);
  });

  it("polls until a run appears", async () => {
    useFastPoll();
    let ghCalls = 0;
    const { hooks } = await createHarness(
      shaHandler(() => {
        ghCalls += 1;
        return ghCalls === 1
          ? { exitCode: 0, stdout: "[]" }
          : { exitCode: 0, stdout: runsJson([makeRun()]) };
      }),
    );
    const { input, output } = bashOutput("git push", "pushed");

    await hooks["tool.execute.after"]?.(input, output);

    expect(ghCalls).toBe(2);
    expect(output.output).toContain("CI is GREEN");
  });

  it("logs a warning and skips when HEAD cannot be resolved", async () => {
    const { hooks, logs } = await createHarness(() => ({ exitCode: 128 }));
    const { input, output } = bashOutput("git push", "pushed");

    await hooks["tool.execute.after"]?.(input, output);

    expect(output.output).toBe("pushed");
    expect(logs.some((entry) => entry.level === "warn")).toBe(true);
  });

  // -------------------------------------------------------------------------
  // Pure helpers
  // -------------------------------------------------------------------------

  describe("pure helpers", () => {
    it("isGitPush matches push commands only", () => {
      expect(isGitPush("git push origin main")).toBe(true);
      expect(isGitPush("git  push --force")).toBe(true);
      expect(isGitPush("git pushd")).toBe(false);
      expect(isGitPush("git status")).toBe(false);
    });

    it("hasPushFailed detects rejection and fatal output", () => {
      expect(hasPushFailed("! [rejected] main -> main")).toBe(true);
      expect(hasPushFailed("error: failed to push some refs")).toBe(true);
      expect(hasPushFailed("fatal: could not read Username")).toBe(true);
      expect(hasPushFailed("abc123..def456 main -> main")).toBe(false);
    });

    it("isUpToDate detects the no-op push", () => {
      expect(isUpToDate("Everything up-to-date")).toBe(true);
      expect(isUpToDate("abc123..def456 main -> main")).toBe(false);
    });

    it("parseRuns returns null for invalid JSON and filters malformed entries", () => {
      expect(parseRuns("not json")).toBeNull();
      expect(parseRuns("{}")).toBeNull();
      expect(parseRuns(runsJson([makeRun()]))).toHaveLength(1);
      expect(parseRuns('[{"status":"completed"}]')).toEqual([]);
    });

    it("summariseRuns classifies none, pending, failed and green", () => {
      expect(summariseRuns([])).toEqual({ kind: "none" });
      expect(summariseRuns([makeRun({ status: "queued", conclusion: null })]).kind).toBe("pending");
      expect(summariseRuns([makeRun({ conclusion: "timed_out" })]).kind).toBe("failed");
      expect(summariseRuns([makeRun()]).kind).toBe("green");
      // A failure wins over a still-pending run.
      const mixed = summariseRuns([
        makeRun({ conclusion: "failure" }),
        makeRun({ status: "in_progress", conclusion: null }),
      ]);
      expect(mixed.kind).toBe("failed");
      // Neutral conclusions count as passing.
      expect(summariseRuns([makeRun({ conclusion: "neutral" })]).kind).toBe("green");
    });

    it("buildCiMessage renders the query-failure variant", () => {
      const message = buildCiMessage(null, HEAD_SHA);
      expect(message).toContain("Could not query CI status");
      expect(message).toContain(HEAD_SHA);
    });
  });
});
