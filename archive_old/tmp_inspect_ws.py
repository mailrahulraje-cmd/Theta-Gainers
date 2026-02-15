import inspect
try:
    import websocket
    print('websocket module file:', getattr(websocket, '__file__', str(websocket)))
    print('WebSocketApp.__init__ signature:', inspect.signature(websocket.WebSocketApp.__init__))
    print('\n--- WebSocketApp source (start) ---\n')
    src = inspect.getsource(websocket.WebSocketApp)
    print(src)
    print('\n--- WebSocketApp source (end) ---\n')
except Exception as e:
    import traceback
    traceback.print_exc()
    print('ERROR:', e)
