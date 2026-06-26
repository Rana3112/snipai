# SnipAI — AI Screen Assistant for Windows

Press a hotkey → drag to select any region of your screen (or highlight text) → get instant AI analysis in a floating chat popup. Supports every major AI provider.

---

## One-Command Install

Open **PowerShell** and paste:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Rana3112/snipai/main/install.ps1 | iex"
```

That's it. The script automatically:
- Installs Python 3.11 (via winget) if not already present
- Installs Git if not already present
- Clones SnipAI into `%LOCALAPPDATA%\SnipAI`
- Creates an isolated Python environment and installs all dependencies
- Adds a `snipai` command usable from any CMD or PowerShell window
- Creates Desktop and Start Menu shortcuts
- Registers SnipAI to start automatically with Windows

After install, the **Setup Wizard** opens automatically. Add a free [Groq API key](https://console.groq.com/keys) (no credit card required) and you're ready to go.

---

## Manual Installation (Step-by-Step)

### Requirements

| Requirement | Version | Notes |
|---|---|---|
| Windows | 10 / 11 | 64-bit |
| Python | 3.10 or newer | [python.org](https://python.org) |
| Git | Any | [git-scm.com](https://git-scm.com) |

### Steps

**1. Clone the repository**

```cmd
git clone https://github.com/Rana3112/snipai.git
cd snipai
```

**2. Create a virtual environment**

```cmd
python -m venv .venv
.venv\Scripts\activate
```

**3. Install dependencies**

```cmd
pip install -r requirements.txt
```

**4. Run SnipAI**

```cmd
python -m snipai
```

The Setup Wizard opens on first run. Complete it to configure your API key, hotkeys, and theme.

---

## Getting an API Key (Free)

SnipAI works with **any** AI provider. The easiest free option:

| Provider | Free Tier | Sign-up |
|---|---|---|
| **Groq** | Yes — no credit card | [console.groq.com/keys](https://console.groq.com/keys) |
| **NVIDIA NIM** | Yes — no credit card | [build.nvidia.com](https://build.nvidia.com) |
| OpenRouter | Free models available | [openrouter.ai/keys](https://openrouter.ai/keys) |
| OpenAI | Pay-per-use | [platform.openai.com](https://platform.openai.com) |
| Anthropic | Pay-per-use | [console.anthropic.com](https://console.anthropic.com) |
| Google Gemini | Free tier available | [aistudio.google.com](https://aistudio.google.com) |

---

## Usage

### Capture a Screen Region

1. Press **Ctrl + Shift + Space** (default)
2. Your screen dims — drag to draw a rectangle over anything
3. Release — the AI response popup appears instantly
4. Ask follow-up questions in the chat input

### Grab Selected Text

1. Highlight any text in any app
2. Press **Ctrl + Alt + G** (default)
3. SnipAI analyzes the selected text

### Other Features

| Feature | How to use |
|---|---|
| **Multi-snip stack** | Tray → "Add snip to stack" multiple times → "Analyze stack" |
| **Region watch** | Tray → "Watch a region" — alerts you when the region changes |
| **History** | Tray → "History" or the clock icon in the popup |
| **Settings** | Tray → "Settings" or the gear icon in the popup |

---

## Settings

Open **Settings** from the system tray icon or the gear icon inside the chat popup.

### Hotkeys Tab
Click a hotkey field, then press the key combination you want to use. Changes apply after restarting SnipAI.

### Theme Tab
Choose from 5 presets (Midnight, Lavender, Forest, Sunset, Rose) or pick a custom accent color. The preview updates live.

### Providers Tab
- Paste API keys for any provider — the row glows green when active
- Click **Test** next to any key to verify it works before saving
- **Custom Providers**: add any OpenAI-compatible endpoint (Ollama, LM Studio, Together, etc.)
- **Fallback Order**: reorder providers — SnipAI automatically switches when one rate-limits you

---

## Architecture

```
┌─────────────────────────────────┐    HTTPS    ┌────────────────────────────┐
│   DESKTOP CLIENT (Python)       │ ──────────> │   BACKEND (FastAPI)        │
│                                 │             │                            │
│  PySide6 UI                     │             │  Provider router           │
│  ├─ Setup Wizard (first run)    │             │  ├─ OpenAI                 │
│  ├─ Capture overlay (mss)       │             │  ├─ Anthropic              │
│  ├─ Response Window (chat)      │             │  ├─ Google Gemini          │
│  ├─ Settings Panel              │             │  ├─ Groq / NVIDIA / etc.   │
│  └─ System Tray                 │             │  └─ Web search pipeline    │
│                                 │             │                            │
│  Config: ~/.snipai/config.json  │             │  Stateless — your API key  │
│  History: ~/.snipai/history.db  │             │  is never stored server-side│
└─────────────────────────────────┘             └────────────────────────────┘
```

Your API keys are sent with each request and **never stored** on the server.

---

## Installer Options

The `install.ps1` script accepts optional flags:

```powershell
# Install without adding SnipAI to Windows startup
.\install.ps1 -NoStartup

# Install without creating Desktop / Start Menu shortcuts
.\install.ps1 -NoShortcuts

# Update an existing installation (pull latest code + reinstall deps)
.\install.ps1 -Update
```

---

## Uninstall

```powershell
# Remove app files
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\SnipAI"
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Programs\snipai"

# Remove startup registry entry
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v SnipAI /f

# Remove shortcuts
Remove-Item "$env:USERPROFILE\Desktop\SnipAI.lnk" -ErrorAction SilentlyContinue
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\SnipAI.lnk" -ErrorAction SilentlyContinue

# Remove config and history (optional — permanently deletes your snip history)
Remove-Item -Recurse -Force "$env:USERPROFILE\.snipai"
```

---

## For Developers

### Running from source

```powershell
git clone https://github.com/Rana3112/snipai.git
cd snipai
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m snipai
```

### Running the backend locally

```powershell
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

To point the desktop client at your local backend:

```powershell
$env:SNIPAI_BACKEND_URL = "http://localhost:8000"
python -m snipai
```

### Building the .exe

```powershell
python build.py
# Output: dist\SnipAI.exe
```

### Deploying the backend (Railway)

```bash
cd backend
railway login
railway up
```

---

## File Locations

| Path | Purpose |
|---|---|
| `%LOCALAPPDATA%\SnipAI\` | App files (installed by installer) |
| `~\.snipai\config.json` | User config (provider, hotkeys, theme) |
| `~\.snipai\history.db` | SQLite history of all snips |
| `~\.snipai\snipai.log` | Log file for troubleshooting |

---

## Troubleshooting

**Hotkey doesn't work**
- Another app (IME, AutoHotkey, language switcher) may own that shortcut
- Open Settings → Hotkeys → choose a different combination
- Check `~\.snipai\snipai.log` for `RegisterHotKey failed` errors

**"No providers configured" error**
- Open Settings → Providers → paste at least one API key → Save Changes

**Popup doesn't appear**
- Check the system tray — SnipAI icon should be visible
- Try tray menu → "Snip now" to test without the hotkey
- Check `~\.snipai\snipai.log` for errors

**Backend connection error**
- The hosted backend may be sleeping (free tier cold start ~30 sec)
- Wait 30 seconds and try again, or run the backend locally (see above)

---

## Stack

| Layer | Technology |
|---|---|
| Desktop UI | PySide6 (Qt for Python) |
| Screenshot | mss (multi-monitor screen capture) |
| Global hotkeys | Win32 RegisterHotKey (native) |
| HTTP client | httpx |
| Backend | FastAPI + uvicorn |
| AI providers | openai SDK, anthropic SDK, google-genai SDK |
| Distribution | PyInstaller (.exe) |

---

## License

MIT — free to use, modify, and distribute.
