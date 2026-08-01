import { describe, expect, it } from "vitest";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type { Event } from "@opencode-ai/sdk";
import type { Hooks, PluginInput } from "@opencode-ai/plugin";

import {
  isProtectedFile,
  isAddingBypass,
  isJustifiedSuppression,
  protectedPatchChanges,
  countMatches,
  BYPASS_PATTERNS,
  GATE_REFERENCES,
  QualityGatePlugin,
} from "../plugins/quality-gate";

// ---------------------------------------------------------------------------
// isProtectedFile
// ---------------------------------------------------------------------------

describe("isProtectedFile", () => {
  it("matches scripts/ directory prefix", () => {
    expect(isProtectedFile("scripts/check-quality.sh")).toBe(true);
  });

  it("matches Makefile at root", () => {
    expect(isProtectedFile("Makefile")).toBe(true);
  });

  it("matches scripts/ with leading ./", () => {
    expect(isProtectedFile("./scripts/check-quality.sh")).toBe(true);
  });

  it("matches scripts/ with absolute-like path", () => {
    expect(isProtectedFile("/home/user/project/scripts/lint.sh")).toBe(true);
  });

  it("matches Makefile with nested path", () => {
    expect(isProtectedFile("subdir/Makefile")).toBe(true);
  });

  it("rejects non-protected files", () => {
    expect(isProtectedFile("src/main.py")).toBe(false);
  });

  it("rejects empty path", () => {
    expect(isProtectedFile("")).toBe(false);
  });

  it("rejects paths that only resemble targets", () => {
    expect(isProtectedFile("not-scripts/file.txt")).toBe(false);
  });

  it("matches Makefile with backslash normalisation", () => {
    expect(isProtectedFile("path\\to\\Makefile")).toBe(true);
  });

  it("matches scripts/ with backslash normalisation", () => {
    expect(isProtectedFile("path\\scripts\\check.sh")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// countMatches
// ---------------------------------------------------------------------------

describe("countMatches", () => {
  it("counts occurrences in text", () => {
    expect(countMatches("foo bar foo", /foo/g)).toBe(2);
  });

  it("returns 0 when no matches", () => {
    expect(countMatches("hello world", /foo/g)).toBe(0);
  });

  it("handles empty string", () => {
    expect(countMatches("", /./g)).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// isAddingBypass — bypass patterns
// ---------------------------------------------------------------------------

describe("isAddingBypass", () => {
  it("detects --exclude addition", () => {
    const reason = isAddingBypass("", "--exclude src/test");
    expect(reason).toBe("added --exclude bypass");
  });

  it("detects --exclude-rule addition", () => {
    const reason = isAddingBypass("", "--exclude-rule S101");
    expect(reason).toBe("added --exclude-rule bypass");
  });

  it("detects # nosec addition (unjustified)", () => {
    const reason = isAddingBypass("", "# nosec");
    expect(reason).toBe("added # nosec bypass");
  });

  it("ignores justified # nosec line", () => {
    const reason = isAddingBypass("", "# nosec B608 — false positive");
    expect(reason).toBeNull();
  });

  it("detects # pragma: no cover addition (unjustified)", () => {
    const reason = isAddingBypass("", "# pragma: no cover");
    expect(reason).toBe("added # pragma: no cover bypass");
  });

  it("ignores justified # pragma: no cover line", () => {
    const reason = isAddingBypass(
      "",
      "# pragma: no cover — edge case only",
    );
    expect(reason).toBeNull();
  });

  it("detects # type: ignore addition (unjustified)", () => {
    const reason = isAddingBypass("", "# type: ignore");
    expect(reason).toBe("added # type: ignore bypass");
  });

  it("ignores justified # type: ignore line", () => {
    const reason = isAddingBypass(
      "",
      "# type: ignore[override] — library mismatch",
    );
    expect(reason).toBeNull();
  });

  it("detects removal of --severity flag", () => {
    const reason = isAddingBypass("--severity HIGH", "other content");
    expect(reason).toBe("removed severity level(s) from --severity flag");
  });

  it("detects removal of --max-flagged gate reference", () => {
    const reason = isAddingBypass("--max-flagged 10", "other content");
    expect(reason).toBe("removed --max-flagged gate reference");
  });

  it("detects removal of --min-coverage gate reference", () => {
    const reason = isAddingBypass("--min-coverage 80", "other content");
    expect(reason).toBe("removed --min-coverage gate reference");
  });

  it("detects removal of fail_under gate reference", () => {
    const reason = isAddingBypass("fail_under 90", "other content");
    expect(reason).toBe("removed fail_under gate reference");
  });

  it("allows strengthening (more severity flags)", () => {
    const reason = isAddingBypass("", "--severity LOW --severity HIGH");
    expect(reason).toBeNull();
  });

  it("allows same number of bypass lines (reformatting)", () => {
    const reason = isAddingBypass(
      "# nosec\n--exclude foo",
      "--exclude foo\n# nosec",
    );
    expect(reason).toBeNull();
  });

  it("returns null when no bypass changes", () => {
    const reason = isAddingBypass(
      "print('hello')",
      "print('hello world')",
    );
    expect(reason).toBeNull();
  });

  it("detects replacing --severity HIGH with LOW (value substitution)", () => {
    const reason = isAddingBypass("--severity HIGH", "--severity LOW");
    expect(reason).toBe("lowered severity level (--severity HIGH)");
  });

  it("detects replacing --severity HIGH with MEDIUM", () => {
    const reason = isAddingBypass("--severity HIGH", "--severity MEDIUM");
    expect(reason).toBe("lowered severity level (--severity HIGH)");
  });

  it("detects removing the strongest of several severity flags", () => {
    const reason = isAddingBypass(
      "--severity HIGH --severity LOW",
      "--severity LOW",
    );
    expect(reason).toBe("removed severity level(s) from --severity flag");
  });

  it("allows strengthening --severity LOW to HIGH", () => {
    const reason = isAddingBypass("--severity LOW", "--severity HIGH");
    expect(reason).toBeNull();
  });

  it("allows keeping an equal or stronger severity", () => {
    const reason = isAddingBypass(
      "--severity HIGH",
      "--severity HIGH --severity LOW",
    );
    expect(reason).toBeNull();
  });

  it("ignores unknown severity values in --severity", () => {
    const reason = isAddingBypass("--severity BOGUS", "--severity LOW");
    expect(reason).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// isJustifiedSuppression
// ---------------------------------------------------------------------------

describe("isJustifiedSuppression", () => {
  it("accepts nosec with justification", () => {
    expect(
      isJustifiedSuppression("# nosec B608 — intentional debug", "# nosec"),
    ).toBe(true);
  });

  it("rejects nosec without justification", () => {
    expect(isJustifiedSuppression("# nosec", "# nosec")).toBe(false);
  });

  it("accepts pragma: no cover with justification", () => {
    expect(
      isJustifiedSuppression(
        "# pragma: no cover — defers to integration test",
        "# pragma: no cover",
      ),
    ).toBe(true);
  });

  it("rejects pragma: no cover without justification", () => {
    expect(
      isJustifiedSuppression("# pragma: no cover", "# pragma: no cover"),
    ).toBe(false);
  });

  it("accepts type: ignore with justification", () => {
    expect(
      isJustifiedSuppression(
        "# type: ignore[override] — library bug",
        "# type: ignore",
      ),
    ).toBe(true);
  });

  it("rejects type: ignore without justification", () => {
    expect(
      isJustifiedSuppression("# type: ignore[override]", "# type: ignore"),
    ).toBe(false);
  });

  it("returns false for unknown label", () => {
    expect(
      isJustifiedSuppression(
        "# something else — with text",
        "unknown",
      ),
    ).toBe(false);
  });

  it("handles nosec with em-dash separator", () => {
    expect(
      isJustifiedSuppression("# nosec B608 \u2014 false positive", "# nosec"),
    ).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// protectedPatchChanges
// ---------------------------------------------------------------------------

describe("protectedPatchChanges", () => {
  it("extracts changes from patch text for protected files", () => {
    const patch = `*** Add File: scripts/lint.sh
+new line 1
+new line 2
-old line
*** Update File: Makefile
+modified line
*** Add File: src/main.py
+ignored line`;
    const changes = protectedPatchChanges(patch);
    expect(changes.size).toBe(2);
    expect(changes.get("scripts/lint.sh")).toEqual({
      added: ["new line 1", "new line 2"],
      removed: ["old line"],
    });
    expect(changes.get("Makefile")).toEqual({
      added: ["modified line"],
      removed: [],
    });
  });

  it("ignores non-protected files", () => {
    const patch = `*** Add File: src/main.py
+new code
-old code`;
    const changes = protectedPatchChanges(patch);
    expect(changes.size).toBe(0);
  });

  it("handles empty patch text", () => {
    const changes = protectedPatchChanges("");
    expect(changes.size).toBe(0);
  });

  it("handles Delete File operations", () => {
    const patch = `*** Delete File: scripts/old.sh
-discarded line`;
    const changes = protectedPatchChanges(patch);
    expect(changes.size).toBe(1);
    expect(changes.get("scripts/old.sh")).toEqual({
      added: [],
      removed: ["discarded line"],
    });
  });

  it("handles Update File operations", () => {
    const patch = `*** Update File: Makefile
+added line
-removed line`;
    const changes = protectedPatchChanges(patch);
    expect(changes.size).toBe(1);
    expect(changes.get("Makefile")).toEqual({
      added: ["added line"],
      removed: ["removed line"],
    });
  });

  it("ignores non-file section headers", () => {
    const patch = `*** Summary
+summary line
*** Add File: Makefile
+real change`;
    const changes = protectedPatchChanges(patch);
    expect(changes.size).toBe(1);
  });

  it("ignores +++ and --- diff headers", () => {
    const patch = `*** Add File: Makefile
+++ b/Makefile
--- a/Makefile
+actual change`;
    const changes = protectedPatchChanges(patch);
    expect(changes.size).toBe(1);
    const change = changes.get("Makefile");
    expect(change?.added).toEqual(["actual change"]);
    expect(change?.removed).toEqual([]);
  });

  it("handles Move File sections", () => {
    const patch = `*** Move File: scripts/old.sh → scripts/new.sh
+relocated line`;
    const changes = protectedPatchChanges(patch);
    expect(changes.size).toBe(1);
    const change = changes.get("scripts/old.sh");
    expect(change?.added).toEqual(["relocated line"]);
  });

  it("handles Move File sections with -> separator", () => {
    const patch = `*** Move File: Makefile -> Makefile.new
+content`;
    const changes = protectedPatchChanges(patch);
    expect(changes.get("Makefile")?.added).toEqual(["content"]);
  });

  it("handles Move File between two protected targets", () => {
    const patch = `*** Move File: scripts/old.sh → scripts/new.sh
-dropped line`;
    const changes = protectedPatchChanges(patch);
    expect(changes.get("scripts/old.sh")?.removed).toEqual(["dropped line"]);
  });

  it("accumulates duplicate sections for the same protected path", () => {
    const patch = `*** Update File: Makefile
+first
*** Update File: Makefile
+second
-removed`;
    const changes = protectedPatchChanges(patch);
    expect(changes.size).toBe(1);
    const change = changes.get("Makefile");
    expect(change?.added).toEqual(["first", "second"]);
    expect(change?.removed).toEqual(["removed"]);
  });
});

// ---------------------------------------------------------------------------
// BYPASS_PATTERNS and GATE_REFERENCES structure
// ---------------------------------------------------------------------------

describe("constants", () => {
  it("BYPASS_PATTERNS has expected entries", () => {
    const labels = BYPASS_PATTERNS.map((p) => p.label);
    expect(labels).toContain("--exclude");
    expect(labels).toContain("# nosec");
    expect(labels).toContain("# type: ignore");
  });

  it("GATE_REFERENCES has expected entries", () => {
    const labels = GATE_REFERENCES.map((g) => g.label);
    expect(labels).toContain("--max-flagged");
    expect(labels).toContain("--min-coverage");
    expect(labels).toContain("fail_under");
  });

  it("BYPASS_PATTERNS regexes match expected strings", () => {
    expect(BYPASS_PATTERNS[0]?.re.test("--exclude foo")).toBe(true);
    expect(BYPASS_PATTERNS[2]?.re.test("# nosec")).toBe(true);
    expect(BYPASS_PATTERNS[2]?.re.test("# nosec B608")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Hook-level tests (QualityGatePlugin factory)
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

type BeforeHook = NonNullable<Hooks["tool.execute.before"]>;

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

async function createFixture(
  handler: (command: string) => ShellResult | undefined,
  directory: string,
): Promise<{ hooks: Hooks; logs: LogEntry[]; calls: ShellCall[] }> {
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
  const hooks = await QualityGatePlugin({
    client,
    $: fake.shell,
    directory,
  } as unknown as PluginInput);

  return { hooks, logs, calls: fake.calls };
}

async function withTempDir(fn: (dir: string) => Promise<void>): Promise<void> {
  const dir = await mkdtemp(join(tmpdir(), "quality-gate-hook-"));
  try {
    await fn(dir);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function getBeforeHook(hooks: Hooks): BeforeHook {
  const hook = hooks["tool.execute.before"];
  if (hook === undefined) {
    throw new Error("tool.execute.before hook not registered");
  }
  return hook;
}

function runBefore(
  hooks: Hooks,
  tool: string,
  args: Record<string, unknown>,
): Promise<void> {
  return getBeforeHook(hooks)(
    { tool, sessionID: "s", callID: "c" },
    { args },
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

const idleEvent: Event = {
  type: "session.idle",
  properties: { sessionID: "session-1" },
};

describe("QualityGatePlugin hooks", () => {
  it("registers all hooks (pre-turn and post-turn)", async () => {
    await withTempDir(async (dir) => {
      const { hooks } = await createFixture(() => undefined, dir);
      expect(typeof hooks["tool.execute.before"]).toBe("function");
      expect(typeof hooks.event).toBe("function");
    });
  });

  it("disabled mode registers no hooks", async () => {
    process.env.OPENCODE_DISABLE_QUALITY_GATE = "1";
    try {
      await withTempDir(async (dir) => {
        const { hooks } = await createFixture(() => undefined, dir);
        expect(hooks).toEqual({});
      });
    } finally {
      delete process.env.OPENCODE_DISABLE_QUALITY_GATE;
    }
  });

  it("blocks an empty write to a protected file", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture(() => undefined, dir);
      const rejection = await captureRejection(
        runBefore(hooks, "write", { filePath: "scripts/lint.sh", content: "" }),
      );
      expect(rejection.message).toContain("quality-gate plugin");
      expect(rejection.message).toContain("empty writes");
      expect(logs).toHaveLength(1);
      expect(logs[0]).toMatchObject({ service: "quality-gate", level: "warn" });
    });
  });

  it("blocks a write that adds a bypass pattern to a protected file", async () => {
    await withTempDir(async (dir) => {
      await mkdir(join(dir, "scripts"), { recursive: true });
      await writeFile(join(dir, "scripts", "lint.sh"), "#!/bin/bash\nruff check src\n");
      const { hooks, logs } = await createFixture(() => undefined, dir);
      const rejection = await captureRejection(
        runBefore(hooks, "write", {
          filePath: "scripts/lint.sh",
          content: "#!/bin/bash\nruff check src\n# nosec\n",
        }),
      );
      expect(rejection.message).toContain("added # nosec bypass");
      expect(logs[0]?.message).toContain("Blocked change to scripts/lint.sh");
    });
  });

  it("blocks a write that lowers the --severity value", async () => {
    await withTempDir(async (dir) => {
      await mkdir(join(dir, "scripts"), { recursive: true });
      await writeFile(
        join(dir, "scripts", "semgrep.sh"),
        "semgrep --severity HIGH\n",
      );
      const { hooks } = await createFixture(() => undefined, dir);
      const rejection = await captureRejection(
        runBefore(hooks, "write", {
          filePath: "scripts/semgrep.sh",
          content: "semgrep --severity LOW\n",
        }),
      );
      expect(rejection.message).toContain("lowered severity level");
    });
  });

  it("blocks an edit that lowers the --severity value", async () => {
    await withTempDir(async (dir) => {
      const { hooks } = await createFixture(() => undefined, dir);
      const rejection = await captureRejection(
        runBefore(hooks, "edit", {
          filePath: "Makefile",
          oldString: "--severity HIGH",
          newString: "--severity LOW",
        }),
      );
      expect(rejection.message).toContain("lowered severity level");
    });
  });

  it("blocks an edit that removes a gate reference", async () => {
    await withTempDir(async (dir) => {
      const { hooks } = await createFixture(() => undefined, dir);
      const rejection = await captureRejection(
        runBefore(hooks, "edit", {
          filePath: "Makefile",
          oldString: "--max-flagged 5",
          newString: "",
        }),
      );
      expect(rejection.message).toContain("removed --max-flagged");
    });
  });

  it("blocks apply_patch edits to protected files", async () => {
    await withTempDir(async (dir) => {
      const { hooks } = await createFixture(() => undefined, dir);
      const patchText = `*** Add File: scripts/lint.sh
+#!/bin/bash
+--exclude src
*** Update File: Makefile
+--min-coverage 100
`;
      const rejection = await captureRejection(
        runBefore(hooks, "apply_patch", { patchText }),
      );
      expect(rejection.message).toContain("added --exclude bypass");
    });
  });

  it("blocks apply_patch Move sections that touch protected files", async () => {
    await withTempDir(async (dir) => {
      const { hooks } = await createFixture(() => undefined, dir);
      const patchText = `*** Move File: scripts/lint.sh → scripts/lint-new.sh
+# nosec
`;
      const rejection = await captureRejection(
        runBefore(hooks, "apply_patch", { patchText }),
      );
      expect(rejection.message).toContain("added # nosec bypass");
    });
  });

  it("allows clean writes to protected files via path aliases", async () => {
    await withTempDir(async (dir) => {
      await mkdir(join(dir, "scripts"), { recursive: true });
      await writeFile(join(dir, "scripts", "lint.sh"), "old\n");
      const { hooks, logs } = await createFixture(() => undefined, dir);
      await runBefore(hooks, "write", {
        filePath: "./scripts/lint.sh",
        content: "new clean\n",
      });
      expect(logs).toHaveLength(0);
    });
  });

  it("does not block writes to non-protected files", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture(() => undefined, dir);
      await runBefore(hooks, "write", {
        filePath: "src/main.py",
        content: "--exclude foo\n",
      });
      expect(logs).toHaveLength(0);
    });
  });

  it("returns early when write args are missing", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture(() => undefined, dir);
      await runBefore(hooks, "write", {});
      expect(logs).toHaveLength(0);
    });
  });

  it("returns early when a protected write omits content", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture(() => undefined, dir);
      await runBefore(hooks, "write", { filePath: "scripts/lint.sh" });
      expect(logs).toHaveLength(0);
    });
  });

  it("returns early for unrelated tools", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture(() => undefined, dir);
      await runBefore(hooks, "bash", { command: "echo hi" });
      expect(logs).toHaveLength(0);
    });
  });

  it("returns early for edits to non-protected files", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture(() => undefined, dir);
      await runBefore(hooks, "edit", {
        filePath: "src/main.py",
        oldString: "--severity HIGH",
        newString: "--severity LOW",
      });
      expect(logs).toHaveLength(0);
    });
  });

  it("returns early when edit strings are empty", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture(() => undefined, dir);
      await runBefore(hooks, "edit", {
        filePath: "Makefile",
        oldString: "",
        newString: "",
      });
      expect(logs).toHaveLength(0);
    });
  });

  it("allows clean edits to protected files", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture(() => undefined, dir);
      await runBefore(hooks, "edit", {
        filePath: "Makefile",
        oldString: "old",
        newString: "new",
      });
      expect(logs).toHaveLength(0);
    });
  });

  it("allows apply_patch changes that keep the gate intact", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture(() => undefined, dir);
      const patchText = `*** Update File: Makefile
+clean tightening
*** Update File: scripts/lint.sh
+echo ok
`;
      await runBefore(hooks, "apply_patch", { patchText });
      expect(logs).toHaveLength(0);
    });
  });

  it("supports the legacy patch argument name", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture(() => undefined, dir);
      const patch = `*** Add File: Makefile
+--exclude foo
`;
      const rejection = await captureRejection(
        runBefore(hooks, "apply_patch", { patch }),
      );
      expect(rejection.message).toContain("added --exclude bypass");
      expect(logs[0]?.message).toContain("Blocked change to Makefile");
    });
  });

  it("blocks a bypass write addressed via an absolute path", async () => {
    await withTempDir(async (dir) => {
      const absolutePath = join(dir, "scripts", "lint.sh");
      await mkdir(join(dir, "scripts"), { recursive: true });
      await writeFile(absolutePath, "clean\n");
      const { hooks } = await createFixture(() => undefined, dir);
      const rejection = await captureRejection(
        runBefore(hooks, "write", {
          filePath: absolutePath,
          content: "clean\n--exclude src\n",
        }),
      );
      expect(rejection.message).toContain("added --exclude bypass");
    });
  });

  it("blocks a bypass write to a protected file that does not exist yet", async () => {
    await withTempDir(async (dir) => {
      const { hooks } = await createFixture(() => undefined, dir);
      const rejection = await captureRejection(
        runBefore(hooks, "write", {
          filePath: "scripts/new-lint.sh",
          content: "#!/bin/bash\n# nosec\n",
        }),
      );
      expect(rejection.message).toContain("added # nosec bypass");
    });
  });

  it("rejects when the protected target cannot be read (EISDIR)", async () => {
    await withTempDir(async (dir) => {
      await mkdir(join(dir, "scripts", "lint.sh"), { recursive: true });
      const { hooks } = await createFixture(() => undefined, dir);
      const rejection = await captureRejection(
        runBefore(hooks, "write", {
          filePath: "scripts/lint.sh",
          content: "clean content\n",
        }),
      );
      expect(rejection.message).toContain("EISDIR");
    });
  });

  it("session.idle logs info when the gate passes", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture((command) => {
        if (command.startsWith("git status")) {
          return { exitCode: 0, stdout: " M scripts/lint.sh\n", stderr: "" };
        }
        if (command === "make coupling-check") {
          return { exitCode: 0, stdout: "", stderr: "" };
        }
        return undefined;
      }, dir);
      await hooks.event?.({ event: idleEvent });
      expect(logs).toHaveLength(1);
      expect(logs[0]).toMatchObject({ service: "quality-gate", level: "info" });
      expect(logs[0]?.message).toContain("scripts/lint.sh");
      expect(logs[0]?.message).toContain("coupling-check passed");
    });
  });

  it("session.idle logs warn when coupling-check fails", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture((command) => {
        if (command.startsWith("git status")) {
          return { exitCode: 0, stdout: " M Makefile\n", stderr: "" };
        }
        if (command === "make coupling-check") {
          return { exitCode: 1, stdout: "", stderr: "loop detected" };
        }
        return undefined;
      }, dir);
      await hooks.event?.({ event: idleEvent });
      expect(logs[0]?.level).toBe("warn");
      expect(logs[0]?.message).toContain("coupling-check FAILED: loop detected");
    });
  });

  it("session.idle does not log when nothing was modified", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture(() => undefined, dir);
      await hooks.event?.({ event: idleEvent });
      expect(logs).toHaveLength(0);
    });
  });

  it("session.idle logs warn when coupling-check cannot run", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture((command) => {
        if (command.startsWith("git status")) {
          return { exitCode: 0, stdout: " M scripts/lint.sh\n", stderr: "" };
        }
        if (command === "make coupling-check") {
          throw new Error("make not found");
        }
        return undefined;
      }, dir);
      await hooks.event?.({ event: idleEvent });
      expect(logs[0]?.level).toBe("warn");
      expect(logs[0]?.message).toContain("coupling-check could not run");
    });
  });

  it("session.idle does not log when git status fails", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture((command) => {
        if (command.startsWith("git status")) {
          return { exitCode: 1, stdout: "", stderr: "not a git repo" };
        }
        return { exitCode: 0, stdout: "", stderr: "" };
      }, dir);
      await hooks.event?.({ event: idleEvent });
      expect(logs).toHaveLength(0);
    });
  });

  it("session.idle tolerates a git status that throws", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture((command) => {
        if (command.startsWith("git status")) {
          throw new Error("git binary missing");
        }
        return { exitCode: 0, stdout: "", stderr: "" };
      }, dir);
      await hooks.event?.({ event: idleEvent });
      expect(logs).toHaveLength(0);
    });
  });

  it("session.idle falls back to stdout detail when stderr is empty", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture((command) => {
        if (command.startsWith("git status")) {
          return { exitCode: 0, stdout: " M scripts/lint.sh\n", stderr: "" };
        }
        if (command === "make coupling-check") {
          return { exitCode: 1, stdout: "stdout-detail", stderr: "" };
        }
        return { exitCode: 0, stdout: "", stderr: "" };
      }, dir);
      await hooks.event?.({ event: idleEvent });
      expect(logs[0]?.level).toBe("warn");
      expect(logs[0]?.message).toContain("coupling-check FAILED: stdout-detail");
    });
  });

  it("session.idle reports a bare failure when no detail is available", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture((command) => {
        if (command.startsWith("git status")) {
          return { exitCode: 0, stdout: " M scripts/lint.sh\n", stderr: "" };
        }
        if (command === "make coupling-check") {
          return { exitCode: 1, stdout: "", stderr: "" };
        }
        return { exitCode: 0, stdout: "", stderr: "" };
      }, dir);
      await hooks.event?.({ event: idleEvent });
      expect(logs[0]?.message).toContain("coupling-check FAILED");
      expect(logs[0]?.message).not.toContain("FAILED:");
    });
  });

  it("block() logs and throws the full block message", async () => {
    await withTempDir(async (dir) => {
      await mkdir(join(dir, "scripts"), { recursive: true });
      await writeFile(join(dir, "scripts", "lint.sh"), "ok\n");
      const { hooks, logs } = await createFixture(() => undefined, dir);
      const rejection = await captureRejection(
        runBefore(hooks, "write", {
          filePath: "scripts/lint.sh",
          content: "ok\n# type: ignore\n",
        }),
      );
      expect(rejection.message).toContain("This change was blocked by the quality-gate plugin");
      expect(rejection.message).toContain("added # type: ignore bypass");
      expect(logs[0]?.message).toContain("Blocked change to scripts/lint.sh");
    });
  });

  it("ignores events that are not session.idle", async () => {
    await withTempDir(async (dir) => {
      const { hooks, logs } = await createFixture(() => undefined, dir);
      await hooks.event?.({ event: { type: "session.compacted" } as Event });
      expect(logs).toHaveLength(0);
    });
  });
});
