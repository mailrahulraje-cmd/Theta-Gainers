# Trading System Cleanup & Organization Script
# Categorizes and organizes files into:
# - Keep: Production code, essential tests, core documentation
# - Archive: Old reports, phase completions, debug artifacts, migration patches
# - Delete: Zero-size logs, test data, temporary state files

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

# Define the working directory
$workDir = (Get-Location).Path
$archiveDir = Join-Path $workDir "archive_old"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Trading System Cleanup & Organization" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Working Directory: $workDir`n" -ForegroundColor Gray

# ============================================================================
# CATEGORIZATION RULES
# ============================================================================

# Files to KEEP (production code, essential tests, core docs)
$filesToKeep = @(
    # Production source code
    "main.py", "config.py", "constants.py", "contract.py",
    "live_broker.py", "paper_broker.py", "liveness_layer.py",
    
    # Core test files
    "test_tradeleg_v1.py", "test_trade_leg_manager.py",
    "test_final_validation.py", "test_production_ready.py",
    "test_state_validation.py", "test_state_integration.py",
    "test_e2e_tradeleg_integration.py", "test_liveness_layer.py",
    "test_websocket_fix.py", "test_live_network_hardening.py",
    
    # Verification scripts (essential for production)
    "verify_state_access.py", "verify_can_trade.py", "verify_state_migration_fix.py",
    "check_syntax.py", "check_entry_readiness.py", "run_network_tests.py",
    "validate.py",
    
    # Essential documentation
    "README_PRODUCTION_READY.md", "QUICK_START.md", "GO-LIVE_APPROVAL.md",
    "MASTER_DEPLOYMENT_REFERENCE.md", "READY_TO_DEPLOY.md",
    "IMMEDIATE_DEPLOYMENT_GUIDE.md", 
    
    # Migration reference (needed for context)
    "migration_suggestions.csv",
    
    # Configuration files
    ".env", ".gitignore", "sitecustomize.py",
    
    # Patch files (keep as reference)
    "engine-add-tradeleg-manager.patch", "engine-replace-sell-ce.patch"
)

# Directories to KEEP (source code structure)
$dirsToKeep = @(
    ".git", ".venv", ".vscode", ".pytest_cache",
    "core", "strategy", "utils", "tools", "logs", "strategy_logs", "tick_data"
)

# Files to ARCHIVE (old reports, debug, temporary, phases)
$filesToArchive = @(
    # Phase completion reports
    "PHASE_0_1_CRITICAL_WINDOW_IMPLEMENTATION.md",
    "PHASE_0_1_DEADLOCK_DIAGNOSIS.md",
    "PHASE_0_1_DEADLOCK_VISUAL_MAP.md",
    "PHASE_0_1_DEBUG_CHECKLIST.md",
    "PHASE_0_1_DEPLOYMENT_STATUS.md",
    "PHASE_0_1_DIAGNOSIS_COMPLETE.md",
    "PHASE_0_1_DIAGNOSIS_INDEX.md",
    "PHASE_0_1_FINAL_IMPLEMENTATION_REPORT.md",
    "PHASE_0_1_IMPLEMENTATION_INDEX.md",
    "PHASE_0_1_NOTIFIER_ORDER_BLOCKING.md",
    "PHASE_0_1_OPERATIONS_GUIDE.md",
    "PHASE_0_1_QUICK_REFERENCE.md",
    "PHASE_0_1_TRACE.py",
    "PHASE_0_1_TRACE_SUMMARY.md",
    "PHASE1_CHANGELOG.txt",
    "PHASE1_COMPLETION_SUMMARY.txt",
    "PHASE1_IMPLEMENTATION_COMPLETE.md",
    "PHASE1_VALIDATION_GUIDE.py",
    "PHASE1_AND_GATE_ANALYSIS_AND_FIX.md",
    "PHASE1_FIX_IMPLEMENTATION_SUMMARY.md",
    "PHASE2_STABILIZATION_COMPLETE.md",
    "PHASE_COMPLETION_SUMMARY.md",
    
    # Redundant/old status reports
    "ABSOLUTE_FINAL_SYSTEM_STATUS.md",
    "COMPLETE_IMPLEMENTATION_SUMMARY.md",
    "COMPLETE_SYSTEM_AUDIT.md",
    "COMPREHENSIVE_AUDIT_REPORT.md",
    "CRITICAL_BUGS_FIXED.md",
    "CRITICAL_BUGS_VERIFIED_FIXED.md",
    "CRITICAL_REMAINING_ISSUES.md",
    "DEFINITIVE_FINAL_COMPLETION_STATUS.md",
    "DELIVERABLES_MANIFEST.md",
    "DELIVERABLES_SUMMARY.md",
    "DELIVERY_PACKAGE_SUMMARY.md",
    "DEPLOYMENT_ARTIFACTS_INDEX.md",
    "DEPLOYMENT_SUMMARY.md",
    "FINAL_AUDIT_COMPLETION_REPORT.md",
    "FINAL_DELIVERY_SUMMARY.md",
    "FINAL_DEPLOYMENT_VERIFICATION.md",
    "FINAL_IMPLEMENTATION_ROADMAP.md",
    "FINAL_RECOMMENDATION.md",
    "IMPLEMENTATION_CHECKLIST.md",
    "IMPLEMENTATION_COMPLETION.md",
    "IMPLEMENTATION_NOTES_STATE_MIGRATION_FIX.md",
    "IMPLEMENTATION_SUMMARY.md",
    "MIGRATION_COMPLETION_REPORT.md",
    "MIGRATION_EVIDENCE.md",
    "MIGRATION_PLAN.md",
    "STEP_1_COMPLETION_SUMMARY.md",
    "STEP_2_COMPLETION_SUMMARY.md",
    "STEP_3_FINAL_COMPLETION_REPORT.md",
    "STEP_3_INTEGRATION_SUMMARY.md",
    
    # Old deployment/notification docs
    "CHANGELOG_NOTIFICATIONS.md",
    "HARDENED_WEBSOCKET_RECONNECT_IMPLEMENTATION.md",
    "HARDENING_COMPLETE.md",
    "INFINITE_LOOP_FIX.md",
    "ISSUE_4_COMPLETE_SOLUTION.md",
    "LIVENESS_ARCHITECTURE_DIAGRAM.md",
    "LIVENESS_EXECUTIVE_SUMMARY.md",
    "LIVENESS_FINAL_CONFIRMATION.md",
    "LIVENESS_LAYER_FILE_INDEX.md",
    "LIVENESS_LAYER_IMPLEMENTATION.md",
    "LIVENESS_QUICK_START.md",
    "LIVE_DEPLOYMENT_EXECUTION_SUMMARY.md",
    "LIVE_SAFETY_DEPLOYMENT_GUIDE.md",
    "LIVE_SAFETY_VALIDATION_COMPLETE.md",
    "LOCAL_DEPLOYMENT_EXECUTION_RECORD.md",
    "LOCAL_DEPLOYMENT_GUIDE.md",
    "NOTIFICATION_IMPROVEMENTS.md",
    "NOTIFIER_LOCK_SAFETY_AUDIT.md",
    "NOTIFIER_QUICK_REFERENCE.md",
    "NOTIFIER_SAFETY_EXECUTIVE_SUMMARY.md",
    "NOTIFIER_VERIFICATION_SUMMARY.md",
    "STALE_DATA_PREVENTION_FINAL_REPORT.md",
    "STALE_DATA_PREVENTION_IMPLEMENTATION.md",
    "TRADING_SAFETY_GATE_IMPLEMENTATION_COMPLETE.md",
    
    # Strategy inspection/analysis (already implemented, not needed)
    "STRATEGY_FLOW_DIAGRAMS_AND_MATRICES.md",
    "STRATEGY_INSPECTION_COMPLETION_REPORT.md",
    "STRATEGY_INSPECTION_DELIVERY_SUMMARY.md",
    "STRATEGY_INSPECTION_FINAL_SUMMARY.md",
    "STRATEGY_INSPECTION_VISUAL_SUMMARY.md",
    "STRATEGY_LOGIC_INSPECTION.md",
    "STRATEGY_LOGIC_INSPECTION_INDEX.md",
    "READ_ME_STRATEGY_INSPECTION_FIRST.md",
    "TRADELEG_ARCHITECTURE_OVERVIEW.md",
    "TRADELEG_V1_QUICK_REFERENCE.md",
    "TRADELEG_V1_USAGE_GUIDE.py",
    "TRADE_ENTRY_DEBUGGING.md",
    "TRADE_ENTRY_DEBUGGING.md",
    
    # Migration patches (applied, not needed anymore)
    "patch_migrate_014.diff", "patch_migrate_015.diff", "patch_migrate_016.diff",
    "patch_migrate_017.diff", "patch_migrate_018.diff", "patch_migrate_019.diff",
    "patch_migrate_020.diff", "patch_migrate_021.diff", "patch_migrate_022.diff",
    "patch_migrate_023.diff", "patch_migrate_024.diff", "patch_migrate_028.diff",
    "patch_migrate_029.diff", "patch_migrate_030.diff", "patch_migrate_032.diff",
    "patch_migrate_033.diff", "patch_migrate_034.diff", "patch_migrate_035.diff",
    "patch_migrate_036.diff", "patch_migrate_037.diff", "patch_migrate_038.diff",
    "patch_migrate_039.diff", "patch_migrate_040.diff", "patch_migrate_041.diff",
    "patch_migrate_042.diff", "patch_migrate_043.diff", "patch_migrate_044.diff",
    "patch_migrate_046.diff", "patch_migrate_047.diff", "patch_migrate_048.diff",
    "patch_migrate_049.diff", "patch_migrate_050.diff", "patch_migrate_053.diff",
    "patch_migrate_054.diff", "patch_migrate_055.diff", "patch_migrate_057.diff",
    "patch_migrate_058.diff", "patch_migrate_059.diff", "patch_migrate_060.diff",
    "patch_migrate_063.diff", "patch_migrate_064.diff", "patch_migrate_065.diff",
    "patch_migrate_066.diff", "patch_migrate_067.diff", "patch_migrate_068.diff",
    "patch_migrate_069.diff", "patch_migrate_070.diff", "patch_migrate_075.diff",
    "patch_migrate_076.diff", "patch_migrate_077.diff", "patch_migrate_078.diff",
    "patch_migrate_079.diff", "patch_migrate_080.diff", "patch_migrate_085.diff",
    "patch_migrate_086.diff", "patch_migrate_088.diff", "patch_migrate_089.diff",
    "patch_migrate_091.diff", "patch_migrate_092.diff",
    
    # Setup/migration scripts (one-time use, not production)
    "apply_all_migrations.py",
    "apply_engine_edits.py",
    "apply_line_migrations.py",
    "apply_safe_migrations.py",
    "extract_remaining_keys.py",
    "find_unmatched_try.py",
    "generate_migration_patches.py",
    "inventory_state_keys.py",
    "search_state_get.py",
    
    # Diagnostic/temporary scripts
    "diagnose_no_trades.py",
    "diagnose_trade_entry.py",
    "tmp_debug_assign.py",
    "tmp_inspect_smartws.py",
    "tmp_inspect_ws.py",
    "tmp_invoke_patch.py",
    "tmp_runtime_inspect.py",
    "tmp_runtime_reload.py",
    "tmp_smartapi_inspect.py",
    "tmp_verify_patch.py",
    
    # Old reference documentation
    "INDEX.md",
    "PROJECT_COMPLETION_STATUS.md",
    "PROJECT_VISUAL_SUMMARY.md",
    "QUICK_FIX_SUMMARY.md",
    "README_FINAL_COMPLETE.md",
    "README_TRADELEG_V1_PROJECT.md",
    "READ_ME_STRATEGY_INSPECTION_FIRST.md",
    "REFACTORING_IMPLEMENTATION_GUIDE.md",
    "REFACTORING_SUMMARY.md",
    "REMAINING_KEYS_MIGRATION_PLAN.md",
    "VALIDATION_REPORT.md",
    "VERIFICATION_CHECKLIST.md",
    "CONFIG_PARAMETER_VERIFICATION_REPORT.md",
    "CAN_TRADE_SAFETY_GATE_FINAL_REPORT.md",
    
    # Old deployment scripts
    "create_pr.ps1"
)

# Files to DELETE (truly redundant, zero-size logs, test data)
$filesToDelete = @(
    # Old logs and data
    "order_journal.log",
    "startup_diagnostics.txt",
    "filelist.txt",
    "tmp_smartapi_inspect_output.txt",
    
    # Test state and trade files
    "test_state.json",
    "test_state_2.json",
    "test_state_3.json",
    "strategy_state.json",
    "test_trades.csv",
    "test_trades_2.csv",
    "paper_trades.csv",
    "paper_trades.csv.backup.20260215_164545",
    
    # Old test files (superseded)
    "test_fixes.py",
    "test_phase1.py",
    "test_phase1_fixes.py",
    "verify_fixes.py",
    "verify_phase_0_1_blocking.py",
    "verify_phase_aware_retry.py",
    "verify_stale_data.py"
)

# ============================================================================
# EXECUTION
# ============================================================================

$keptCount = 0
$archivedCount = 0
$deletedCount = 0
$skippedDirs = 0

# Create archive directory
if (-not (Test-Path $archiveDir)) {
    Write-Host "Creating archive directory: archive_old/" -ForegroundColor Green
    New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
    Write-Host ""
}

# Get all items in the working directory
$allItems = Get-ChildItem -Path $workDir -Force | Where-Object { $_.Name -ne "archive_old" }

Write-Host "ANALYZING FILES AND DIRECTORIES..." -ForegroundColor Yellow
Write-Host ""

foreach ($item in $allItems) {
    $itemName = $item.Name
    
    # Skip directories (except for archiving into archive_old)
    if ($item.PSIsContainer) {
        if ($dirsToKeep -contains $itemName) {
            $keptCount++
            Write-Host "  [KEEP] $itemName/" -ForegroundColor Green
        } else {
            # Check if it's a known non-critical directory
            if ($itemName -in @("__pycache__")) {
                # Skip __pycache__ silently, it will be cleaned by Python
                $skippedDirs++
            } else {
                $keptCount++
                Write-Host "  [KEEP] $itemName/" -ForegroundColor Green
            }
        }
        continue
    }
    
    # Check if file should be kept
    if ($filesToKeep -contains $itemName) {
        $keptCount++
        Write-Host "  [KEEP] $itemName" -ForegroundColor Green
        continue
    }
    
    # Check if file should be deleted
    if ($filesToDelete -contains $itemName) {
        Write-Host "  [DELETE] $itemName (removing)" -ForegroundColor Red
        Remove-Item -Path (Join-Path $workDir $itemName) -Force -ErrorAction SilentlyContinue
        $deletedCount++
        continue
    }
    
    # Check if file should be archived
    if ($filesToArchive -contains $itemName) {
        Write-Host "  [ARCHIVE] $itemName → archive_old/" -ForegroundColor Cyan
        $destPath = Join-Path $archiveDir $itemName
        Move-Item -Path (Join-Path $workDir $itemName) -Destination $destPath -Force -ErrorAction SilentlyContinue
        $archivedCount++
        continue
    }
    
    # Default: keep unknown files (be conservative)
    $keptCount++
    Write-Host "  [KEEP] $itemName (unclassified, keeping for safety)" -ForegroundColor Gray
}

# ============================================================================
# SUMMARY
# ============================================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "CLEANUP COMPLETE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📊 SUMMARY:" -ForegroundColor Yellow
Write-Host "  ✓ Kept:       $keptCount files/dirs (production & essential)" -ForegroundColor Green
Write-Host "  📦 Archived:  $archivedCount files → archive_old/" -ForegroundColor Cyan
Write-Host "  🗑  Deleted:   $deletedCount files (temp/log/test data)" -ForegroundColor Red
Write-Host ""
Write-Host "📁 Folder structure preserved:" -ForegroundColor Yellow
Write-Host "  - core/, strategy/, utils/, tools/ (source code)" -ForegroundColor Gray
Write-Host "  - logs/, strategy_logs/, tick_data/ (runtime data)" -ForegroundColor Gray
Write-Host "  - .git/, .venv/, .vscode/ (environment)" -ForegroundColor Gray
Write-Host "  - archive_old/ (old reports & patches)" -ForegroundColor Gray
Write-Host ""
Write-Host "✅ Your project is now clean and organized!" -ForegroundColor Green
Write-Host ""
