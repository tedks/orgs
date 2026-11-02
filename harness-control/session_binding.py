"""Compatibility import; implementation lives in skills/_shared/native."""
from _skills_native import load_into as _load_into

_load_into(__name__, globals())
