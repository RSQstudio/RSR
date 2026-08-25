#!/usr/bin/env node
// RSQ Skill Router — npm/npx entry point
// Thin wrapper: runs the Python CLI. Requires python3 on PATH.

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const srcDir = resolve(__dirname, "..", "src", "skill_router_cli.py");
const args = process.argv.slice(2);

const result = spawnSync("python3", [srcDir, ...args], {
  stdio: "inherit",
  env: process.env,
});

process.exit(result.status ?? 1);