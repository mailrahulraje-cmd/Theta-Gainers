from pathlib import Path
p=Path('c:/Users/SANU/Desktop/New folder (2)/12 Feb Onwards/trading_system_fixed/live_broker.py')
s=p.read_text()
lines=s.splitlines()
stack=[]
for i,l in enumerate(lines,1):
    stripped=l.strip()
    if stripped.startswith('try:'):
        stack.append(('try',i))
    elif stripped.startswith('except') or stripped.startswith('finally'):
        if stack:
            stack.pop()
        else:
            print('Extra except/finally at',i)
            break
if stack:
    print('Unmatched try at',stack[-1][1])
else:
    print('All matched')
