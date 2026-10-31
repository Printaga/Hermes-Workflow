/**
 * Shared Playwright loader for the throwaway probes in .hermes/.
 *
 * These scripts run on a developer machine, sometimes from a plain `node` without this repo's
 * dependencies installed. Resolve Playwright normally first, then fall back to the host's
 * bundled copy; launch the version-pinned Chromium unless CHROME_PATH names a browser or the
 * bundled one is unavailable (then a system Chrome/Chromium).
 */
const fs = require("fs");
const os = require("os");
const path = require("path");

function loadPlaywright() {
  try {
    return require("playwright");
  } catch (err) {
    const fallback = path.join(os.homedir(), ".hermes", "hermes-agent", "node_modules", "playwright");
    return require(fallback);
  }
}

const playwright = loadPlaywright();
const { chromium } = playwright;

function systemChrome() {
  return [
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find((candidate) => fs.existsSync(candidate));
}

async function launch(options) {
  const opts = { headless: true, ...(options || {}) };
  if (process.env.CHROME_PATH) opts.executablePath = process.env.CHROME_PATH;
  try {
    return await chromium.launch(opts);
  } catch (err) {
    if (opts.executablePath) throw err;
    const executablePath = systemChrome();
    if (!executablePath) throw err;
    return chromium.launch({ ...opts, executablePath });
  }
}

/** The session token the dashboard's init script needs; fail fast instead of shipping one. */
function requiredToken() {
  const token = process.env.TOK;
  if (!token) {
    console.error("TOK is required (the dashboard session token for this probe).");
    process.exit(2);
  }
  return token;
}

module.exports = { chromium, launch, requiredToken };
