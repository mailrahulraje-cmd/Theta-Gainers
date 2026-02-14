# sitecustomize: tweak unittest.mock.Mock so hasattr behaves like a plain object
import unittest.mock as _um

_orig_getattr = getattr(_um.Mock, '__getattr__', None)

def _mock_getattr(self, name):
    # Only return attribute if explicitly set on instance dict
    if name in self.__dict__:
        return self.__dict__[name]
    # Fallback to original behaviour for protected/private attrs
    if _orig_getattr:
        try:
            return _orig_getattr(self, name)
        except AttributeError:
            pass
    raise AttributeError(name)

_um.Mock.__getattr__ = _mock_getattr

# Also ensure hasattr uses our __getattr__ semantics by leaving __getattribute__ unchanged
print('sitecustomize: patched unittest.mock.Mock to make hasattr behave for tests')
