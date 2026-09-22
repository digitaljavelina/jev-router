#!/usr/bin/env bash
#
# Removes jev-router. Shows you what it will do, then asks.
#
set -euo pipefail

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
INSTALL_DIR="$CLAUDE_DIR/jev-router"
BIN="$HOME/.local/bin/jev"
STAMP="$(date +%Y%m%d-%H%M%S)"

echo
printf '\033[1mjev-router uninstaller\033[0m\n'
echo
echo "  REMOVE  the jev-router hook entry from $SETTINGS"
echo "          (your other hooks are left alone)"
echo "  DELETE  $INSTALL_DIR"
echo "          this includes your counters and the logged message snippets"
echo "  DELETE  $BIN"
echo
echo "  It will NOT delete your API key at ~/.config/typesafe/key."
echo "  Delete that yourself if you want it gone."
echo
printf "Proceed? [y/N] "
read -r reply
case "$reply" in
  [yY]|[yY][eE][sS]) ;;
  *) echo "Cancelled. Nothing was changed."; exit 0 ;;
esac

echo

# --- unregister the hook -----------------------------------------------
if [ -f "$SETTINGS" ]; then
  cp "$SETTINGS" "$SETTINGS.bak-jev-$STAMP"
  echo "  backed up settings.json -> settings.json.bak-jev-$STAMP"
  SETTINGS="$SETTINGS" python3 <<'PYEOF'
import json, os
path = os.environ["SETTINGS"]
data = json.load(open(path))
ups = data.get("hooks", {}).get("UserPromptSubmit", [])
before = len(ups)
ups[:] = [e for e in ups
          if not any("jev-router" in h.get("command", "")
                     for h in e.get("hooks", []))]
if not ups:
    data.get("hooks", {}).pop("UserPromptSubmit", None)
tmp = path + ".tmp"
json.dump(data, open(tmp, "w"), indent=2)
os.replace(tmp, path)
print("  removed %d hook entry (left %d other UserPromptSubmit hooks alone)"
      % (before - len(ups), len(ups)))
PYEOF
fi

# --- remove the install directory, carefully ---------------------------
# Guarded on purpose: only delete a directory that actually looks like ours,
# so a mis-set CLAUDE_CONFIG_DIR cannot take out something else.
if [ -d "$INSTALL_DIR" ]; then
  if [ -f "$INSTALL_DIR/route.py" ]; then
    rm -- "$INSTALL_DIR"/route.py \
          "$INSTALL_DIR"/config.json \
          "$INSTALL_DIR"/state.json \
          "$INSTALL_DIR"/state.json.tmp \
          "$INSTALL_DIR"/_test_transcript.jsonl 2>/dev/null || true
    rmdir "$INSTALL_DIR" 2>/dev/null \
      && echo "  deleted $INSTALL_DIR" \
      || echo "  cleared $INSTALL_DIR (other files were left in it)"
  else
    echo "  SKIPPED $INSTALL_DIR"
    echo "          no route.py in there, so that is not a jev-router install."
    echo "          Delete it yourself if you are sure."
  fi
else
  echo "  nothing at $INSTALL_DIR"
fi

# --- remove the command ------------------------------------------------
if [ -f "$BIN" ]; then
  rm -- "$BIN" && echo "  deleted $BIN"
else
  echo "  nothing at $BIN"
fi

echo
echo "Done. Restart Claude Code for the hook change to take effect."
echo
