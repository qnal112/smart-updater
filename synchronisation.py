from typing import (
    overload,
    TYPE_CHECKING,
)
from functools import wraps

from process_helper import ResourceLock

if TYPE_CHECKING:
    from typing import (
        TypeVar,
        Callable,
        ParamSpec,
        TypeAlias,
    )

    P = ParamSpec("P")
    R = TypeVar("R")
    WrappedCallable: TypeAlias = Callable[P, R]


@overload
def acquires_lock(wrapped_function: "WrappedCallable") -> "WrappedCallable":
    """Overload for the version that doesn't take arguments."""
    ...


@overload
def acquires_lock(*, lock: ResourceLock = ResourceLock.KRAKE) -> "WrappedCallable":
    """Overload for the version that takes keyword-only arguments."""
    ...


def acquires_lock(
    wrapped_function: "WrappedCallable | None" = None, *, lock: ResourceLock = ResourceLock.KRAKE
) -> "WrappedCallable":
    """Decorator for functions that should acquire the resource lock.

    Args:
        wrapped_function: Reference to the wrapped function - passed if the decorator is used
            without arguments.
        lock: Enum instance that represents the lock that should be acquired. Must be passed as
            a keyword argument.

    Returns:
        Modified function with code that acquires the resource lock.
    """

    def outer(function: "WrappedCallable") -> "WrappedCallable":
        """Outer function used to allow the decorator to take the lock name as an argument.

        Args:
            function: Decorated function.

        Returns:
            Modified function with code that acquires the resource lock.
        """

        @wraps(function)
        def inner(*args: "P.args", **kwargs: "P.kwargs") -> "R":
            """Inner function that acquires the resource lock.

            Args:
                *args: Positional arguments passed to the wrapped function.
                **kwargs: Keyword arguments passed to the wrapped function.

            Returns:
                Same return value as the wrapped function.
            """
            with lock.value:
                return function(*args, **kwargs)

        return inner

    if not wrapped_function:
        return outer

    if not callable(wrapped_function):
        raise TestImplementationError(
            "Detected an invalid callable - please make sure only "
            "keyword arguments are passed to the decorator"
        )
    return outer(wrapped_function)
