import inspect
try:
    import SmartApi.smartWebSocketV2 as sw
    print('SmartApi.smartWebSocketV2 file:', getattr(sw, '__file__', str(sw)))
    src = inspect.getsource(sw)
    lines = src.splitlines()
    for i, line in enumerate(lines, start=1):
        if 'WebSocketApp' in line or 'on_close' in line or 'on_error' in line:
            print(f"{i}: {line}")
    # show snippet around first WebSocketApp(
    for idx, line in enumerate(lines):
        if 'WebSocketApp(' in line:
            st = max(0, idx-3)
            ed = min(len(lines), idx+6)
            print('\n--- snippet ---')
            print('\n'.join(f"{j+1}: {lines[j]}" for j in range(st, ed)))
            break
except Exception as e:
    import traceback
    traceback.print_exc()
    print('ERROR:', e)
