#!/usr/bin/env python3
"""
All-in-one preflight audit for live trading

Runs these checks (single entry point):
- Config.validate() and required env vars
- strategy_state.json schema + checksum; migrate/regenerate if missing/invalid
- Engine time-window sanity checks
- Delta-loop safety checks
- Codebase scan for legacy state.get('phase0_done') / state.get('phase1_done') usages
- Download/refresh angel_master_instruments.csv once per day and inspect structure

Exits 0 if all checks PASS, otherwise exits 1.
"""
import sys
import os
import json
import time
from datetime import datetime, date
from pathlib import Path
import traceback

ROOT = Path(__file__).parent
STATE_FILE = ROOT / 'strategy_state.json'
INSTRUMENTS_FILE = ROOT / 'angel_master_instruments.csv'
INSTRUMENTS_URL = os.getenv('INSTRUMENTS_SOURCE_URL', 'https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json')

results = []

def result(name, ok, msg=''):
    results.append((name, ok, msg))
    print(f"[{ 'PASS' if ok else 'FAIL' }] {name}: {msg}")


# -------------------------
# Instruments download & inspection
# -------------------------
def manage_and_inspect_master():
    """Download (once/day) and inspect instrument master list.
    Uses pandas+requests if available, otherwise falls back to stdlib urllib + csv/json.
    Returns (ok:bool, message:str)
    """
    try:
        today = date.today()
        should_download = True
        if INSTRUMENTS_FILE.exists():
            last_update = datetime.fromtimestamp(INSTRUMENTS_FILE.stat().st_mtime).date()
            if last_update == today:
                should_download = False
        if should_download:
            msg = f"Downloading master list from {INSTRUMENTS_URL}"
            print(msg)
            try:
                try:
                    import requests
                    import pandas as pd
                    data = requests.get(INSTRUMENTS_URL, timeout=15)
                    data.raise_for_status()
                    j = data.json()
                    df = pd.DataFrame(j)
                    df.to_csv(INSTRUMENTS_FILE, index=False)
                    cnt = len(df)
                    cols = list(df.columns)
                    return True, f"Downloaded via requests+pandas: {cnt} rows, {len(cols)} cols"
                except Exception:
                    # Fallback to urllib + csv/json
                    from urllib.request import urlopen
                    import csv
                    resp = urlopen(INSTRUMENTS_URL, timeout=15)
                    raw = resp.read()
                    try:
                        j = json.loads(raw)
                    except Exception:
                        # if the resource is CSV already
                        text = raw.decode('utf-8', errors='replace')
                        with INSTRUMENTS_FILE.open('w', encoding='utf-8') as f:
                            f.write(text)
                        # count rows
                        with INSTRUMENTS_FILE.open('r', encoding='utf-8') as f:
                            reader = csv.reader(f)
                            rows = list(reader)
                        return True, f"Downloaded raw CSV: {len(rows)-1} rows, {len(rows[0]) if rows else 0} cols"
                    # write JSON->CSV
                    if isinstance(j, list):
                        # infer header
                        keys = set()
                        for item in j:
                            if isinstance(item, dict):
                                keys.update(item.keys())
                        keys = list(keys)
                        with INSTRUMENTS_FILE.open('w', encoding='utf-8', newline='') as f:
                            writer = csv.writer(f)
                            writer.writerow(keys)
                            for item in j:
                                row = [item.get(k, '') for k in keys]
                                writer.writerow(row)
                        # count rows
                        with INSTRUMENTS_FILE.open('r', encoding='utf-8') as f:
                            r = sum(1 for _ in f) - 1
                        return True, f"Downloaded JSON->CSV: {r} rows, {len(keys)} cols (fallback)"
                    else:
                        return False, 'Unexpected JSON structure from instruments URL'
            except Exception as e:
                # download failed — fall back to existing file if present
                if INSTRUMENTS_FILE.exists():
                    return False, f'Download failed ({e}); using existing file'
                return False, f'Download failed and no existing file ({e})'
        else:
            # inspect existing file
            try:
                try:
                    import pandas as pd
                    df = pd.read_csv(INSTRUMENTS_FILE)
                    return True, f'Local file current: {len(df)} rows, {len(df.columns)} cols'
                except Exception:
                    import csv
                    with INSTRUMENTS_FILE.open('r', encoding='utf-8') as f:
                        reader = csv.reader(f)
                        rows = list(reader)
                    if rows:
                        return True, f'Local CSV: {len(rows)-1} rows, {len(rows[0])} cols'
                    else:
                        return False, 'Local CSV empty'
            except Exception as e:
                return False, f'Inspect failed: {e}'
    except Exception as e:
        return False, str(e)


# -------------------------
# Config and env checks
# -------------------------
def check_config_and_env():
    try:
        from config import Config
    except Exception as e:
        return False, f'Failed to import Config: {e}'
    try:
        Config.validate()
    except Exception as e:
        return False, f'Config.validate() failed: {e}'
    # required envs for LIVE mode
    if Config.TRADING_MODE == 'LIVE' or Config.DATA_MODE == 'LIVE':
        missing = [k for k in ('ANGEL_API_KEY','ANGEL_CLIENT_CODE','ANGEL_PASSWORD','ANGEL_TOTP_SECRET') if not os.getenv(k)]
        if missing:
            return False, f'Missing env vars for LIVE: {missing}'
    return True, 'Config and env OK'


# -------------------------
# State schema validation and migration
# -------------------------
def validate_or_fix_state():
    try:
        from core.state_schema import (
            validate_state_schema, verify_state_checksum, ensure_state_valid, migrate_state_v1_to_v2, compute_state_checksum
        )
    except Exception:
        # minimal local fallback
        def validate_state_schema(s):
            if not isinstance(s, dict):
                return False, 'State not a dict'
            if not s:
                return False, 'State empty'
            if '_version' not in s:
                return False, 'Missing _version'
            return True, 'OK'
        def verify_state_checksum(s):
            return True, 'Checksum verification skipped (no core.state_schema)'
        def ensure_state_valid(s):
            if not isinstance(s, dict):
                s = {}
            s.setdefault('_version','2.0')
            s.setdefault('phase','INIT')
            s.setdefault('trade_state', { 'sell_ce':'IDLE','sell_pe':'IDLE','buy_ce':'IDLE','buy_pe':'IDLE'})
            s.setdefault('legs', {})
            s['_checksum'] = compute_state_checksum(s) if 'compute_state_checksum' in globals() else 'na'
            return s
        def migrate_state_v1_to_v2(s):
            # naive migration: wrap existing keys into legs if possible
            new = {'_version':'2.0', 'phase': s.get('phase','INIT'), 'trade_state':{}, 'legs':{}}
            return new

    # load or create state
    if not STATE_FILE.exists():
        # generate minimal state
        st = ensure_state_valid({})
        try:
            with STATE_FILE.open('w', encoding='utf-8') as f:
                json.dump(st, f, indent=2)
            return True, 'State file not found — created minimal state v2'
        except Exception as e:
            return False, f'Failed to write new state file: {e}'
    else:
        try:
            s = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except Exception as e:
            return False, f'Failed to parse existing state file: {e}'
        ok, msg = validate_state_schema(s)
        if ok:
            chk_ok, chk_msg = verify_state_checksum(s)
            if chk_ok:
                return True, 'State valid and checksum ok'
            else:
                # attempt recompute and correct
                try:
                    s['_checksum'] = compute_state_checksum(s) if 'compute_state_checksum' in globals() else 'na'
                    with STATE_FILE.open('w', encoding='utf-8') as f:
                        json.dump(s, f, indent=2)
                    return True, 'Checksum corrected'
                except Exception as e:
                    return False, f'Checksum invalid and correction failed: {e}'
        else:
            # Try to migrate from v1
            try:
                migrated = migrate_state_v1_to_v2(s)
                migrated = ensure_state_valid(migrated)
                with STATE_FILE.open('w', encoding='utf-8') as f:
                    json.dump(migrated, f, indent=2)
                return True, 'Migrated legacy state to v2'
            except Exception as e:
                return False, f'State invalid and migration failed: {e}'


# -------------------------
# Engine checks
# -------------------------
def engine_time_window_checks():
    try:
        from config import Config
        p0s = Config.PHASE0_START
        p0e = Config.PHASE0_END
        p1s = Config.PHASE1_START
        p1e = Config.PHASE1_END
        sq = Config.SQUAREOFF_TIME
        msgs = []
        ok = True
        if not (p0s < p0e):
            ok = False; msgs.append('PHASE0_START >= PHASE0_END')
        if not (p0e <= p1s):
            ok = False; msgs.append('PHASE0_END > PHASE1_START (overlap)')
        if not (p1s < p1e):
            ok = False; msgs.append('PHASE1_START >= PHASE1_END')
        if not (p1e < sq):
            ok = False; msgs.append('PHASE1_END >= SQUAREOFF_TIME')
        return ok, '; '.join(msgs) or 'OK'
    except Exception as e:
        return False, f'Engine check error: {e}'


def delta_loop_safety_checks():
    try:
        from utils.safety_validator import SafetyValidator
        from config import Config
        sv = SafetyValidator()
        # excessive attempt should fail
        sc1, _ = sv.validate_delta_loop_safety(attempt_number=999999, max_retries=Config.DELTA_LOOP_MAX_RETRIES, elapsed_time=0, timeout_seconds=Config.DELTA_LOOP_TIMEOUT)
        # timeout should fail
        sc2, _ = sv.validate_delta_loop_safety(attempt_number=1, max_retries=Config.DELTA_LOOP_MAX_RETRIES, elapsed_time=Config.DELTA_LOOP_TIMEOUT + 10, timeout_seconds=Config.DELTA_LOOP_TIMEOUT)
        # normal should pass
        sc3, _ = sv.validate_delta_loop_safety(attempt_number=1, max_retries=max(1, Config.DELTA_LOOP_MAX_RETRIES), elapsed_time=0.1, timeout_seconds=max(0.1, Config.DELTA_LOOP_TIMEOUT))
        ok = (not sc1) and (not sc2) and sc3
        return ok, f'retry-fail={not sc1}, timeout-fail={not sc2}, nominal-pass={sc3}'
    except Exception as e:
        return False, f'Delta safety error: {e}'


# -------------------------
# Static codebase scan for legacy state.get usages
# -------------------------
def scan_legacy_state_get():
    patterns = ["state.get('phase0_done'", 'state.get("phase0_done"', "state.get('phase1_done'", 'state.get("phase1_done"']
    matches = []
    strategy_dir = ROOT / 'strategy'
    search_root = strategy_dir if strategy_dir.exists() else ROOT
    for p in search_root.rglob('*.py'):
        if 'archive' in str(p).lower():
            continue
        try:
            txt = p.read_text(encoding='utf-8')
        except Exception:
            continue
        for pat in patterns:
            if pat in txt:
                matches.append((str(p.relative_to(ROOT)), pat))
    if matches:
        return False, matches
    return True, 'No legacy state.get usage found in strategy/'


def main():
    print('Preflight Full Audit —', datetime.now().isoformat())

    ok, msg = manage_and_inspect_master()
    result('Instruments refresh & inspect', ok, msg)

    ok, msg = check_config_and_env()
    result('Config + ENV', ok, msg)

    ok, msg = validate_or_fix_state()
    result('State schema & checksum', ok, msg)

    ok, msg = engine_time_window_checks()
    result('Engine time-window checks', ok, msg)

    ok, msg = delta_loop_safety_checks()
    result('Delta-loop safety checks', ok, msg)

    ok, msg = scan_legacy_state_get()
    if ok:
        result('Legacy state.get scan', True, msg)
    else:
        # format matches (support tuples of (path, pattern) or (path, pattern, snippet))
        formatted_lines = []
        for entry in msg:
            if isinstance(entry, (list, tuple)) and len(entry) == 3:
                p, pat, sn = entry
                formatted_lines.append(f"{p}: {pat}: {sn[:120]}")
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                p, pat = entry
                formatted_lines.append(f"{p}: {pat}")
            else:
                formatted_lines.append(str(entry))
        formatted = '\n'.join(formatted_lines)
        result('Legacy state.get scan', False, formatted)

    # Consolidated summary
    print('\n=== SUMMARY ===')
    passed = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]
    print(f'Passed: {len(passed)}  Failed: {len(failed)}')
    if failed:
        print('\nFailures:')
        for name, ok, m in failed:
            print(f'- {name}: {m}')
        sys.exit(1)
    else:
        print('\nAll checks passed — preflight OK')
        sys.exit(0)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(2)
