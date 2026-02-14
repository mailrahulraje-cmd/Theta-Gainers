import types

from config import Config


class DummyState:
    def __init__(self):
        self._data = {}

    def get(self, k, default=None):
        return self._data.get(k, default)

    def set(self, k, v):
        self._data[k] = v


class DummyNotifier:
    def __init__(self):
        self.messages = []

    def send_trade_log(self, msg):
        self.messages.append(msg)


def make_livebroker_with_api(api):
    """Import `live_broker`, ensure SmartConnect placeholder exists, and construct LiveBroker with dummy state."""
    import live_broker

    # Ensure module-level SmartConnect var is present so LiveBroker doesn't raise
    if getattr(live_broker, 'SmartConnect', None) is None:
        live_broker.SmartConnect = type('FakeSmart', (), {})

    state = DummyState()
    notifier = DummyNotifier()
    lb = live_broker.LiveBroker(api, state, notifier=notifier, lots=1, instruments=None)
    return lb, api, state, notifier


def test_duplicate_order_detection():
    """_has_similar_pending_order returns True when broker orderBook contains matching pending order."""
    # fake API
    class API:
        def orderBook(self):
            return {
                'status': True,
                'data': [
                    {
                        'symboltoken': '123',
                        'transactiontype': 'BUY',
                        'quantity': '10',
                        'orderstatus': 'open',
                        'orderid': 'o-1'
                    }
                ]
            }

        def position(self):
            return {'status': True, 'data': []}

    api = API()
    lb, api, state, notifier = make_livebroker_with_api(api)

    assert lb._has_similar_pending_order('BUY', '123', 10) is True
    match = lb._find_matching_order('BUY', '123', 10)
    assert match is not None
    assert match.get('orderid') == 'o-1'


def test_safe_api_call_retries_and_raises():
    import live_broker
    if getattr(live_broker, 'SmartConnect', None) is None:
        live_broker.SmartConnect = type('FakeSmart', (), {})

    # construct LiveBroker with minimal API
    class API:
        def orderBook(self):
            return {'status': True, 'data': []}

        def position(self):
            return {'status': True, 'data': []}

    lb, api, state, notifier = make_livebroker_with_api(API())

    # Function that always raises
    def always_fail():
        raise RuntimeError('simulated timeout')

    raised = False
    try:
        lb._safe_api_call(always_fail, retries=2, delay=0)
    except RuntimeError:
        raised = True

    assert raised is True


def test_placeorder_missing_response_but_order_exists():
    """When placeOrder returns no response, but orderBook shows order complete, _execute_order_with_retry returns FILLED."""
    class API:
        def __init__(self, token):
            self.token = token
            self._calls = 0

        def placeOrder(self, params=None):
            # Simulate missing response
            return None

        def orderBook(self):
            # First call: show pending/open order so _find_matching_order discovers it
            # Subsequent calls: report it as complete so polling returns FILLED
            self._calls += 1
            print(f"DEBUG: API.orderBook called, count={self._calls}")
            # keep 'open' for first two calls so _find_matching_order finds it and
            # the immediate post-placement check also finds it; subsequent polls return 'complete'
            status = 'open' if self._calls < 3 else 'complete'
            return {
                'status': True,
                'data': [
                    {
                        'orderid': 'ex123',
                        'symboltoken': str(self.token),
                        'orderstatus': status,
                        'averageprice': '150.0',
                        'transactiontype': 'BUY',
                        'quantity': '5'
                    }
                ]
            }

        def position(self):
            return {'status': True, 'data': []}

    params_token = '321'
    api = API(params_token)
    lb, api, state, notifier = make_livebroker_with_api(api)

    # Ensure small retry window for deterministic test
    old_retries = Config.ORDER_MAX_RETRIES
    Config.ORDER_MAX_RETRIES = 1
    try:
        # Ensure matching order is discoverable by LiveBroker (orderBook should initially report it as open)
        match = lb._find_matching_order('BUY', params_token, 5)
        assert match is not None, "Matching order must be present in orderBook for this test"

        res = lb._execute_order_with_retry('BUY', params_token, None, 5, 150.0, 'test')
        assert res['status'] == 'FILLED'
    finally:
        Config.ORDER_MAX_RETRIES = old_retries


def test_circuit_breaker_on_unresolved_uncertainty():
    """If placeOrder fails and no matching order exists, after retries LB triggers circuit breaker and returns ERROR."""
    class API:
        def placeOrder(self, params=None):
            return None

        def orderBook(self):
            return {'status': True, 'data': []}

        def position(self):
            return {'status': True, 'data': []}

    api = API()
    lb, api, state, notifier = make_livebroker_with_api(api)

    old_retries = Config.ORDER_MAX_RETRIES
    Config.ORDER_MAX_RETRIES = 1
    try:
        res = lb._execute_order_with_retry('BUY', '9', None, 1, 10.0, 'cbtest')
        assert res['status'] == 'ERROR'
        assert lb.circuit_breaker_triggered is True
    finally:
        Config.ORDER_MAX_RETRIES = old_retries
