import importlib
try:
    import SmartApi.smartWebSocketV2 as sw_mod
    importlib.reload(sw_mod)
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
    import websocket
    websocket.WebSocketApp.run_forever = lambda self, *a, **k: None
    print('Reloaded module, instantiating...')
    s = SmartWebSocketV2('AUTH','API','CLIENT','FEED')
    print('Calling connect() after reload...')
    s.connect()
    print('connect() returned')
except Exception as e:
    import traceback
    traceback.print_exc()
    print('ERROR:', e)
