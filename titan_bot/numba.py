def njit(*args, **kwargs):
    def decorator(func):
        return func
    if len(args) == 1 and callable(args[0]):
        return args[0]
    return decorator

def jit(*args, **kwargs):
    return njit(*args, **kwargs)

class jitclass:
    def __init__(self, *args, **kwargs):
        pass
    def __call__(self, cls):
        return cls
