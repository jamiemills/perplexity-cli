import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import ts from "typescript";

const pluginPath = resolve(import.meta.dirname, "..", "plugins", "plan-compliance-gate.ts");
const source = readFileSync(pluginPath, "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const encoded = Buffer.from(output).toString("base64");
const { isGitCommit } = await import(`data:text/javascript;base64,${encoded}`);

const commits = [
  "git commit -m test",
  "/usr/bin/git commit --no-verify",
  '"/usr/bin/git" commit -m test',
  "git -c core.hooksPath=/dev/null commit -m test",
  "git -C ../repo commit -m test",
  "git status && git commit -m test",
  "git -c alias.ci=commit ci -m test",
  "g\\it commit -m test",
  "cmd=git; $cmd commit -m test",
];
const nonCommits = ["git status", "git commit-tree HEAD", "echo committed"];

for (const command of commits) {
  if (!isGitCommit(command)) {
    throw new Error(`Commit command bypassed plan gate: ${command}`);
  }
}
for (const command of nonCommits) {
  if (isGitCommit(command)) {
    throw new Error(`Non-commit command triggered plan gate: ${command}`);
  }
}
