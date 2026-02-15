"""Tracer for entering and exiting Python functions.

This tracer uses the new `sys.monitoring` API to track function calls and their return values.
"""

import sys
from collections.abc import Callable
from types import CodeType, FrameType
from typing import Any, NamedTuple, Protocol, Self

# convenience alias for sys.monitoring, to avoid long names
_sm = sys.monitoring


class MonitoringCallbackError(BaseException):
    """An exception raised in a sys.monitoring callback.

    From the call stack perspective, sys.monitoring callbacks are executed as
    if they were called from the monitored code. This means that exceptions
    raised in callbacks propagate through the monitored code, which, in turn,
    may interfere with its exception handling in unexpected ways.

    This custom class is used to both disguise and distinguish errors raised
    in sys.monitoring callbacks. It intentionally derives from `BaseException`
    to minimize impact on the monitored code (it may only be catched with bare
    `except` or `except BaseException`, both of which are highly discouraged).
    """


class ShouldTraceFn(Protocol):
    def __call__(self, filename: str) -> bool:
        """Return whether the given file should be traced.

        Filename comes from `CodeType.co_filename`, so it may be a path,
        or some magic string like <module> or <string>.
        """


class FuncTracer(Protocol):
    """Tracer for a single function. Receives all events related to entering or leaving this function."""

    def on_start(self, frame: FrameType) -> Any:
        """Callback for function start event.

        Returned object will be passed to the return/unwind callback corresponding
        to this call, and can be used to correlate them with the start event.
        """

    def on_return(self, start_key: Any, retval: object) -> None:
        """Callback for function return event."""

    def on_unwind(self, start_key: Any, exception: BaseException) -> None:
        """Callback for function unwind (exception) event."""


class GetFuncTracerFn[FT: FuncTracer](Protocol):
    def __call__(self, func: Callable[..., Any]) -> FT | None:
        """Given a callable object, return a tracer for it, or None to skip tracing this code.

        Exceptions raised in this function will be suppressed
        and treated as if this function returned None.
        """


class Fullname(NamedTuple):
    module: str
    qualname: str


class Tracer[FT: FuncTracer]:
    def __init__(self, should_trace: ShouldTraceFn, get_func_tracer: GetFuncTracerFn[FT]) -> None:
        self._should_trace = should_trace
        self._get_func_tracer = get_func_tracer
        self.traced_funcs: dict[Fullname, FT] = {}
        # _known_codes stores same FuncTracer instances as traced_funcs,
        # or None if the code is not traceable
        self._known_codes: dict[CodeType, FT | None] = {}

    def __enter__(self) -> Self:
        self._call_stack: list[tuple[CodeType, FT | None, Any]] = []
        self.tool_id = _get_tool_id()
        _sm.use_tool_id(self.tool_id, "apicov")
        _sm.register_callback(self.tool_id, _sm.events.PY_START, self._start_callback)
        _sm.register_callback(self.tool_id, _sm.events.PY_RETURN, self._return_callback)
        _sm.register_callback(self.tool_id, _sm.events.PY_UNWIND, self._unwind_callback)
        _sm.set_events(self.tool_id, _sm.events.PY_START | _sm.events.PY_RETURN | _sm.events.PY_UNWIND)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        _sm.set_events(self.tool_id, _sm.events.NO_EVENTS)
        _sm.free_tool_id(self.tool_id)

        if exc_type is not MonitoringCallbackError:
            assert not self._call_stack

    # Signatures for sys.monitoring callbacks can be found here:
    # https://docs.python.org/3/library/_sm.html#callback-function-arguments

    def _start_callback(self, code: CodeType, instruction_offset: int) -> None:
        try:
            if code is self.__exit__.__code__:
                return  # entering our own __exit__ method, skip
            if not self._should_trace(code.co_filename):
                return
            return self._start_callback_inner(code)
        except Exception as e:
            raise MonitoringCallbackError from e

    def _start_callback_inner(self, code: CodeType) -> None:
        # if this `code` hasn't been seen before, create a FuncTracer for it (if possible)
        if code not in self._known_codes:
            module_name = sys._getframemodulename(2)  # 2nd caller's frame is the monitored code frame
            if module_name is None:
                # not sure why this may happen, but just don't trace it
                tracer = None
            else:
                fullname = Fullname(module_name, code.co_qualname)
                tracer = self._new_func_tracer(fullname)
                if tracer is not None:
                    self.traced_funcs[fullname] = tracer
            self._known_codes[code] = tracer

        # if this function is traceable (code maps to a FuncTracer), call its on_start callback
        key = None
        tracer = self._known_codes[code]
        if tracer is not None:
            frame = sys._getframe(2)  # 2nd caller's frame is the monitored code frame
            assert frame.f_code is code
            key = tracer.on_start(frame)

        self._call_stack.append((code, tracer, key))

    def _new_func_tracer(self, fullname: Fullname) -> FT | None:
        # this is very unlikely, but may theoretically happen if a function is somehow freed
        # and then recompiled -- we still want to trace it into the same FuncTracer
        tracer = self.traced_funcs.get(fullname)
        if tracer is None:
            # try to create a tracer for this code object
            # this may raise different exceptions because `code` may be
            # a module, a class body or other non-function code object
            # in that case we just don't trace it
            try:
                module = sys.modules[fullname.module]
                obj = _get_object(module, fullname.qualname)
                if callable(obj):
                    tracer = self._get_func_tracer(obj)
            except Exception:
                pass
        return tracer

    def _return_callback(self, code: CodeType, instruction_offset: int, retval: object) -> None:
        try:
            if code is self.__enter__.__code__:
                return  # leaving our own __enter__ method, skip
            if not self._should_trace(code.co_filename):
                return
            return self._return_callback_inner(code, retval)
        except Exception as e:
            raise MonitoringCallbackError from e

    def _return_callback_inner(self, code: CodeType, retval: object) -> None:
        started_code, traced_func, key = self._call_stack.pop()
        assert started_code is code, f"mismatched start and return events: {started_code}, {code}"

        if traced_func is not None:
            traced_func.on_return(key, retval)

    def _unwind_callback(self, code: CodeType, instruction_offset: int, exception: BaseException) -> None:
        if isinstance(exception, MonitoringCallbackError):
            return  # an exception occured in our callbacks code (oopsie), nothing to trace

        if not self._should_trace(code.co_filename):
            return

        started_code, traced_func, key = self._call_stack.pop()
        assert started_code is code, f"mismatched start and unwind events: {started_code}, {code}"

        if traced_func is not None:
            traced_func.on_unwind(key, exception)


def _get_tool_id() -> int:
    """Find a free tool ID."""
    # Prefer the coverage ID, fall back to unassigned ones (3 and 4).
    tool_ids = [_sm.COVERAGE_ID, 3, 4]
    for tool_id in tool_ids:
        if _sm.get_tool(tool_id) is None:
            return tool_id
    raise RuntimeError("no available tool IDs for instrumentation")


def _get_object(module, qualname: str) -> object:
    parts = qualname.split(".")
    obj = module
    for part in parts:
        obj = getattr(obj, part)
    return obj
