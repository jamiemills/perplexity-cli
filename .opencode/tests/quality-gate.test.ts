import { describe, expect, it } from "vitest";

import {
  isProtectedFile,
  isAddingBypass,
  isJustifiedSuppression,
  protectedPatchChanges,
  countMatches,
  BYPASS_PATTERNS,
  GATE_REFERENCES,
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
    expect(BYPASS_PATTERNS[0]!.re.test("--exclude foo")).toBe(true);
    expect(BYPASS_PATTERNS[2]!.re.test("# nosec")).toBe(true);
    expect(BYPASS_PATTERNS[2]!.re.test("# nosec B608")).toBe(true);
  });
});
