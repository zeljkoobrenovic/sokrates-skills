#!/usr/bin/env sh
# Link every skill in this repository into the skills folders of your AI coding tools.
#
#   ./install.sh                       # links into ~/.claude/skills (Claude Code) and ~/.agents/skills
#                                      # (Codex CLI, Gemini CLI, Cursor, GitHub Copilot CLI, and others)
#   ./install.sh ~/.cursor/skills      # links into the given folder(s) instead
#   ./install.sh --project             # links into ./.claude/skills and ./.agents/skills of the current
#                                      # project (run it from the project you analyse)
#
# Symlinks mean `git pull` in this repository updates every tool at once. Re-running is safe.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ "$1" = "--project" ]; then
  TARGETS="$PWD/.claude/skills $PWD/.agents/skills"
elif [ $# -gt 0 ]; then
  TARGETS="$*"
else
  TARGETS="$HOME/.claude/skills $HOME/.agents/skills"
fi
for target in $TARGETS; do
  mkdir -p "$target"
  n=0
  for skill in "$HERE"/skills/scanners/*/ "$HERE"/skills/config/*/; do
    name="$(basename "$skill")"
    [ -f "$skill/SKILL.md" ] || continue
    ln -sfn "${skill%/}" "$target/$name"
    n=$((n + 1))
  done
  echo "linked $n skills into $target"
done
