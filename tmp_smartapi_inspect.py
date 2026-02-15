import inspect, sys
out = []
try:
    import SmartApi
    out.append(f"SmartApi file: {getattr(SmartApi, '__file__', None)}")
    import SmartApi.smartWebSocketV2 as sw
    out.append(f"smartWebSocketV2 file: {getattr(sw, '__file__', None)}")
    src = inspect.getsource(sw)
    lines = src.splitlines()
    # Find WebSocketApp( occurrences
    for i, line in enumerate(lines, start=1):
        if 'WebSocketApp(' in line:
            st = max(1, i-3)
            ed = min(len(lines), i+6)
            out.append('\nWebSocketApp(...) snippet:')
            for j in range(st, ed+1):
                out.append(f"{j}: {lines[j-1]}")
    # Find on_close= occurrences
    for i, line in enumerate(lines, start=1):
        if 'on_close' in line and 'WebSocketApp' not in line:
            st = max(1, i-3)
            ed = min(len(lines), i+3)
            out.append('\non_close=(...) snippet:')
            for j in range(st, ed+1):
                out.append(f"{j}: {lines[j-1]}")
    # Inspect SmartWebSocketV2 class
    if hasattr(sw, 'SmartWebSocketV2'):
        cls = sw.SmartWebSocketV2
        try:
            src_cls = inspect.getsource(cls)
            out.append('\nSmartWebSocketV2 source (start):')
            out.extend(src_cls.splitlines())
            out.append('\nSmartWebSocketV2 source (end)')
        except Exception as e:
            out.append(f"Could not get SmartWebSocketV2 source: {e}")
        # _on_close
        if hasattr(cls, '_on_close'):
            func = getattr(cls, '_on_close')
            try:
                sig = inspect.signature(func)
                out.append(f"\nSmartWebSocketV2._on_close signature: {sig}")
            except Exception as e:
                out.append(f"Could not get signature: {e}")
            try:
                src_fn = inspect.getsource(func)
                out.append('\nSmartWebSocketV2._on_close source:')
                out.extend(src_fn.splitlines())
            except Exception as e:
                out.append(f"Could not get _on_close source: {e}")
        else:
            out.append('SmartWebSocketV2 has no attribute _on_close')
    else:
        out.append('smartWebSocketV2 has no SmartWebSocketV2 class')

except Exception as e:
    out.append('Import SmartApi failed: ' + repr(e))

# Write to file for retrieval
with open('tmp_smartapi_inspect_output.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))

print('Inspection complete — output written to tmp_smartapi_inspect_output.txt')
