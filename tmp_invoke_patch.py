# Import core.feed to ensure patches are applied, then instantiate SDK and call _on_close
try:
    from core import feed
    # SmartWebSocketV2 should be the SDK class from SmartApi (patched by core.feed)
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2

    print('Creating SmartWebSocketV2 instance (patched)...')
    sw = SmartWebSocketV2('AUTH','API','CLIENT','FEED')
    print('Invoking patched _on_close directly...')
    # Call the patched wrapper to capture _original_on_close runtime object
    try:
        sw._on_close(None)
        print('Called sw._on_close(None) successfully')
    except Exception as e:
        import traceback
        traceback.print_exc()
        print('ERROR when calling sw._on_close:', e)

except Exception as e:
    import traceback
    traceback.print_exc()
    print('ERROR:', e)
