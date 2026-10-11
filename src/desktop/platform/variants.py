"""Per-function Windows variants.

``@windows_variant("module:function")`` marks a function whose Windows
behaviour lives in a Windows-only module. On every other system the decorator
returns the function itself: Linux runs the original object, with no wrapper
and nothing imported. On Windows the function is replaced by a router that
imports the variant when first called and passes it the same arguments, so a
method's variant receives ``self`` like the original.
"""
from __future__ import annotations

import functools
import importlib
import inspect
import sys


def windows_variant(target: str, *, system: str | None = None):
    selected = sys.platform if system is None else system
    module_name, _, attribute = target.partition(":")
    if not module_name or not attribute or ":" in attribute:
        raise ValueError("a variant target is 'module:function'")

    def decorate(func):
        if selected != "win32":
            return func

        def resolve():
            return getattr(importlib.import_module(module_name), attribute)

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def routed(*args, **kwargs):
                return await resolve()(*args, **kwargs)
        else:
            # Generator and async-generator functions return their iterator from
            # the variant's call, so context-manager decorators above still work.
            @functools.wraps(func)
            def routed(*args, **kwargs):
                return resolve()(*args, **kwargs)
        routed.linux_original = func
        routed.windows_target = target
        return routed

    return decorate
