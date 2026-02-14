import os
root='.'
changed=0
for dirpath, dirs, files in os.walk(root):
    # skip .venv and __pycache__
    if '.venv' in dirpath or '__pycache__' in dirpath:
        continue
    for fn in files:
        if not fn.endswith('.py'):
            continue
        path = os.path.join(dirpath, fn)
        try:
            s = open(path, 'r', encoding='utf-8').read()
        except Exception as e:
            print('READ-ERR', path, e)
            continue
        out = []
        removed = 0
        for ch in s:
            if ord(ch) < 128:
                out.append(ch)
            else:
                removed += 1
        if removed > 0:
            open(path, 'w', encoding='utf-8').write(''.join(out))
            print('Cleaned', path, 'removed', removed, 'chars')
            changed += 1
print('Done. Files changed:', changed)
