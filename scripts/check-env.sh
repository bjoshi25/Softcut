#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"

missing=0

check_file() {
  if [ ! -f "$1" ]; then
    printf '%s\n' "Missing file: $1"
    missing=1
  fi
}

check_dir() {
  if [ ! -d "$1" ]; then
    printf '%s\n' "Missing directory: $1"
    missing=1
  fi
}

check_file README.md
check_file AGENTS.md
check_file CONTRIBUTING.md
check_file .gitignore
check_file .env.example

check_dir guidance
check_dir prompts
check_dir plans
check_dir reviews
check_dir actions
check_dir docs
check_dir docs/decisions
check_dir scripts

check_file guidance/engineering-principles.md
check_file guidance/coding-practices.md
check_file guidance/implementation.md
check_file guidance/review.md
check_file guidance/action.md
check_file guidance/testing.md
check_file guidance/security-and-secrets.md
check_file guidance/dependencies.md
check_file guidance/documentation.md

check_file prompts/plan.md
check_file prompts/implementation.md
check_file prompts/review.md
check_file prompts/review-action.md
check_file prompts/milestone-review.md
check_file prompts/engineering-truth-review.md
check_file prompts/usefulness-review.md

check_file plans/README.md
check_file reviews/README.md
check_file actions/README.md
check_file docs/architecture.md
check_file docs/decisions/README.md

check_file scripts/bootstrap.sh
check_file scripts/check-env.sh

if [ -d extensions/github ]; then
  check_file extensions/github/README.md
  check_file extensions/github/CODEOWNERS
  check_file extensions/github/.github/pull_request_template.md
  check_file extensions/github/.github/ISSUE_TEMPLATE/bug_report.md
  check_file extensions/github/.github/ISSUE_TEMPLATE/feature_request.md
fi

for env_file in .env .env.*; do
  if [ -f "$env_file" ] && [ "$env_file" != ".env.example" ]; then
    printf '%s\n' "Warning: local $env_file exists."
    printf '%s\n' "Keep it untracked and do not use it as documentation."
  fi
done

if [ -f CODEOWNERS ]; then
  if grep '^[^#]*@your-org' CODEOWNERS >/dev/null 2>&1; then
    printf '%s\n' "Error: CODEOWNERS still contains an active placeholder owner."
    missing=1
  fi
fi

if command -v git >/dev/null 2>&1; then
  tracked_env_files=$(git ls-files '.env*' 2>/dev/null || true)
  for env_file in $tracked_env_files; do
    if [ "$env_file" != ".env.example" ]; then
      printf '%s\n' "Error: $env_file is tracked."
      printf '%s\n' "Secrets must not be committed; document variables in .env.example."
      missing=1
    fi
  done
fi

if [ "$missing" -ne 0 ]; then
  printf '%s\n' "Template check failed."
  exit 1
fi

printf '%s\n' "Template check passed."
