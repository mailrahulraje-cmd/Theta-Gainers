import inspect
from core import feed

# Use fallback SmartWebSocketV2 from core.feed (used when SmartAPI not installed)
sw = feed.SmartWebSocketV2()

# Create a dummy UnifiedFeed-like object with _on_close method
class DummyFeed:
    def _on_close(self, wsapp):
        pass

dummy = DummyFeed()

# Simulate assignment from UnifiedFeed instance: sw.on_close = dummy._on_close
sw.on_close = dummy._on_close

print('on_close reference:', sw.on_close)
print('type:', type(sw.on_close))
print('has __self__:', hasattr(sw.on_close, '__self__'))
print('bound to:', getattr(sw.on_close, '__self__', None))
print('inspect.signature:', inspect.signature(sw.on_close))

# Also simulate assigning the unbound function
sw.on_close = DummyFeed._on_close
print('\nAssigned unbound function:')
print('on_close reference:', sw.on_close)
print('type:', type(sw.on_close))
print('has __self__:', hasattr(sw.on_close, '__self__'))
print('bound to:', getattr(sw.on_close, '__self__', None))
try:
    print('inspect.signature:', inspect.signature(sw.on_close))
except Exception as e:
    print('signature error:', e)
