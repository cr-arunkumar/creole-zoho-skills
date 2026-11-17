#!/usr/bin/env node
// npx / npm entry point. Installs the Python package in this directory with `uv` (once per
// package version) and then runs the `zoho-skills` console script with the user's arguments.
"use strict";
const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const readline = require("readline");

const pkgDir = path.join(__dirname, "..");
const pkg = JSON.parse(fs.readFileSync(path.join(pkgDir, "package.json"), "utf8"));
const home = os.homedir();
const isWin = process.platform === "win32";
const exe = isWin ? ".exe" : "";
const UV_INSTALL_CMD = "curl -LsSf https://astral.sh/uv/install.sh | sh";

function fail(msg) {
  console.error(`zoho-skills: ${msg}`);
  process.exit(1);
}

function works(bin) {
  const r = spawnSync(bin, ["--version"], { stdio: "ignore" });
  return r.status === 0;
}

function findUv() {
  const candidates = ["uv", path.join(home, ".local", "bin", "uv" + exe), path.join(home, ".cargo", "bin", "uv" + exe)];
  return candidates.find((c) => (c === "uv" || fs.existsSync(c)) && works(c)) || null;
}

function confirm(question) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stderr });
    rl.question(question, (a) => {
      rl.close();
      resolve(/^y(es)?$/i.test(a.trim()));
    });
  });
}

async function ensureUv() {
  const found = findUv();
  if (found) return found;
  console.error("zoho-skills needs `uv` (https://docs.astral.sh/uv/) to manage its Python environment, and it was not found.");
  if (isWin) fail("install uv from https://docs.astral.sh/uv/getting-started/installation/ and re-run.");
  if (!process.stdin.isTTY || !process.stderr.isTTY) {
    console.error("Install it with the official installer, then re-run:");
    console.error(`  ${UV_INSTALL_CMD}`);
    process.exit(1);
  }
  console.error(`The official installer will be run:\n  ${UV_INSTALL_CMD}`);
  if (!(await confirm("Install uv now? [y/N] "))) fail("uv is required; aborted.");
  const r = spawnSync("sh", ["-c", UV_INSTALL_CMD], { stdio: "inherit" });
  if (r.status !== 0) fail("uv installation failed.");
  const uv = findUv();
  if (!uv) fail("uv was installed but could not be located; open a new shell and re-run.");
  return uv;
}

function uvBinDir(uv) {
  const r = spawnSync(uv, ["tool", "dir", "--bin"], { encoding: "utf8" });
  return r.status === 0 ? r.stdout.trim() : "";
}

function findCli(uv) {
  const dirs = [uvBinDir(uv), path.join(home, ".local", "bin")].filter(Boolean);
  for (const d of dirs) {
    const p = path.join(d, "zoho-skills" + exe);
    if (fs.existsSync(p)) return p;
  }
  return works("zoho-skills") ? "zoho-skills" : null;
}

async function main() {
  const invoked = process.env.ZOHO_SKILLS_BIN_ALIAS || path.basename(process.argv[1] || "").replace(/\.js$/, "");
  if (invoked === "creole-zoho") {
    console.error("note: `creole-zoho` is deprecated and now an alias; use `zoho-skills` instead.");
  }

  const uv = await ensureUv();
  const stateDir = path.join(home, ".zoho-skills");
  const stamp = path.join(stateDir, `.npm-installed-${pkg.version}`);
  let cli = fs.existsSync(stamp) ? findCli(uv) : null;

  if (!cli) {
    console.error(`zoho-skills: installing ${pkg.version} with uv (one-time)...`);
    const r = spawnSync(uv, ["tool", "install", "--force", pkgDir], { stdio: ["ignore", 2, 2] });
    if (r.status !== 0) fail("`uv tool install` failed.");
    try {
      fs.mkdirSync(stateDir, { recursive: true, mode: 0o700 });
      fs.writeFileSync(stamp, new Date().toISOString() + "\n");
    } catch (_) {
      /* stamp is only an optimisation */
    }
    cli = findCli(uv);
    if (!cli) fail("installed, but the `zoho-skills` command was not found; check `uv tool dir --bin` is on your PATH.");
  }

  const res = spawnSync(cli, process.argv.slice(2), { stdio: "inherit" });
  if (res.error) fail(`could not start ${cli}: ${res.error.message}`);
  process.exit(res.status === null ? 1 : res.status);
}

main();
