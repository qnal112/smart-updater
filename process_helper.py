import logging
import tempfile
from abc import (
    ABCMeta,
    abstractmethod,
)
from enum import Enum
from typing import TYPE_CHECKING
from pathlib import Path
from contextlib import (
    suppress,
    ExitStack,
    contextmanager,
)

import typer
from filelock import FileLock

if TYPE_CHECKING:
    from typing import Any
    from collections.abc import Generator

logging.getLogger("filelock").disabled = True


class TerminationAfterInitialFailure(Exception):
    """Used to terminate the process of acquiring the lock if the first attempt is unsuccessful."""


class ResourceLockCallbackHandler(metaclass=ABCMeta):
    """Stores callbacks executed in different stages of the resource locking procedure."""

    def __init__(self, resource_lock: "_ResourceLock") -> None:
        """Stores a reference to the resource lock for later use."""
        self.resource_lock = resource_lock

    @property
    @abstractmethod
    def terminate_after_initial_failure(self) -> bool:
        """Whether the instance should stop attempting to acquire the lock after the first attempt
        fails."""

    @abstractmethod
    def initial_failure(self) -> None:
        """Called when the first attempt to acquire the resource lock fails."""

    @abstractmethod
    def success_after_initial_failure(self) -> None:
        """Called when the lock is successfully acquired after the initial attempt fails."""


class CLIResourceCallbackHandler(ResourceLockCallbackHandler):
    """Stores callbacks executed when the framework is used with the CLI."""

    @property
    def terminate_after_initial_failure(self) -> bool:
        return False

    def initial_failure(self) -> None:
        typer.echo(
            f"Another instance of the framework is already using the "
            f"{typer.style(self.resource_lock.name, bold=True)} resource, waiting for the "
            f"lock to get released.."
        )

    def success_after_initial_failure(self) -> None: ...


# pylint: disable=too-many-ancestors
class _ResourceLock(FileLock):
    """File-backed resource de-conflicting lock. Can be used to synchronise exclusive usage of some
    particular named resource, e.g. to ensure only one instance of the framework is running at
    a time.

    Attributes:
        DEFAULT_PARENT_DIRECTORY: Default parent directory for all lock files.
        EXTENSION: Generated lock extension.
    """

    DEFAULT_PARENT_DIRECTORY = Path(tempfile.gettempdir(), "krake")
    EXTENSION = ".lock"

    def __init__(self, name: str, parent_directory: Path | None = None) -> None:
        """Initialises the process lock.

        Args:
            name: Lock name.
            parent_directory: Parent directory override.
        """
        self.name = name
        self.callback_handler = CLIResourceCallbackHandler(self)
        directory = parent_directory or self.DEFAULT_PARENT_DIRECTORY
        directory.mkdir(parents=True, exist_ok=True)
        with suppress(PermissionError):
            directory.chmod(0o777)
        self.lock_file_path = directory.joinpath(f"{name}{self.EXTENSION}")
        super().__init__(str(self.lock_file_path), mode=0o666)
        self.__initial_failure_to_acquire_handled = False

    def acquire(self, *args: "Any", **kwargs: "Any") -> "Any":
        """Custom version that executes callback functions depending on whether the initial attempt
        to acquire the lock failed.

        Args:
            *args: Positional arguments passed to the original method.
            **kwargs: Positional arguments passed to the original method.

        Returns:
            The original return value.
        """
        self.__initial_failure_to_acquire_handled = False
        acquire_proxy = super().acquire(*args, **kwargs)
        if self.__initial_failure_to_acquire_handled:
            self.callback_handler.success_after_initial_failure()
        return acquire_proxy

    def _acquire(self) -> None:
        """Overridden version used for calling custom callbacks if the initial attempt to acquire
        the lock is unsuccessful.

        Notes:
            The only way to determine if the lock is in use is to check the is_locked property after
            the original _acquire has finished executing. It returns True if the current instance
            successfully captures the lock. If it returns False, the parent's acquire method
            will continue calling _acquire in a while loop.
        """
        super()._acquire()
        if self.is_locked or self.__initial_failure_to_acquire_handled:
            return

        self.__initial_failure_to_acquire_handled = True
        self.callback_handler.initial_failure()
        if self.callback_handler.terminate_after_initial_failure:
            raise TerminationAfterInitialFailure


class ResourceLock(Enum):
    """Stores available resource locks.

    Attributes:
        KRAKE: General purpose lock.
        TARGET_INTERACTION: Used whenever the framework interacts with the target.
        INI: Used whenever krake.ini needs to be modified.
        CACHE: Used whenever the cache file needs to be modified.
        LOG_DIRECTORY: Used whenever a new log directory needs to be created.
    """

    KRAKE = _ResourceLock("KRAKE")
    TARGET_INTERACTION = _ResourceLock("TARGET_INTERACTION")
    INI = _ResourceLock("INI")
    CACHE = _ResourceLock("CACHE")
    LOG_DIRECTORY = _ResourceLock("LOG_DIRECTORY")

    @classmethod
    @contextmanager
    def all_acquired(cls) -> "Generator[None]":
        """Context manager that acquires every available lock."""
        with ExitStack() as exit_stack:
            for lock in cls:
                exit_stack.enter_context(lock.value)
            yield
