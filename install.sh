#!/usr/bin/env bash
#
# jev-router installer.
#
# This script shows you every change it wants to make, then asks before making
# any of them. Nothing is edited until you type y.
#
set -euo pipefail

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
INSTALL_DIR="$CLAUDE_DIR/jev-router"
BIN_DIR="$HOME/.local/bin"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; }
info() { printf '    %s\n' "$1"; }

echo
bold "jev-router installer"
echo

# ---------------------------------------------------------------- checks
bold "1. Checking your machine"

if command -v python3 >/dev/null 2>&1; then
  ok "python3 found ($(python3 --version 2>&1))"
else
  bad "python3 not found. Install Python 3 first, then run this again."
  exit 1
fi

if [ -f "$SETTINGS" ]; then
  if python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$SETTINGS" 2>/dev/null; then
    ok "found your Claude settings: $SETTINGS"
  else
    bad "$SETTINGS exists but is not valid JSON."
    info "Fix that file first. This installer will not touch a broken settings file."
    exit 1
  fi
else
  ok "no settings.json yet, one will be created at $SETTINGS"
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ok "$BIN_DIR is on your PATH" ;;
  *) bad "$BIN_DIR is NOT on your PATH"
     info "The 'jev' command will not work until you add this to your shell profile:"
     info "    export PATH=\"\$HOME/.local/bin:\$PATH\""
     info "Continuing anyway. Add it afterwards and restart your terminal." ;;
esac

# ---------------------------------------------------------------- plan
echo
bold "2. What this will do"
echo
info "CREATE   $INSTALL_DIR/route.py       the classifier that runs on each message"
info "CREATE   $INSTALL_DIR/config.json    your settings, starts switched OFF"
info "CREATE   $BIN_DIR/jev                the on/off/status command"
if [ -f "$SETTINGS" ]; then
  info "BACKUP   $SETTINGS"
  info "         -> $SETTINGS.bak-jev-$STAMP"
  info "EDIT     $SETTINGS"
  info "         adds ONE UserPromptSubmit hook. Existing hooks are left alone."
else
  info "CREATE   $SETTINGS  with one UserPromptSubmit hook"
fi
echo
info "It does NOT touch your API key, your projects, or any other file."
info "The router installs switched OFF. Nothing is sent anywhere until you run 'jev on'."
echo

printf "Proceed? [y/N] "
read -r reply
case "$reply" in
  [yY]|[yY][eE][sS]) ;;
  *) echo "Cancelled. Nothing was changed."; exit 0 ;;
esac

# ---------------------------------------------------------------- install
echo
bold "3. Installing"

mkdir -p "$INSTALL_DIR" "$BIN_DIR"

install -m 0755 "$SRC/route.py" "$INSTALL_DIR/route.py"
ok "installed route.py"

install -m 0755 "$SRC/jev" "$BIN_DIR/jev"
ok "installed the jev command"

if [ -f "$INSTALL_DIR/config.json" ]; then
  ok "kept your existing config.json"
else
  cp "$SRC/config.example.json" "$INSTALL_DIR/config.json"
  ok "created config.json (router is OFF)"
fi

if [ -f "$SETTINGS" ]; then
  cp "$SETTINGS" "$SETTINGS.bak-jev-$STAMP"
  ok "backed up settings.json -> settings.json.bak-jev-$STAMP"
fi

SETTINGS="$SETTINGS" INSTALL_DIR="$INSTALL_DIR" python3 <<'PYEOF'
import json, os

settings = os.environ["SETTINGS"]
install_dir = os.environ["INSTALL_DIR"]
hook_cmd = os.path.join(install_dir, "route.py")

try:
    with open(settings) as fh:
        data = json.load(fh)
except FileNotFoundError:
    data = {}

ups = data.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])

# Remove any earlier jev-router entry so re-running this installer is safe.
ups[:] = [e for e in ups
          if not any("jev-router" in h.get("command", "")
                     for h in e.get("hooks", []))]

ups.append({"hooks": [{"type": "command", "command": hook_cmd, "timeout": 5}]})

tmp = settings + ".tmp"
os.makedirs(os.path.dirname(settings), exist_ok=True)
with open(tmp, "w") as fh:
    json.dump(data, fh, indent=2)
os.replace(tmp, settings)

print("  \033[32m✓\033[0m registered the hook (%d UserPromptSubmit hook(s) total)"
      % len(ups))
PYEOF

# ---------------------------------------------------------------- verify
echo
bold "4. Checking it worked"

python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$SETTINGS" \
  && ok "settings.json is still valid JSON"

if echo '{"prompt":"test"}' | "$INSTALL_DIR/route.py" >/dev/null 2>&1; then
  ok "route.py runs and exits cleanly"
else
  bad "route.py did not run. Check that python3 works."
fi

if command -v jev >/dev/null 2>&1; then
  ok "the 'jev' command is reachable"
else
  bad "'jev' is not on your PATH yet (see the PATH note above)"
fi

# ---------------------------------------------------------------- done
echo
bold "5. Done. Three things left, and you must do them yourself."
echo
info "a) Get a TypeSafe API key from https://typesafe.ai"
info ""
info "b) Save it where the router can find it:"
info "      mkdir -p ~/.config/typesafe"
info "      echo 'YOUR_KEY_HERE' > ~/.config/typesafe/key"
info "      chmod 600 ~/.config/typesafe/key"
info ""
info "c) Turn it on:"
info "      jev on"
echo
info "Check it any time with:   jev status"
info "Turn it off with:         jev off"
echo
printf '\033[1mWhile the router is ON, every message you type is sent to the TypeSafe API.\033[0m\n'
printf '\033[1mTurn it off before anything private.\033[0m\n'
echo
