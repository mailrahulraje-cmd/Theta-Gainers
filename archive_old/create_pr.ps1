#!/usr/bin/env pwsh
# PR Creation Script for Type-Safe State Migration
# Purpose: Push branch and create PR on GitHub

$REPO_URL = "https://github.com/mailrahulraje-cmd/Theta-Gainers.git"
$BRANCH = "fix/engine-state-migration-AN-20260215"
$PR_TITLE = "Migrate engine state access to TradeLegManager (safe, tested migration)"
$TMP_BODY = Join-Path $env:TEMP "pr_body_$(Get-Random).txt"

try {
  Write-Host "Working directory:"; Get-Location

  if (-not (Test-Path ".git")) { throw "Not a git repository. Run from the repo root." }

  $current = git rev-parse --abbrev-ref HEAD 2>&1
  Write-Host "Current branch: $current"
  if ($LASTEXITCODE -ne 0) { throw "Failed to determine current branch: $current" }
  if ($current -ne $BRANCH) {
    Write-Host "Switching to branch $BRANCH"
    git checkout $BRANCH 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Failed to checkout branch $BRANCH" }
  }

  Write-Host "`nConfigured remotes (before):"; git remote -v 2>&1

  # Add or update origin remote
  try { git remote remove origin 2>$null } catch {}
  git remote add origin $REPO_URL 2>&1
  if ($LASTEXITCODE -ne 0) { throw "Failed to add remote $REPO_URL. Check URL and access." }

  Write-Host "`nConfigured remotes (after):"; git remote -v 2>&1

  Write-Host "`nFetching origin..."
  git fetch origin 2>&1
  if ($LASTEXITCODE -ne 0) { throw "git fetch origin failed. Check network/auth." }

  # Try to rebase, but skip if main branch doesn't exist yet
  Write-Host "`nChecking for origin/main branch..."
  $mainExists = git rev-parse --verify "origin/main" 2>$null
  if ($mainExists) {
    Write-Host "`nRebasing onto origin/main..."
    git pull --rebase origin main 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git pull --rebase origin main failed. Resolve conflicts locally." }
  } else {
    Write-Host "origin/main doesn't exist yet (new repository). Skipping rebase."
  }

  Write-Host "`nPushing branch to origin..."
  git push --set-upstream origin $BRANCH 2>&1
  if ($LASTEXITCODE -ne 0) { throw "git push failed. Check remote access and authentication." }

  # Prepare PR body
  $pr_body = @"
This PR migrates legacy `self.state.get(...)` access patterns in `strategy/engine.py` to the new, type-safe `TradeLegManager` and `TradeLegV1` accessors.

Summary:
- **61** leg-related `self.state.get(...)` calls replaced with `trade_leg_manager.get_leg()` and type-safe helpers.
- Remaining **34** keys are non-leg config/phase values intentionally left unchanged.
- All unit tests and verification scripts pass locally.
- Migration artifacts (patch_migrate_*.diff and migration_suggestions.csv) are included in the `migration/` folder for audit.

Reviewer checklist:
- [ ] Confirm mapped fields for migrated legs (token, quantity, entry_price, strike, ref_premium).
- [ ] Verify mandatory leg handling raises clear errors and optional legs log warnings.
- [ ] Ensure each replacement includes a `# TODO REVIEW: migrated from state.get('KEY')` comment.
- [ ] Run unit tests and smoke verification locally; no regressions in trading flows.
- [ ] Validate no remaining unsafe `self.state.get(` usage in critical execution paths.
- [ ] Approve or request manual fixes for any `MAPPING=MANUAL` entries in migration_suggestions.csv

Notes: Run `pytest -q` and `./verify_migration.sh` locally before merging. If anything fails, revert with `git reset --hard HEAD~<n>` and re-run tests.
"@

  Set-Content -Path $TMP_BODY -Value $pr_body -Encoding utf8

  Write-Host "`nCreating PR via gh..."
  $ghOutput = gh pr create --base main --head $BRANCH --title $PR_TITLE --body-file $TMP_BODY 2>&1
  $ghExit = $LASTEXITCODE

  Remove-Item -Path $TMP_BODY -Force -ErrorAction SilentlyContinue

  if ($ghExit -ne 0) {
    Write-Host "gh returned an error:"
    Write-Host $ghOutput
    throw "gh pr create failed. Ensure GitHub CLI is installed and authenticated (gh auth login)."
  }

  Write-Host "`n✅ PR created successfully."
  Write-Host $ghOutput
} catch {
  Write-Host "`nERROR: $($_.Exception.Message)"
  Write-Host "Full error object: $_"
  exit 1
}
