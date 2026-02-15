import ast, sys
p = 'c:/Users/SANU/Desktop/New folder (2)/12 Feb Onwards/trading_system_fixed/live_broker.py'
try:
    with open(p, 'r', encoding='utf-8') as f:
        s = f.read()
    ast.parse(s)
    print('OK')
except Exception as e:
    print('ERROR', type(e).__name__, e)
    import traceback
    traceback.print_exc()
    sys.exit(1)
