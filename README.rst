======
apicov
======

apicov is a tool for measuring an experimental metric called "API coverage" in Python projects.
The idea is similar to that of a more traditional line or branch coverage, but it focuses
on the coverage of the API surface rather than the code itself.


What is API coverage?
---------------------

API coverage is a metric that quantifies how much of a project's API (expressed through type annotations)
is covered in runtime, typically in tests. A 100% API coverage means that each function has been called
with arguments of all types specified in its type annotations, and return values of all annotated return
types have been observed.

For example, consider the following function:

.. code-block:: python

    def process_data(data: str | bytes) -> SomeResult:
        ...


To achieve 100% API coverage for this function, there has to be at least one call to ``process_data``
with a ``str`` argument and at least one call with a ``bytes`` argument. Additionally, the return value
has to be of type ``SomeResult`` in both cases.

If there were only calls with a ``str`` argument, the measured API coverage for this function would be 50%.
Calls with arguments or return values that do not match type annotations do not contribute to the API coverage.
For example, calling ``process_data`` with a value of ``42``, or returning ``None`` from ``process_data``
would not increase the API coverage.

Note how this metric completely omits the implementation of ``process_data`` - the API coverage is only
concerned with the function's signature, not with how it works internally.


Why is API coverage useful?
---------------------------

API coverage can help identify gaps in test coverage that are not visible through traditional line or branch
coverage metrics. For example, if a function has a union type annotation, it might be possible that only one of
the types is actually tested, which would not be reflected in line coverage if the same code paths are executed
regardless of the argument types (e.g. because the value is passed to an external library that accepts both types).

Similarly, it can also help to identify "dead" type annotations that are no longer needed. For example,
a return type annotation might specify a union of several types, but in practice only one of those types is ever
returned. Despite being valid from type checker perspective, this could indicate that the function's
implementation has changed but the type annotations have not been updated accordingly.

Because API coverage relies on type annotations, it generally encourages better typing in the codebase,
which has benefits beyond just measuring API coverage.

Lastly, it is easier to reach and maintain 100% API coverage compared to 100% line or branch coverage, especially
in large codebases. This is because API coverage is more coarse-grained, and only focuses on the correctness
of the API usage, rather than on edge cases or error handling. This makes it a more practical goal to achieve.


What apicov is not?
-------------------

apicov is not a replacement for line/branch coverage tools. It is a complementary tool that provides
insights from a different perspective. Line/branch coverage would still be useful when different values
of the same type trigger different code paths (e.g. different handling of positive and negative integers).

apicov is not a replacement for a type checker. In particular, it deliberately ignores incorrect usages
of the API, because this might be intentional in tests (e.g. testing that a function raises an exception
when called with wrong types).
