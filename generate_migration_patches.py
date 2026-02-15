from pathlib import Path
import re, csv, subprocess

SRC = Path("strategy/engine.py")
OUT_DIR = Path(".")
PATCH_PREFIX = "patch_migrate_"
CSV_FILE = "migration_suggestions.csv"

text = SRC.read_text(encoding="utf-8")
lines_list = text.splitlines(keepends=True)
occurrences = []

for m in re.finditer(r"self\.state\.get\(\s*'([^']+)'", text):
    key = m.group(1)
    line_no = text[:m.start()].count("\n") + 1
    occurrences.append((line_no, key))

def map_key(key):
    if key.startswith(("sell_", "buy_")) and ("token" in key or "strike" in key or "ref" in key or "leg" in key):
        leg = "_".join(key.split("_")[:2])
        return leg
    return None

patch_files = []
rows = []

for i, (ln, key) in enumerate(occurrences, start=1):
    leg_name = map_key(key)
    if leg_name is None:
        rows.append((ln, key, "(NO_PATCH)", "NO_AUTO_PATCH", "KEEP_AS_IS"))
        continue
    
    # Line index (0-based)
    target_idx = ln - 1
    target_line = lines_list[target_idx]
    
    # Find context: 3 lines before, 3 lines after
    ctx_start = max(0, target_idx - 3)
    ctx_end = min(len(lines_list), target_idx + 4)
    
    orig_lines = lines_list[ctx_start:ctx_end]
    
    # Replacement: just swap the state.get() call with leg accessor
    new_line = target_line.replace(f"self.state.get('{key}')", f"self.trade_leg_manager.get_leg('{leg_name}').token")
    
    # Build new lines (context + replaced line)
    new_lines = (
        lines_list[ctx_start:target_idx]
        + [new_line]
        + lines_list[target_idx+1:ctx_end]
    )
    
    # Build unified diff manually
    start_line = ctx_start + 1
    orig_count = len(orig_lines)
    new_count = len(new_lines)
    
    patch_content = "--- a/strategy/engine.py\n"
    patch_content += "+++ b/strategy/engine.py\n"
    patch_content += f"@@ -{start_line},{orig_count} +{start_line},{new_count} @@\n"
    
    # Add context and diff lines
    for idx, orig_line in enumerate(orig_lines):
        if idx == target_idx - ctx_start:
            patch_content += "-" + orig_line
            patch_content += "+" + new_line
        else:
            patch_content += " " + orig_line
    
    pfile = OUT_DIR / f"{PATCH_PREFIX}{i:03d}.diff"
    pfile.write_text(patch_content, encoding="utf-8")
    patch_files.append(str(pfile))
    rows.append((ln, key, str(pfile), "MIGRATED", "REVIEW_AND_APPLY"))

# Write CSV
with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["line_num", "state_key", "patch_file", "mapping_status", "recommendation"])
    for r in rows:
        w.writerow(r)

# Self-check first patch
if patch_files:
    first = patch_files[0]
    try:
        result = subprocess.run(["git", "apply", "--check", first], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"SAMPLE_PATCH_VALID: {first}")
        else:
            print(f"SAMPLE_PATCH_INVALID: {first}")
            print(result.stderr[:200] if result.stderr else "Unknown error")
    except Exception as e:
        print(f"SAMPLE_PATCH_CHECK_ERROR: {e}")
    
    print(f"\nGenerated {len(patch_files)} patches from {len(occurrences)} occurrences")
else:
    print("NO_PATCHES_CREATED")
