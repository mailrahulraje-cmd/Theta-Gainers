import websocket
# Prevent network connect; we only need the assignment and prints inside SDK
websocket.WebSocketApp.run_forever = lambda self, *a, **k: None

try:
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
    print('Instantiating SmartWebSocketV2...')
    sw = SmartWebSocketV2('AUTH','API','CLIENT','FEED')
    print('Calling connect()...')
    sw.connect()
    print('connect() returned')
except Exception as e:
    import traceback
    traceback.print_exc()
    print('ERROR:', e)
