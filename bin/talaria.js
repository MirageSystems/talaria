#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");
const path = require("path");

const repoRoot = path.resolve(__dirname, "..");
const pythonPath = process.env.PYTHONPATH
  ? `${repoRoot}${path.delimiter}${process.env.PYTHONPATH}`
  : repoRoot;

function findPython() {
  const candidates = [process.env.TALARIA_PYTHON || "", "python3", "python", "py -3"];
  for (const candidate of candidates) {
    if (!candidate) continue;
    const proc = spawnSync(candidate, ["--version"], { encoding: "utf8", shell: candidate.includes(" ") });
    if (!proc.error) return candidate;
  }
  return null;
}

const python = findPython();
if (!python) {
  console.error("Python runtime not found. Install python3.");
  process.exit(1);
}

const proc = spawnSync(
  python,
  ["-m", "talaria.cli", ...process.argv.slice(2)],
  {
    stdio: "inherit",
    cwd: repoRoot,
    env: { ...process.env, PYTHONPATH: pythonPath },
    shell: python.includes(" "),
  },
);

if (proc.error) {
  console.error("Failed to run Talaria Python module:", proc.error.message);
  process.exit(1);
}

process.exit(proc.status ?? 0);
