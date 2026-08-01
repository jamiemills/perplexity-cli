import type { Hooks, PluginInput } from "@opencode-ai/plugin";
import { describe, expect, it } from "vitest";

import { PrePushDocsCheckPlugin } from "../plugins/pre-push-docs-check";

interface LogRequest {
  body: {
    service: string;
    level: "info" | "warn";
    message: string;
  };
}

interface PluginHarness {
  before: NonNullable<Hooks["tool.execute.before"]>;
  logs: LogRequest[];
}

async function createPluginHarness(): Promise<PluginHarness> {
  const logs: LogRequest[] = [];
  const input = {
    client: {
      app: {
        log: (request: LogRequest): Promise<void> => {
          logs.push(request);
          return Promise.resolve();
        },
      },
    },
  } as unknown as PluginInput;
  const hooks = await PrePushDocsCheckPlugin(input);
  const before = hooks["tool.execute.before"];

  if (before === undefined) {
    throw new Error("Pre-push documentation hook was not registered");
  }

  return { before, logs };
}

function execute(
  before: NonNullable<Hooks["tool.execute.before"]>,
  tool: string,
  command: string,
): Promise<void> {
  return before(
    { tool, sessionID: "session", callID: "call" },
    { args: { command } },
  );
}

async function captureRejection(action: Promise<void>): Promise<Error> {
  try {
    await action;
  } catch (error: unknown) {
    if (error instanceof Error) return error;
    throw new Error("Hook rejected with a non-Error value");
  }

  throw new Error("Expected hook to reject");
}

describe("PrePushDocsCheckPlugin", () => {
  it("ignores non-bash tools", async () => {
    const { before, logs } = await createPluginHarness();

    await execute(before, "read", "git push");

    expect(logs).toEqual([]);
  });

  it("ignores non-matching bash commands", async () => {
    const { before, logs } = await createPluginHarness();

    await execute(before, "bash", "git status");

    expect(logs).toEqual([]);
  });

  it("rejects and warns on the first recognised push attempt", async () => {
    const { before, logs } = await createPluginHarness();

    const rejection = await captureRejection(execute(before, "bash", "git push"));

    expect(rejection.message).toContain("Before pushing, verify that documentation is up to date.");
    expect(logs).toEqual([
      {
        body: {
          service: "pre-push-docs-check",
          level: "warn",
          message: "Blocked first recognised git push attempt; requesting documentation review.",
        },
      },
    ]);
  });

  it("allows the second recognised attempt and logs reminder acknowledgement", async () => {
    const { before, logs } = await createPluginHarness();
    await captureRejection(execute(before, "bash", "git push"));

    await execute(before, "bash", "git push");

    expect(logs).toEqual([
      {
        body: {
          service: "pre-push-docs-check",
          level: "warn",
          message: "Blocked first recognised git push attempt; requesting documentation review.",
        },
      },
      {
        body: {
          service: "pre-push-docs-check",
          level: "info",
          message: "Reminder acknowledged; allowing this git push attempt and resetting the reminder.",
        },
      },
    ]);
  });

  it("rejects again on the third recognised attempt", async () => {
    const { before, logs } = await createPluginHarness();
    await captureRejection(execute(before, "bash", "git push"));
    await execute(before, "bash", "git push");

    const rejection = await captureRejection(execute(before, "bash", "git push"));

    expect(rejection.message).toContain("Before pushing, verify that documentation is up to date.");
    expect(logs).toHaveLength(3);
    expect(logs[2]).toEqual({
      body: {
        service: "pre-push-docs-check",
        level: "warn",
        message: "Blocked first recognised git push attempt; requesting documentation review.",
      },
    });
  });
});
