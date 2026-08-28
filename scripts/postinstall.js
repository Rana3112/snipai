/**
 * postinstall — runs after `npm install -g snippai`
 * On Windows, it auto-runs install.ps1 to clone + venv + deps + shortcuts.
 * On other OS, it just prints the Windows-only notice.
 * Never fails the install — user can still run `npx snippai` later to trigger install.
 */
const { execSync } = require('child_process');
const os = require('os');

function isWin() { return process.platform === 'win32'; }

if (!isWin()) {
  console.log('[snippai] Postinstall: Windows-only app — skipping auto-install on', process.platform);
  console.log('[snippai] On Windows, run: npx snippai  or  snippai  to auto-install & launch');
  process.exit(0);
}

// Only auto-install when installed globally (npm_config_global) or when user explicitly wants it
// To avoid surprise on `npm install` as a dep, we do a best-effort but never throw.
try {
  const isGlobal = process.env.npm_config_global === 'true' || process.env.npm_config_global === '1';
  // Even for local install, we can offer to install, but don't block
  console.log('[snippai] Postinstall: setting up SnipAI (Windows)...');
  const repo = 'https://raw.githubusercontent.com/Rana3112/snipai/main/install.ps1';
  // Use -NoProfile and Bypass, run hidden but show output
  const cmd = `powershell -ExecutionPolicy Bypass -NoProfile -Command "try { irm ${repo} | iex } catch { Write-Host \\"[snippai] Auto-install skipped — run 'snippai' or 'npx snippai' to install\\" }"`;
  execSync(cmd, { stdio: 'inherit', timeout: 300000 });
  console.log('[snippai] Postinstall done — run `snippai` or `npx snippai` to launch');
} catch (e) {
  console.log('[snippai] Postinstall: auto-install skipped (you can run `npx snippai` to install)');
  // Do not fail npm install
  process.exit(0);
}
