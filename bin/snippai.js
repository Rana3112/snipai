#!/usr/bin/env node
/**
 * snippai — npm wrapper for SnipAI (Python desktop app)
 * Usage: npx snippai  OR  npm i -g snippai && snippai
 * Behavior:
 *   - Windows: launches %LOCALAPPDATA%\SnipAI\.venv\Scripts\pythonw.exe -m snipai
 *   - If not installed, runs the one-line installer (install.ps1) then launches
 *   - macOS/Linux: prints Windows-only notice (SnipAI uses Win32 RegisterHotKey)
 */
const { spawn, execSync } = require('child_process');
const { existsSync } = require('fs');
const path = require('path');
const os = require('os');

function isWin() { return process.platform === 'win32'; }

function snipAiInstalledPath() {
  const localApp = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
  const proj = path.join(localApp, 'SnipAI');
  const pyw = path.join(proj, '.venv', 'Scripts', 'pythonw.exe');
  const exe = path.join(proj, 'dist', 'SnipAI.exe');
  if (existsSync(exe)) return { cmd: exe, args: [], cwd: proj, mode: 'exe' };
  if (existsSync(pyw)) return { cmd: pyw, args: ['-m', 'snipai'], cwd: proj, mode: 'pyw' };
  return null;
}

function launch() {
  if (!isWin()) {
    console.log('SnipAI is Windows-only (uses Win32 RegisterHotKey + mss).');
    console.log('On Windows, run: npm i -g snippai && snippai');
    console.log('Or one-liner: powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Rana3112/snipai/main/install.ps1 | iex"');
    process.exit(0);
  }
  const found = snipAiInstalledPath();
  if (found) {
    // Launch detached, hidden (like run_snipai.vbs)
    const child = spawn(found.cmd, found.args, {
      cwd: found.cwd,
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
    });
    child.unref();
    console.log(`SnipAI launched (${found.mode}): ${found.cmd} ${found.args.join(' ')}`);
    console.log('Check system tray for the blue AI icon. Hotkey: Ctrl+Shift+Space');
    return;
  }
  // Not installed — run installer
  console.log('SnipAI not found at %LOCALAPPDATA%\\SnipAI — running installer...');
  const repo = 'https://raw.githubusercontent.com/Rana3112/snipai/main/install.ps1';
  const psCmd = `powershell -ExecutionPolicy Bypass -NoProfile -Command "irm ${repo} | iex"`;
  try {
    execSync(psCmd, { stdio: 'inherit', windowsHide: false });
  } catch (e) {
    console.error('Installer failed. Try manually:');
    console.error('  powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Rana3112/snipai/main/install.ps1 | iex"');
    process.exit(1);
  }
}

if (require.main === module) launch();
module.exports = { launch };
