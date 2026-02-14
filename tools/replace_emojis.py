import io
import sys
p = 'strategy/engine.py'
try:
    s = open(p, 'r', encoding='utf-8').read()
except Exception as e:
    print('READ-ERR', e); raise
repls = {
    '': '[OK]',
    '': '[ERROR]',
    '': '[START]',
    '': '[STOP]',
    '': '[PHASE]',
    '': '->',
    '': '[WARN]',
    '': '[WARN]',
    '': 'Rs',
}
for k, v in repls.items():
    if k in s:
        s = s.replace(k, v)
        print('Replaced', k, '->', v)
open(p, 'w', encoding='utf-8').write(s)
print('Done')
