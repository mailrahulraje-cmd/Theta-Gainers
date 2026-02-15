# Quick verification: import patched core.feed, instantiate SmartWebSocketV2,
# set a dummy on_close to observe that bound_original calls through correctly.
try:
    import importlib
    import core.feed as feed_mod
    importlib.reload(feed_mod)
    from SmartApi import smartWebSocketV2 as sw_mod
    importlib.reload(sw_mod)
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2

    print('Creating SmartWebSocketV2 instance (patched)...')
    sw = SmartWebSocketV2('AUTH','API','CLIENT','FEED')

    # Set a dummy on_close to verify original behavior
    def dummy_on_close(wsapp, *a, **k):
        print('dummy_on_close called with', wsapp, a, k)

    sw.on_close = dummy_on_close
    print('Calling patched _on_close with ws=WSAPP_OBJ')
    sw._on_close('WSAPP_OBJ')
    print('Patched _on_close returned (no TypeError)')
except Exception as e:
    import traceback
    traceback.print_exc()
    print('ERROR:', e)
