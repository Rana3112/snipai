# SnipAI Installer for Windows
# ─────────────────────────────────────────────────────────────────────────────
# One-command install (run in PowerShell as Administrator or normal user):
#
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Rana3112/snipai/main/install.ps1 | iex"
#
# What this script does:
#   1. Checks for Python 3.10+  (installs via winget if missing)
#   2. Checks for Git           (installs via winget if missing)
#   3. Clones / updates the repo into %LOCALAPPDATA%\SnipAI
#   4. Creates an isolated .venv and installs all Python dependencies
#   5. Creates a `snipai` command accessible from any CMD / PowerShell window
#   6. Creates Desktop + Start Menu shortcuts
#   7. Registers SnipAI to start automatically with Windows (optional)
# ─────────────────────────────────────────────────────────────────────────────

param(
    [switch]$NoStartup,     # Skip adding SnipAI to Windows startup
    [switch]$NoShortcuts,   # Skip Desktop / Start Menu shortcuts
    [switch]$Update         # Update existing install without re-running setup wizard
)

$ErrorActionPreference = "Stop"

$REPO_URL   = "https://github.com/Rana3112/snipai.git"
$INSTALL_DIR = Join-Path $env:LOCALAPPDATA "SnipAI"
$BIN_DIR     = Join-Path $env:LOCALAPPDATA "Programs\snipai"
$VENV_DIR    = Join-Path $INSTALL_DIR ".venv"
$PYTHON_EXE  = Join-Path $VENV_DIR "Scripts\pythonw.exe"
$PYTHON_MIN  = [Version]"3.10"

# ── Helpers ────────────────────────────────────────────────────────────────
function Write-Step  ($msg) { Write-Host "`n  >> $msg" -ForegroundColor Cyan }
function Write-Ok    ($msg) { Write-Host "     [OK] $msg" -ForegroundColor Green }
function Write-Warn  ($msg) { Write-Host "     [!!] $msg" -ForegroundColor Yellow }
function Write-Err   ($msg) { Write-Host "     [XX] $msg" -ForegroundColor Red }

function Refresh-Path {
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
}

function Find-Python {
    foreach ($cmd in @("python","python3","py")) {
        try {
            $out = & $cmd --version 2>&1
            if ($out -match "Python (\d+\.\d+)") {
                if ([Version]$Matches[1] -ge $PYTHON_MIN) { return $cmd }
            }
        } catch {}
    }
    return $null
}

function Find-Git {
    try { return (Get-Command git -ErrorAction Stop).Source } catch { return $null }
}

function Add-ToUserPath ($dir) {
    $cur = [System.Environment]::GetEnvironmentVariable("PATH","User")
    if ($cur -notlike "*$dir*") {
        [System.Environment]::SetEnvironmentVariable("PATH","$cur;$dir","User")
        $env:PATH = "$env:PATH;$dir"
        Write-Ok "Added $dir to PATH (takes effect in new terminals)"
    }
}

# ── Banner ──────────────────────────────────────────────────────────────────
Clear-Host
Write-Host @"

  ███████╗███╗   ██╗██╗██████╗  █████╗ ██╗
  ██╔════╝████╗  ██║██║██╔══██╗██╔══██╗██║
  ███████╗██╔██╗ ██║██║██████╔╝███████║██║
  ╚════██║██║╚██╗██║██║██╔═══╝ ██╔══██║██║
  ███████║██║ ╚████║██║██║     ██║  ██║██║
  ╚══════╝╚═╝  ╚═══╝╚═╝╚═╝     ╚═╝  ╚═╝╚═╝

  AI Screen Assistant — Installer
  https://github.com/Rana3112/snipai

"@ -ForegroundColor Magenta

# ── Step 1: Python ──────────────────────────────────────────────────────────
Write-Step "Checking Python (need 3.10+)..."
$pythonCmd = Find-Python

if (-not $pythonCmd) {
    Write-Warn "Python 3.10+ not found. Installing Python 3.11 via winget..."
    try {
        winget install --id Python.Python.3.11 -e --silent `
            --accept-source-agreements --accept-package-agreements
        Refresh-Path
        $pythonCmd = Find-Python
        if (-not $pythonCmd) { throw "Python still not found after install." }
    } catch {
        Write-Err "Auto-install failed. Please install Python 3.10+ from https://python.org and re-run."
        exit 1
    }
}
$pythonVer = & $pythonCmd --version 2>&1
Write-Ok "Found: $pythonVer"

# ── Step 2: Git ─────────────────────────────────────────────────────────────
Write-Step "Checking Git..."
$gitExe = Find-Git

if (-not $gitExe) {
    Write-Warn "Git not found. Installing via winget..."
    try {
        winget install --id Git.Git -e --silent `
            --accept-source-agreements --accept-package-agreements
        Refresh-Path
        $gitExe = Find-Git
        if (-not $gitExe) { throw "Git still not found." }
    } catch {
        Write-Err "Auto-install failed. Please install Git from https://git-scm.com and re-run."
        exit 1
    }
}
Write-Ok "Git found: $gitExe"

# ── Step 3: Clone / Update repo ─────────────────────────────────────────────
Write-Step "Setting up SnipAI in $INSTALL_DIR ..."

if (Test-Path (Join-Path $INSTALL_DIR ".git")) {
    Write-Ok "Existing install found — pulling latest changes..."
    & git -C $INSTALL_DIR pull --ff-only 2>&1 | ForEach-Object { Write-Host "     $_" }
} else {
    New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null
    Write-Ok "Cloning repository..."
    & git clone $REPO_URL $INSTALL_DIR 2>&1 | ForEach-Object { Write-Host "     $_" }
}

# ── Step 4: Virtual environment + dependencies ──────────────────────────────
Write-Step "Creating Python virtual environment..."

if (-not (Test-Path $VENV_DIR)) {
    & $pythonCmd -m venv $VENV_DIR
}

$pip = Join-Path $VENV_DIR "Scripts\pip.exe"

Write-Ok "Upgrading pip..."
& $pip install --upgrade pip -q

Write-Ok "Installing dependencies (this may take 1–3 minutes)..."
& $pip install -r (Join-Path $INSTALL_DIR "requirements.txt") -q

Write-Ok "Dependencies installed."

# ── Step 5: snipai command in PATH ──────────────────────────────────────────
Write-Step "Creating 'snipai' command..."

New-Item -ItemType Directory -Force -Path $BIN_DIR | Out-Null

# CMD launcher
$launcherCmd = Join-Path $BIN_DIR "snipai.cmd"
@"
@echo off
"$PYTHON_EXE" -m snipai %*
"@ | Set-Content $launcherCmd -Encoding ASCII

# PowerShell launcher
$launcherPs1 = Join-Path $BIN_DIR "snipai.ps1"
@"
& "$PYTHON_EXE" -m snipai @args
"@ | Set-Content $launcherPs1 -Encoding UTF8

Add-ToUserPath $BIN_DIR
Write-Ok "You can now run 'snipai' from any CMD or PowerShell window."

# ── Step 6: Shortcuts ───────────────────────────────────────────────────────
if (-not $NoShortcuts) {
    Write-Step "Creating shortcuts..."
    $WshShell = New-Object -ComObject WScript.Shell

    # Desktop
    $desktop = Join-Path $env:USERPROFILE "Desktop\SnipAI.lnk"
    $sc = $WshShell.CreateShortcut($desktop)
    $sc.TargetPath      = $PYTHON_EXE
    $sc.Arguments       = "-m snipai"
    $sc.WorkingDirectory = $INSTALL_DIR
    $sc.Description     = "SnipAI — AI Screen Assistant"
    $sc.Save()
    Write-Ok "Desktop shortcut created."

    # Start Menu
    $startMenu = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\SnipAI.lnk"
    $sc2 = $WshShell.CreateShortcut($startMenu)
    $sc2.TargetPath      = $PYTHON_EXE
    $sc2.Arguments       = "-m snipai"
    $sc2.WorkingDirectory = $INSTALL_DIR
    $sc2.Description     = "SnipAI — AI Screen Assistant"
    $sc2.Save()
    Write-Ok "Start Menu shortcut created."
}

# ── Step 7: Windows startup ─────────────────────────────────────────────────
if (-not $NoStartup) {
    Write-Step "Registering SnipAI to start with Windows..."
    $regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $regVal  = "`"$PYTHON_EXE`" -m snipai"
    Set-ItemProperty -Path $regPath -Name "SnipAI" -Value $regVal
    Write-Ok "SnipAI will start automatically on login."
    Write-Warn "To disable auto-start: Settings > Startup Apps > disable SnipAI"
    Write-Warn "  or run: reg delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v SnipAI /f"
}

# ── Done ─────────────────────────────────────────────────────────────────────
Write-Host @"

  ──────────────────────────────────────────────────
   Installation complete!
  ──────────────────────────────────────────────────

   Launch options:
     • CMD / PowerShell : snipai
     • Desktop shortcut : double-click SnipAI
     • Start Menu       : search 'SnipAI'

   First run will open the Setup Wizard.
   Add a free Groq API key at https://console.groq.com/keys
   (no credit card required)

   Default hotkeys:
     Ctrl + Shift + Space  — capture a screen region
     Ctrl + Alt + G        — grab selected text

   Uninstall:
     Remove-Item -Recurse -Force '$INSTALL_DIR'
     reg delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v SnipAI /f

  ──────────────────────────────────────────────────
"@ -ForegroundColor Green

# Launch SnipAI now
$launch = Read-Host "`n  Launch SnipAI now? [Y/n]"
if ($launch -ne "n" -and $launch -ne "N") {
    Start-Process $PYTHON_EXE "-m snipai" -WorkingDirectory $INSTALL_DIR
}
