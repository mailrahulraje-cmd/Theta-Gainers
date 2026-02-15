import re
with open("strategy/engine.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

print("=== grep -nR self.state.get( ===")
for i, line in enumerate(lines, 1):
    if "self.state.get(" in line:
        print(f"{i}:{line.rstrip()}")

print("\n=== grep -nR state.get( (excluding self.state) ===")
for i, line in enumerate(lines, 1):
    if "state.get(" in line and "self.state.get(" not in line:
        print(f"{i}:{line.rstrip()}")

print("\n=== sed -n '1685,1695p' strategy/engine.py ===")
for i in range(1685-1, 1695):
    if i < len(lines):
        print(f"{i+1}:{lines[i].rstrip()}")

print("\n=== sed -n '1729,1736p' strategy/engine.py ===")
for i in range(1729-1, 1736):
    if i < len(lines):
        print(f"{i+1}:{lines[i].rstrip()}")
