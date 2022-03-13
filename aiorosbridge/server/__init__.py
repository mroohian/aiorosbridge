__all__ = ("run")

from ._server import run

for key, value in list(locals().items()):
    if getattr(value, "__module__", "").startswith("aiorosbridge.master."):
        value.__module__ = __name__
