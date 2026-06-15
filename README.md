# SnipAI — Distributable Windows AI Screen Agent

Press a hotkey → select any region of your screen → AI analyzes it in a floating chat popup. Works with **any** AI provider.

## Architecture

```
┌─────────────────────────────┐         ┌──────────────────────────────┐
│   DESKTOP CLIENT (.exe)     │  HTTPS  │   MANAGED BACKEND (Railway)  │
│                             │ ──────> │                              │
│  PySide6 UI                 │         │  FastAPI server              │
│  ├─ Setup Wizard (first run)│         │  ├─ Provider router           │
│  ├─ Capture (overlay/mss)   │         │  ├─ Web search pipeline       │
│  ├─ Response Window         │         │  └─ Streaming chat           │
│  ├─ Settings Panel          │         │                              │
│  └─ Tray Icon               │         │  Stateless:                  │
│                             │         │  - No user data stored        │
│  Config: ~/.snipai/config.json        │  - BYOK (bring your own key)  │
└─────────────────────────────┘         └──────────────────────────────┘
```

## Quick Start (End User)

1. Download `SnipAI.exe`
2. Double-click to run
3. Setup wizard appears → choose provider, enter API key, set hotkeys, pick theme
4. Done! Press your hotkey anywhere, drag a selection, get instant AI analysis.

## Features

- **Multi-provider**: OpenAI, Anthropic (Claude), Google (Gemini), Bluesminds, or any OpenAI-compatible endpoint
- **Bring Your Own Key**: We never store your API key
- **Custom hotkeys**: Set your own keyboard shortcuts for crop and text selection
- **Theme customization**: 5 preset themes (Midnight, Light, Forest, Sunset, Purple) + custom accent color
- **Multi-snip stack**: Collect multiple crops/texts, analyze together
- **Region watch**: Pin a screen region, get notified when it changes
- **History**: Searchable SQLite database of all your snips
- **Web search**: AI can search the web for current info
- **Action buttons**: Copy code, open links directly from the response

## Hotkeys (default)

- `Ctrl+Shift+Space` — Capture a region
- `Ctrl+Alt+G` — Grab selected text

## For Developers

### Backend Deployment (Railway)

```bash
cd backend
# Push to a Git repo, then connect to Railway
# Or use Railway CLI: railway up
```

The backend is a stateless FastAPI server. User's API keys are sent with each request — never stored.

### Desktop Client Development

```powershell
# Install deps
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Run
python -m snipai
```

### Build .exe

```powershell
python build.py
# Output: dist/SnipAI.exe (~80-120 MB)
```

## Stack

- **Backend**: FastAPI, openai SDK, anthropic SDK, google-genai SDK
- **Client**: PySide6, mss, keyboard, httpx
- **Distribution**: PyInstaller

## Config Files

| Location | Purpose |
|---|---|
| `~/.snipai/config.json` | User config (provider, key, hotkeys, theme) |
| `~/.snipai/history.db` | SQLite history of all snips |
| `backend/.env.example` | Optional backend env vars |

## License

MIT
