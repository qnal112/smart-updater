import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import TracebackType
    from typing import Type

class MissingPrecondition(Exception):
    def __init__(self, description=None, suggested_fix=None):
        self.description = description
        self.suggested_fix = suggested_fix
        message = f"{description}"
        if suggested_fix:
            message += f" | Suggested fix: {suggested_fix}"
        super().__init__(message)

class IdEeprom:
    """Class for interacting with an ID EEPROM on a Raspberry Pi extension board.

    Attributes:
            log: Logger object.
            eeprom_size: Size of the attached EEPROM in kbit.
            board_info: Dictionary with information from /proc/device-tree/hat/ folder.
            manufacturer_data: Project specific custom data.
            version: Decoded hardware version of the board.
    """

    def __init__(self, eeprom_size: int = 32) -> None:
        """Constructor of the class initialises the ID EEPROM and searches for
        available content on the Pi in path /proc/device-tree/hat/ and reads
        the content from the attached EEPROM.

        Args:
            eeprom_size: Size of the attached EEPROM in kbit. Defaults to 32.
        """
        self.eeprom_size = eeprom_size
        self.board_info = {}
        self.manufacturer_data = {}
        self.version = None

        # check content
        try:
            content = os.listdir("/proc/device-tree/hat/")
        except FileNotFoundError as exception:
            raise MissingPrecondition(
                description="CAN switcher is unavailable - no HAT information found",
                suggested_fix="add the missing CAN switcher",
            ) from exception

        for entry in content:
            with open(f"/proc/device-tree/hat/{entry}", encoding="utf-8") as file:
                if entry == "custom_0":
                    custom_info_lines = []
                    for line in file:
                        if len(line) < 2 or line[-1] != "\n":
                            raise FrameworkError(
                                f"Invalid board info: malformed line {repr(line)},"
                                f" expecting newline-terminated, non-empty string"
                            )
                        custom_info_lines.append(line[:-1])
                    self.board_info[entry] = custom_info_lines
                else:
                    # read every line of the entry and save them to a list
                    self.board_info[entry] = [
                        stripped_line for line in file if (stripped_line := line.strip())
                    ]

        # always decode the custom data
        self.decode_manufacturer_custom_data()

        # extract the board version
        self.decode_board_version()

    def __enter__(self) -> object:
        """Context Manager initialisation.

        Returns:
            IdEeprom object.
        """
        return self

    def __exit__(
        self,
        exc_type: "Type[BaseException] | None",
        exc_value: BaseException | None,
        exc_raceback: "TracebackType | None",
    ) -> None:
        """Context Manager cleanup."""

    def decode_manufacturer_custom_data(self) -> dict:
        """Decodes the project specific manufacturer custom data of an ID EEPROM. The data has to
        be stored as a key-value pair and must be separated with a LF character, e.g. "date\n" and
        "2023-01-01\n".

        Returns:
            Decoded manufacturer custom data information.
        """
        if "custom_0" not in self.board_info:
            return {}

        data = {}
        key = ""

        # iterate through infos
        for idx, item in enumerate(self.board_info["custom_0"]):
            if not idx % 2:
                # store key
                key = item
            else:
                # add key and value to dictionary
                data[key] = item
                key = ""

        for key, value in data.items():
            # check value
            if key == "serial_number":
                data[key] = bytes(value, "latin-1").hex().replace("2d", "-")

            # number values
            elif len(value) == 1:
                data[key] = int(bytes(value, "latin-1").hex(), 16)

            # string values
            else:
                data[key] = value

        self.manufacturer_data = data

        return data

    def decode_board_version(self) -> str:
        # extract the board version to get a string like "0.1"
        self.version = self.board_info["product_ver"][0]
        self.version = self.version.split("x")[1][1:2] + "." + self.version.split("x")[1][2:3]

        return self.version
