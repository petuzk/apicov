from collections.abc import Iterable, Mapping
from functools import reduce
from operator import add
from typing import Any

from jinja2 import Environment, PackageLoader

from apicov.frozen import CoverageTrace, FuncCoverage, MatchedCall, OverloadCalls, SerializedTypeMatch, Type
from apicov.func_tracer import UnmatchedException, UnmatchedValue
from apicov.type_annotation import (
    ParametrizedTypeCoverage,
    TypeCoverage,
    UnionAnnotation,
    UnknownAnnotation,
)


def generate_html_report(coverage_data: CoverageTrace) -> Iterable[str]:
    """Generate HTML report presenting the captured data."""
    env = Environment(loader=PackageLoader("apicov"), autoescape=True)
    template = env.get_template("coverage_report.html")

    render_data = get_render_data(coverage_data)

    # Render the template
    return template.generate(render_data)


def get_render_data(coverage_data: CoverageTrace) -> dict[str, Any]:
    """Convert the captured data into a format expected by the report template."""
    files_data = ((filename, *generate_file_report(funcs)) for filename, funcs in coverage_data.files.items())
    return {
        "files": [
            {
                "name": filename,
                "coverage": convert_coverage(file_coverage),
                "members": members,
            }
            for filename, file_coverage, members in files_data
        ],
    }


def generate_file_report(funcs: Mapping[str, FuncCoverage]) -> tuple[TypeCoverage, list[dict[str, Any]]]:
    """Generate report data for a single source file, including coverage for the whole file and the member tree."""
    # use fictional root node to simplify processing
    classmap: dict[str | None, dict[str, Any]] = {None: {"members": []}}

    # iterate over tracers (pre-sorted by line number) and build member tree based on their qualified name
    target: list[dict[str, Any]]
    for qualname, func in funcs.items():
        for parent_class in (None, *qualname.split(".")[:-1]):
            if parent_class not in classmap:
                new_node: dict[str, Any] = {"kind": "class", "name": parent_class, "members": []}
                # target is always defined because the first iteration does not satisfy the condition
                target.append(new_node)  # noqa: F821
                classmap[parent_class] = new_node
            target = classmap[parent_class]["members"]
        target.extend(process_tracer(qualname, func))

    # calculate coverage for each node (including root) based on its members, and convert coverage objects into dicts
    # iterate in reverse order to ensure that child nodes are processed before their parents
    for node in reversed(classmap.values()):
        coverages = []
        for member in node.get("members", []):
            if (cov := member.get("coverage")) is not None:
                coverages.append(cov)
                member["coverage"] = convert_coverage(cov)
        node["coverage"] = reduce(add, coverages, TypeCoverage(0, 0))

    return classmap[None]["coverage"], classmap[None]["members"]


def process_tracer(qualname: str, func: FuncCoverage) -> list[dict[str, Any]]:
    """Convert FuncTracer's overloads into a format suitable for rendering in the report."""
    func_name = qualname.rsplit(".", 1)[-1]
    converted = [
        {
            "kind": "function",
            "name": func_name,
            "lineno": overload.lineno,
            "signature": convert_signature(overload),
            "coverage": overload.coverage.total(),  # add raw TypeCoverage, will be converted in generate_file_report
            "call_details": get_call_details(overload.calls),
        }
        for overload in func.matched_calls
    ]

    unmatched_calls = [
        {"args": ", ".join(f"{name}: {arg}" for name, arg in call.params.items())}
        | (
            {"return_type": str(call.result)}
            if isinstance(call.result, UnmatchedValue)
            else {"result": f"raised {call.result}"}
        )
        for call in func.unmatched_calls
    ]

    if unmatched_calls:
        # if there is only one overload, attach unmatched calls to it, otherwise create a separate entry
        if len(converted) == 1:
            converted[0]["call_details"]["unmatched_calls"] = unmatched_calls
        else:
            new_node = {
                "kind": "function",
                "name": func_name,
                "lineno": func.lineno,
                "signature": None,
                "coverage": None,
                "call_details": {"unmatched_calls": unmatched_calls},
            }
            converted.append(new_node)

    return converted


def get_call_details(calls: Iterable[MatchedCall]) -> dict[str, Any]:
    """Convert signature's call details (parameters, return value, exception) into a format expected by template."""
    matched = []
    unmatched_ret = []
    exceptions = []
    for call in calls:
        converted_params = {"parameters": [p.match for p in call.params]}
        if isinstance(call.result, SerializedTypeMatch):
            matched.append(converted_params | {"return_type": call.result.match})
        elif isinstance(call.result, UnmatchedValue):
            unmatched_ret.append(converted_params | {"return_type": call.result.type_label})
        elif isinstance(call.result, UnmatchedException):
            exceptions.append(converted_params | {"result": f"raised {call.result.exc_repr}"})
        else:
            raise TypeError(f"invalid result type: {type(call.result)}")
    result_dict = {"matched": matched, "unmatched_ret": unmatched_ret, "exceptions": exceptions}
    return {k: v for k, v in result_dict.items() if v}


def convert_signature(overload: OverloadCalls) -> dict[str, Any]:
    """Convert an overload's signature and coverage data into a format expected by template."""
    return {
        "params": {
            param_name: convert_type_annotation(anno, cov)
            for (param_name, anno), cov in zip(
                overload.signature.params_annotations.items(), overload.coverage.param_coverages
            )
        },
        "ret": convert_type_annotation(overload.signature.return_annotation, overload.coverage.return_coverage),
    }


def convert_type_annotation(anno: Type | None, coverage: TypeCoverage | None) -> list[dict[str, Any]] | None:
    """Convert a type annotation into a format expected by template.

    Each type is represented as a list of union options, with coverage info for each option.
    If the annotation is not a union, the list will have only one element.
    If there is no annotation, None is returned.
    """
    if anno is None:
        return None
    if anno.cls == UnionAnnotation.__name__:
        assert isinstance(coverage, ParametrizedTypeCoverage)
        assert anno.args and all(isinstance(arg, Type) for arg in anno.args)
        return list(map(convert_single_type_annotation, anno.args, coverage.args_cov))
    if anno.cls == UnknownAnnotation.__name__:
        # display UnknownAnnotation as uncoverable
        coverage = None
    return [convert_single_type_annotation(anno, coverage)]


def convert_single_type_annotation(anno: Type, coverage: TypeCoverage | None) -> dict[str, Any]:
    """Convert a single (non-union) type annotation into a format expected by template."""
    return {
        "cov_type": get_cov_type(coverage),
        "name": anno.origin,
        "args": None if anno.args is None else get_type_args(anno.args, coverage),
    }


def get_cov_type(coverage: TypeCoverage | None) -> str:
    if coverage is None:
        return "uncoverable"
    if coverage.hits == coverage.total:
        return "cov-full"
    if not coverage.hits:
        return "cov-none"
    return "cov-partial"


def get_type_args(args: Iterable[Type], coverage: TypeCoverage | None) -> list[list[dict[str, Any]]]:
    # dealing with a parametrized type annotation, so expect parametrized coverage
    assert isinstance(coverage, ParametrizedTypeCoverage)
    return list(filter(None, map(convert_type_annotation, args, coverage.args_cov)))


def convert_coverage(coverage: TypeCoverage) -> dict[str, Any]:
    """Convert coverage data into a format expected by template."""
    return {
        "hits": coverage.hits,
        "total": coverage.total,
        "ratio": coverage.ratio,
    }
