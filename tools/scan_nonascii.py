import os

path = 'strategy/engine.py'
if not os.path.exists(path):
    print('MISSING', path); raise SystemExit(1)

b = open(path, 'rb').read()
matches = []
for i, by in enumerate(b):
    if by >= 0x80:
        start = max(0, i-10)
        end = min(len(b), i+10)
        context = b[start:end]
        # compute line number
        line_no = b.count(b"\n", 0, i) + 1
        matches.append((i, hex(by), line_no, context))
        if len(matches) >= 20:
            break

if not matches:
    print('No non-ASCII bytes found')
else:
    for pos, hx, line, ctx in matches:
        print(f'POS {pos} BYTE {hx} LINE {line} CTX {ctx!r}')
