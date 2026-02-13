"""Tracer for entering and exiting Python functions.

This tracer uses the new `sys.monitoring` API to track function calls and their return values.
For now it is coupled with `TypeRecorder`s for simplicity, but it should be decoupled in the future.
"""

import sys
import inspect
from dataclasses import dataclass
from types import CodeType
from typing import Protocol, Self

from apicov.type_recorder import TypeRecorder, get_recorder

# convenience alias for sys.monitoring, to avoid long names
_sm = sys.monitoring


@dataclass
class FuncInfo:
    signature: inspect.Signature
    param_rec: list[TypeRecorder | None]  # list of type recorders for each parameter
    return_rec: TypeRecorder | None = None  # type recorder for the return value, if any


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


class ShouldTraceFunc(Protocol):
    def __call__(self, filename: str) -> bool:
        """Return whether the given file should be traced.

        Filename comes from `CodeType.co_filename`, so it may be a path,
        or some magic string like <module> or <string>.
        """


class Tracer:
    def __init__(self, should_trace: ShouldTraceFunc):
        self._should_trace = should_trace
        self.traced_funcs: dict[str, FuncInfo] = {}
        # _known_codes stores same FuncInfo instances as traced_funcs,
        # or None if the code is not traceable
        self._known_codes: dict[CodeType, FuncInfo | None] = {}

    def __enter__(self) -> Self:
        self.call_stack: list[tuple[CodeType, FuncInfo | None]] = []
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
            assert not self.call_stack

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
        # if this `code` hasn't been seen before, try to get its signature
        # and prepare recorders for its parameters and return type
        if code not in self._known_codes:
            module_name = sys._getframemodulename(2)  # 2nd caller's frame is the monitored code frame
            try:
                module = sys.modules[module_name]  # type: ignore # EAFP
                # this may raise different exceptions because `code` may be
                # a module, a class body or other non-function code object
                # in that case we just don't trace it
                obj = _get_object(module, code.co_qualname)
                signature = inspect.signature(obj)  # type: ignore # EAFP
            except Exception:
                # remember that this code object is not traceable, so we don't have to try again
                self._known_codes[code] = None
            else:
                # create recorders based on the signature
                fullname = f"{module_name}:{code.co_qualname}"
                if fullname in self.traced_funcs:
                    # this is very unlikely, but may theoretically happen if a function is somehow freed
                    # and then recompiled -- we still want to trace it into the same FuncInfo
                    func_info = self.traced_funcs[fullname]
                else:
                    func_info = self.traced_funcs[fullname] = FuncInfo(
                        signature,
                        [_get_recorder_for_annotation(param.annotation) for param in signature.parameters.values()],
                        _get_recorder_for_annotation(signature.return_annotation),
                    )
                self._known_codes[code] = func_info

        # if this function is traceable (code maps to a FuncInfo), record seen values
        traced_func = self._known_codes[code]
        if traced_func is not None:
            frame = sys._getframe(2)  # 2nd caller's frame is the monitored code frame
            assert frame.f_code is code
            for param, recorder in zip(traced_func.signature.parameters, traced_func.param_rec):
                if recorder is not None:
                    recorder.record_seen(frame.f_locals[param])

        self.call_stack.append((code, traced_func))

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
        started_code, traced_func = self.call_stack.pop()
        assert started_code is code, f"mismatched start and return events: {started_code}, {code}"

        if traced_func is not None and (recorder := traced_func.return_rec) is not None:
            recorder.record_seen(retval)

    def _unwind_callback(self, code: CodeType, instruction_offset: int, exception: BaseException) -> None:
        if isinstance(exception, MonitoringCallbackError):
            return  # an exception occured in our callbacks code (oopsie), nothing to trace

        if not self._should_trace(code.co_filename):
            return

        started_code, _ = self.call_stack.pop()
        assert started_code is code, f"mismatched start and unwind events: {started_code}, {code}"

        # TODO: record exceptions for some report?
        # TODO: unwinding should satisfy Never and NoReturn types


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


def _get_recorder_for_annotation(annotation) -> TypeRecorder | None:
    if annotation is inspect.Parameter.empty or annotation is inspect.Signature.empty:
        return None
    return get_recorder(annotation)
