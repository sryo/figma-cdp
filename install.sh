#!/usr/bin/env bash
# figma-cdp installer — clones the skill to ~/.agents/skills/figma-cdp and links
# it into ~/.claude/skills. Codex and GitHub Copilot read ~/.agents/skills, so the
# one copy serves all three.
# Re-runnable: pulls an existing clone, leaves a link that's already right.
# Never replaces a directory or a link to somewhere else; it says what it found.
#
# Overrides:
#   FIGMA_CDP_REPO=...  git URL to clone from
#   FIGMA_CDP_DIR=...   install location (default: ~/.agents/skills/figma-cdp)
#   PERCH_DIR=...       where perch lives (default: ~/.perch, then ~/Documents/perch)

set -euo pipefail

FIGMA_CDP_REPO="${FIGMA_CDP_REPO:-https://github.com/sryo/figma-cdp.git}"
FIGMA_CDP_DIR="${FIGMA_CDP_DIR:-$HOME/.agents/skills/figma-cdp}"
CLAUDE_LINK="$HOME/.claude/skills/figma-cdp"

[[ "$(uname -s)" == "Darwin" ]] || { echo "figma-cdp only works on macOS (perch drives the browser over AppleScript)." >&2; exit 1; }

command -v git >/dev/null || { echo "git not found. Run: xcode-select --install" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found. Run: xcode-select --install" >&2; exit 1; }
command -v node >/dev/null || { echo "node not found. Install Node 20+ from https://nodejs.org" >&2; exit 1; }
node_major="$(node -p 'process.versions.node.split(".")[0]')"
[[ "$node_major" -ge 20 ]] || { echo "node $node_major < 20. Upgrade Node." >&2; exit 1; }

# link SRC DEST: make DEST a symlink to SRC unless something else is already there.
link() {
  local src="$1" dest="$2"
  if [[ -L "$dest" ]]; then
    if [[ "$(readlink "$dest")" == "$src" ]]; then
      echo "$dest already links to $src"
    else
      echo "$dest links to $(readlink "$dest"), not $src; leaving it."
    fi
  elif [[ -e "$dest" ]]; then
    echo "$dest exists and isn't a link; leaving it."
  else
    mkdir -p "$(dirname "$dest")"
    ln -sfn "$src" "$dest"
    echo "Linked $dest -> $src"
  fi
}

if [[ ! -e "$FIGMA_CDP_DIR" && -L "$CLAUDE_LINK" && -f "$CLAUDE_LINK/SKILL.md" ]]; then
  echo "figma-cdp already installed: $CLAUDE_LINK -> $(readlink "$CLAUDE_LINK"). Leaving it."
  echo "To install a fresh copy instead, remove that link and run this again."
else
  if [[ -f "$FIGMA_CDP_DIR/SKILL.md" ]]; then
    if [[ -d "$FIGMA_CDP_DIR/.git" ]]; then
      echo "figma-cdp already at $FIGMA_CDP_DIR — pulling latest..."
      git -C "$FIGMA_CDP_DIR" pull --ff-only
    else
      echo "figma-cdp already at $FIGMA_CDP_DIR (local, no git repo — skipping pull)..."
    fi
  elif [[ -e "$FIGMA_CDP_DIR" ]]; then
    echo "$FIGMA_CDP_DIR exists but holds no figma-cdp. Move it or set FIGMA_CDP_DIR." >&2
    exit 1
  else
    echo "Cloning figma-cdp to $FIGMA_CDP_DIR..."
    mkdir -p "$(dirname "$FIGMA_CDP_DIR")"
    git clone --quiet "$FIGMA_CDP_REPO" "$FIGMA_CDP_DIR"
  fi
  link "$FIGMA_CDP_DIR" "$CLAUDE_LINK"
fi

perch_found=0
for d in ${PERCH_DIR:+"$PERCH_DIR"} "$HOME/.perch" "$HOME/Documents/perch"; do
  [[ -f "$d/server.js" ]] && { perch_found=1; break; }
done

echo
echo "figma-cdp installed. Restart your agent if it doesn't pick up the skill."
if [[ "$perch_found" == "0" ]]; then
  cat <<'EOF'

figma-cdp reaches Figma through perch, which isn't installed. Install it with:
  curl -fsSL https://raw.githubusercontent.com/sryo/perch/main/install.sh | bash
EOF
fi
cat <<'EOF'

Open a Figma file in Chrome, Arc or Safari (or a perch room) and ask your agent to build in it.
Optional: for image rendering or comments, give your agent a Figma personal access token
(https://www.figma.com/developers/api#access-tokens).
EOF
