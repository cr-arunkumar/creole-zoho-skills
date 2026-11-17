#!/usr/bin/env node
// npx / npm entry point: runs the Python onboarding CLI (scripts/cli.py) with the user's Python 3.9+.
"use strict";
const { spawnSync } = require("child_process");
const path = require("path");

const cli = path.join(__dirname, "..", "scripts", "cli.py");

function findPython() {
  for (const bin of ["python3", "python", "py"]) {
    const r = spawnSync(bin, ["-c", "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"], { stdio: "ignore" });
    if (r.status === 0) return bin;
  }
  return null;
}

const py = findPython();
if (!py) {
  console.error("creole-zoho needs Python 3.9+ (python3 not found). Install it from https://www.python.org/downloads/ and retry.");
  process.exit(1);
}

const res = spawnSync(py, [cli, ...process.argv.slice(2)], {
  stdio: "inherit",
  env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
});
if (res.error) {
  console.error(`creole-zoho: failed to start ${py}: ${res.error.message}`);
  process.exit(1);
}
process.exit(res.status === null ? 1 : res.status);
