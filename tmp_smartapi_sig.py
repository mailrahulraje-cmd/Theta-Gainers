import inspect
try:
    import SmartApi.smartWebSocketV2 as sw
    print('module:', sw.__file__)
    print('on_close assignment in connect:')
    # Show a few lines around the connect() definition to show assignment
    import inspect
    src = inspect.getsource(sw)
    for i, l in enumerate(src.splitlines(), start=1):
        if 'def connect' in l:
            start = max(1, i-3)
            end = min(len(src.splitlines()), i+12)
            for j in range(start, end+1):
                print(f"{j}: {src.splitlines()[j-1]}")
            break
    print('\nSmartWebSocketV2._on_close signature:', inspect.signature(sw.SmartWebSocketV2._on_close))
    print('\nSmartWebSocketV2._on_close source:')
    print(inspect.getsource(sw.SmartWebSocketV2._on_close))
except Exception as e:
    import traceback
    traceback.print_exc()
    print('ERROR:', e)
