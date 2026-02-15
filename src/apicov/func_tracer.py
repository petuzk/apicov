import inspect
from collections.abc import Callable
from dataclasses import dataclass
from types import FrameType
from typing import Any, Self

from apicov.type_recorder import TypeRecorder, get_recorder


@dataclass(frozen=True)
class FuncTracer:
    signature: inspect.Signature
    param_rec: tuple[TypeRecorder | None, ...]  # type recorders for each parameter
    return_rec: TypeRecorder | None = None  # type recorder for the return value, if any

    def on_start(self, frame: FrameType) -> None:
        for param, recorder in zip(self.signature.parameters, self.param_rec):
            if recorder is not None:
                recorder.record_seen(frame.f_locals[param])

    def on_return(self, _key: None, retval: object) -> None:
        if self.return_rec is not None:
            self.return_rec.record_seen(retval)

    def on_unwind(self, _key: None, exception: BaseException) -> None:
        # TODO: record exceptions for some report?
        # TODO: unwinding should satisfy Never and NoReturn types
        ...

    @classmethod
    def from_callable(cls, func: Callable[..., Any]) -> Self:
        signature = inspect.signature(func)
        return cls(
            signature,
            tuple(_get_recorder_for_annotation(param.annotation) for param in signature.parameters.values()),
            _get_recorder_for_annotation(signature.return_annotation),
        )


def _get_recorder_for_annotation(annotation) -> TypeRecorder | None:
    if annotation is inspect.Parameter.empty or annotation is inspect.Signature.empty:
        return None
    return get_recorder(annotation)
