import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { parse, printParseErrorCode } from "jsonc-parser";

interface ParseError {
  error: number;
  offset: number;
  length: number;
  message?: string;
}

interface PluginConfig {
  $schema?: string;
  plugin?: unknown[];
  [key: string]: unknown;
}

const projectRoot = resolve(__dirname, "..", "..");
const configPath = resolve(projectRoot, "opencode.jsonc");
const errors: ParseError[] = [];
const raw = readFileSync(configPath, "utf8");
const parsed: unknown = parse(raw, errors, {
  allowTrailingComma: true,
});

if (errors.length > 0) {
  const details = errors
    .map((error) =>
      `${printParseErrorCode(error.error)} at offset ${error.offset}`,
    )
    .join("\n");
  throw new Error(`Invalid opencode.jsonc:\n${details}`);
}

if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
  throw new Error("opencode.jsonc must contain an object.");
}
const config = parsed as PluginConfig;
if (config.$schema !== "https://opencode.ai/config.json") {
  throw new Error(
    "opencode.jsonc must reference the OpenCode configuration schema.",
  );
}
if (!Array.isArray(config.plugin) || config.plugin.length === 0) {
  throw new Error("opencode.jsonc must register at least one plugin.");
}

for (const plugin of config.plugin) {
  if (typeof plugin !== "string" || !plugin.startsWith(".opencode/plugins/")) {
    throw new Error(`Unsupported local plugin reference: ${String(plugin)}`);
  }
  if (!existsSync(resolve(projectRoot, plugin))) {
    throw new Error(`Registered plugin does not exist: ${plugin}`);
  }
}
