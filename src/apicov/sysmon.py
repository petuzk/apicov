"""Tracer for entering and exiting Python functions.

This tracer uses the new `sys.monitoring` API to track function calls and their return values.
For now it is coupled with `TypeRecorder`s for simplicity, but it should be decoupled in the future.
"""

import os
import sys
import inspect
from dataclasses import dataclass
from types import CodeType

from apicov.type_recorder import TypeRecorder, get_recorder


@dataclass
class FuncInfo:
    signature: inspect.Signature
    param_rec: list[TypeRecorder | None]  # list of type recorders for each parameter
    return_rec: TypeRecorder | None = None  # type recorder for the return value, if any


class Tracer:
    def __init__(self, filename: str):
        self.filename = filename
        self.traced_funcs: dict[str, FuncInfo] = {}

    def __enter__(self):
        self.call_stack: list[tuple[CodeType, FuncInfo | None]] = []
        self.tool_id = _get_tool_id()
        sys.monitoring.use_tool_id(self.tool_id, "apicov")
        sys.monitoring.register_callback(self.tool_id, sys.monitoring.events.PY_START, self._start_callback)
        sys.monitoring.register_callback(self.tool_id, sys.monitoring.events.PY_RETURN, self._return_callback)
        sys.monitoring.set_events(self.tool_id, sys.monitoring.events.PY_START | sys.monitoring.events.PY_RETURN)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        sys.monitoring.set_events(self.tool_id, sys.monitoring.events.NO_EVENTS)
        sys.monitoring.free_tool_id(self.tool_id)
        assert not self.call_stack

    def _start_callback(self, code: CodeType, instruction_offset: int) -> None:
        if code is self.__exit__.__code__:
            return  # entering our own __exit__ method, skip

        if self._should_skip(code):
            return

        # if this `code` hasn't been seen before, try to get its signature
        # and prepare recorders for its parameters and return type
        if code.co_qualname not in self.traced_funcs:
            module_name = sys._getframemodulename(1)
            module = sys.modules[module_name]
            try:
                # this may raise different exceptions because `code` may be
                # a module, a class body or other non-function code object
                # in that case we just don't record any information about it
                obj = _get_object(module, code.co_qualname)
                signature = inspect.signature(obj)
            except Exception:
                signature = None
            else:
                # create recorders based on the signature
                self.traced_funcs[code.co_qualname] = FuncInfo(
                    signature,
                    [_get_recorder_for_annotation(param.annotation) for param in signature.parameters.values()],
                    _get_recorder_for_annotation(signature.return_annotation),
                )

        # if this function is traceable (present in traced_funcs), record seen values
        traced_func = self.traced_funcs.get(code.co_qualname)
        if traced_func is not None:
            frame = sys._getframe(1)  # get the "caller's" frame, here it's the instrumented frame
            assert frame.f_code is code
            for param, recorder in zip(signature.parameters, self.traced_funcs[code.co_qualname].param_rec):
                if recorder is not None:
                    recorder.record_seen(frame.f_locals[param])

        self.call_stack.append((code, traced_func))

    def _return_callback(self, code: CodeType, instruction_offset: int, retval: object) -> None:
        if code is self.__enter__.__code__:
            return  # leaving our own __enter__ method, skip

        if self._should_skip(code):
            return

        started_code, record = self.call_stack.pop()
        assert started_code is code, f"mismatched start and return events: {started_code}, {code}"
        if record is not None and record.return_rec is not None:
            record.return_rec.record_seen(retval)

    def _should_skip(self, code: CodeType) -> bool:
        try:
            return not os.path.samefile(code.co_filename, self.filename)
        except OSError:
            return True  # file doesn't exist, skip


def _get_tool_id() -> int:
    tool_ids = [sys.monitoring.COVERAGE_ID, 3, 4]
    for tool_id in tool_ids:
        if sys.monitoring.get_tool(tool_id) is None:
            return tool_id
    raise RuntimeError("No available tool IDs for instrumentation")


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
