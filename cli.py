from enum import Enum

class Action(str, Enum):
    """Enumeration class used for restricting CLI argument values to 'on' or 'off'"""

    on = "on"
    off = "off"

    def __bool__(self) -> bool:
        """Overrides the default behaviour and makes the function return True if the value is "on".

        Returns:
            True if the value is "on", False otherwise.
        """
        return self.value == "on"
