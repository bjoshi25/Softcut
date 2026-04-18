#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd "$(dirname "$0")/.." && pwd)

printf '%s\n' "Engineering operating template"
printf '%s\n' "Repository: $repo_root"
printf '\n'
printf '%s\n' "Start here:"
printf '%s\n' "  1. Read README.md"
printf '%s\n' "  2. Read AGENTS.md"
printf '%s\n' "  3. Review guidance/ for engineering practice"
printf '%s\n' "  4. Use prompts/ when asking agents to plan, implement, or review"
printf '%s\n' "  5. Record plans, reviews, actions, and decisions as work becomes real"
printf '\n'
printf '%s\n' "Recommended loop:"
printf '%s\n' "  plan -> implement -> review -> action -> decision record"
printf '\n'
printf '%s\n' "This script does not install dependencies or modify files."
