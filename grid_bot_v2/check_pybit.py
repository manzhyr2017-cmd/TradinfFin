from pybit.unified_trading import HTTP, WebSocket
import inspect

print("HTTP init signature:")
print(inspect.signature(HTTP.__init__))

print("\nWebSocket init signature:")
print(inspect.signature(WebSocket.__init__))
