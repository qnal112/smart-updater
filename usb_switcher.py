import time
import logging
from process_helper import ResourceLock
from synchronisation import acquires_lock
from cli import Action
from eeprom import IdEeprom

# configure globally
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)

logger = logging.getLogger(__name__)

# import subprocess
from typing import (
    Iterable,
    TYPE_CHECKING,
)
# from pathlib import Path
# from datetime import datetime
# from threading import (
#     Event,
#     Thread,
# )
# from contextlib import (
#     suppress,
#     contextmanager,
# )
from dataclasses import dataclass
from enum import Enum

class ResourceLock(Enum):
    TARGET_INTERACTION = "target_interaction"
    USB_ACCESS = "usb_access"

class USBConnectError(Exception):
    def __init__(self, target: str, message: str = "Failed to connect USB"):
        self.target = target
        self.message = f"{message}: {target}"
        super().__init__(self.message)

@dataclass
class Clamp:
    """Stores the output levels of the pin associated with a clamp.

    Attributes:
        name: name of the clamp aka clamp id.
        state: on/off state of the clamp.
    """

    name: str
    state: str = "unknown"

class Portexpander:
    """Class for interfacing the PCA9539APW IO port expander from NXP.
    See the datasheet for further information:
    https://www.nxp.com/docs/en/data-sheet/PCA9539A.pdf

    Attributes:
        i2c_bus: Index of the I2C peripheral.
        i2c_addr: Address of the I2C device.
        config: Pin configuration information.
        pinstate: State of the pins, binary coded.
        instance: Object for the I2C instance.
    """

    # define register addresses
    __inputReg0 = 0x00
    __inputReg1 = 0x01
    __outputReg0 = 0x02
    __outputReg1 = 0x03
    __polarityInvReg0 = 0x04
    __polarityInvReg1 = 0x05
    __configurationReg0 = 0x06
    __configurationReg1 = 0x07

    DEFAULT_PINOUT: dict[str, dict[str, int]] = {
        "Relay_1": {"port": 0, "pin": 0, "direction": "out", "default": 1},
        "Relay_2": {"port": 0, "pin": 1, "direction": "out", "default": 1},
        "Relay_3": {"port": 0, "pin": 2, "direction": "out", "default": 1},
        "Relay_4": {"port": 0, "pin": 3, "direction": "out", "default": 1},
        "Relay_5": {"port": 0, "pin": 4, "direction": "out", "default": 1},
        "Relay_6": {"port": 0, "pin": 5, "direction": "in", "default": 0},
        "USB_Switch": {"port": 0, "pin": 6, "direction": "out", "default": 0},
        "Eeprom_WP": {"port": 0, "pin": 7, "direction": "out", "default": 1},
        "Route_CAN_1": {"port": 1, "pin": 0, "direction": "out", "default": 0},
        "Route_CAN_2": {"port": 1, "pin": 1, "direction": "out", "default": 0},
        "Route_CAN_3": {"port": 1, "pin": 2, "direction": "out", "default": 0},
        "Route_CAN_4": {"port": 1, "pin": 3, "direction": "out", "default": 0},
        "Route_CAN_5": {"port": 1, "pin": 4, "direction": "out", "default": 0},
        "Route_CAN_6": {"port": 1, "pin": 5, "direction": "out", "default": 0},
        "Route_CAN_7": {"port": 1, "pin": 6, "direction": "out", "default": 0},
        "Route_CAN_8": {"port": 1, "pin": 7, "direction": "out", "default": 0},
    }

    VERSION_TO_PINOUT_MAPPING: dict[str, dict[str, dict[str, int]]] = {
        "1.0": {
            "Relay_1": {"port": 0, "pin": 0, "direction": "out", "default": 1},
            "Relay_2": {"port": 0, "pin": 1, "direction": "out", "default": 1},
            "Relay_3": {"port": 0, "pin": 2, "direction": "out", "default": 1},
            "Relay_4": {"port": 0, "pin": 3, "direction": "out", "default": 1},
            "Relay_5": {"port": 0, "pin": 4, "direction": "out", "default": 1},
            "Relay_6": {"port": 0, "pin": 5, "direction": "in", "default": 0},
            "USB_Switch": {"port": 0, "pin": 6, "direction": "out", "default": 0},
            "Switch_CAN_Short": {"port": 0, "pin": 7, "direction": "out", "default": 0},
            "Route_CAN_1": {"port": 1, "pin": 0, "direction": "out", "default": 0},
            "Route_CAN_2": {"port": 1, "pin": 1, "direction": "out", "default": 0},
            "Route_CAN_3": {"port": 1, "pin": 2, "direction": "out", "default": 0},
            "Route_CAN_4": {"port": 1, "pin": 3, "direction": "out", "default": 0},
            "Route_CAN_5": {"port": 1, "pin": 4, "direction": "out", "default": 0},
            "Route_CAN_6": {"port": 1, "pin": 5, "direction": "out", "default": 0},
            "Route_CAN_7": {"port": 1, "pin": 6, "direction": "out", "default": 0},
            "Route_CAN_8": {"port": 1, "pin": 7, "direction": "out", "default": 0},
        },
        "1.1": DEFAULT_PINOUT,
        "1.2": DEFAULT_PINOUT,
    }

    def __init__(self, address: int = 0x74) -> None:
        """Constructor of the class.

        Attributes:
            i2c_bus: Index of the I2C peripheral.
            i2c_addr: Address of the I2C device.
            config: Pin configuration information.
            pinstate: State of the pins, binary coded.
            instance: Object for the I2C instance.

        Raises:
            USBConnectError: If the pin layout could not be determined.
        """
        from smbus import SMBus

        id_eep = IdEeprom()

        self.i2c_bus = 1
        # check if manufacturer data is available on the EEPROM
        if not id_eep.manufacturer_data == {}:
            self.i2c_addr = id_eep.manufacturer_data["portexpander_address"]
            self.version = id_eep.version
        else:
            # set default values if EEPROM is unprogrammed
            self.i2c_addr = address
            self.version = "1.2"

        self.config = {
            "input": [None, None],
            "output": [None, None],
            "inverted": [None, None],
        }
        self.pinstate = [None, None]

        # set the default pinout on the CAN Switcher PCB.
        self.pinout: dict[str, dict[str, int]] = self.VERSION_TO_PINOUT_MAPPING.get(self.version)

        if not self.pinout:
            raise USBConnectError(f"Failed to determine the pin layout for version '{self.version}'")

        self._create_pin_mask_from_pinout()

        try:
            # initialise the bus
            self.instance = SMBus(self.i2c_bus)

            # update configuration
            self._get_configuration()

            # update output configuration
            if not self._check_io_settings():
                # not initialised correctly, need to set direction first
                self.set_default_io_direction()
                self.set_default_pin_state()

        except FileNotFoundError as exc:
            raise SMBusPeripheralError("I2C interface is not enabled!") from exc

        except IOError as exc:
            raise SMBusCommunicationError(
                f"I2C device on address {self.i2c_addr} not found!"
            ) from exc

        except Exception as exc:
            logger.error(exc)
            raise SMBusUndefinedError from exc

    # external API
    def set_gpio_port_output_level(self, port_index: int, level: int) -> bool:
        """Updates the state of a full port. Every pin is binary coded in the byte
        and can be at a logical "1" (high) or a logical "0" (low) state. This
        polarity can be inverted if necessary.

        Args:
            port_index: Port index of the I2C device.
            level: Output level of the port.

        Returns:
            True if success else False.
        """
        # write register
        self._write_port_outputs(port_index, level)
        # check state
        data = self.get_gpio_port_level(port_index)

        if data != level:
            return False

        return True

    def set_gpio_pin_output_level(self, port_index: int, pin_number: int, level: int) -> bool:
        """Updates the state of a pin. Every pin is binary coded in the byte and can
        be at a logical "1" (high) or a logical "0" (low) state. This polarity
        can be inverted if necessary.

        Args:
            port_index: Port index of the I2C device.
            pin_number: Pin number of the selected port.
            level: Output level of the pin.

        Returns:
            True if success else False.
        """
        logger.warning(f"Setting pin {pin_number} on port {port_index} to {level}")
        # get current state
        data = self.get_gpio_port_level(port_index)

        if data is None:
            return False

        # update current state with new pin level
        new_data = (data & ~(1 << pin_number)) + (level << pin_number)
        # write register
        self._write_port_outputs(port_index, new_data)
        # check new state
        data = self.get_gpio_port_level(port_index)

        if data != new_data:
            return False

        return True

    def get_gpio_port_level(self, port_index: int) -> int:
        """Reads the current state of the port. Every pin is binary coded in the byte
        and has a logical "1" at high level and a logical "0" at low level.

        Args:
            port_index: Port index of the I2C device.

        Returns:
            One byte of data, None if port index does not exist.
        """
        data = self._read_port_inputs(port_index)

        # data received from valid port index
        if data is not None:
            self.pinstate[port_index] = data

        return data

    def get_gpio_port_level_detail(self, port_index: int) -> list:
        """Reads the current state of the port. Every pin is binary coded in the byte
        and has a logical "1" at high level and a logical "0" at low level.

        Args:
            port_index: Port index of the I2C device.

        Returns:
            A list with pin state of the port, None if port index does not exist.
        """
        # update pinstate
        self.pinstate[port_index] = self.get_gpio_port_level(port_index)

        data = []

        for i in range(8):
            data.append((self.pinstate[port_index] & (1 << i)) >> i)

        return data

    def get_gpio_port_output_level(self, port_index: int) -> int:
        """Reads the current state of the port. Every pin is binary coded in the byte
        and has a logical "1" at high level and a logical "0" at low level.
        Reading the output register reflect the value that is in the flip-flop
        controlling the output selection, not the actual pin value. To read the
        applied pin states use function get_gpio_port_level().

        Args:
            port_index: Port index of the I2C device.

        Returns:
            One byte of data, None if port index does not exist.
        """
        return self._read_port_outputs(port_index)

    def get_gpio_port_level_detail_dict(self, port_index: int) -> dict | None:
        """Reads the current state of the port. Every pin is binary coded in the byte
        and has a logical "1" at high level and a logical "0" at low level.

        Args:
            port_index: Port index of the I2C device.

        Returns:
            Dictionary with pin states of the port, None if port index does not exist.
        """
        if port_index not in (0, 1):
            return None

        data = self.get_gpio_port_level_detail(port_index)

        state = {}

        for i, key in enumerate(self.pinout.keys()):
            if port_index == 0 and i < 8:
                if "Relay" in key:
                    state[key] = "off" if data[i] == 1 else "on"
                else:
                    state[key] = "off" if data[i] == 0 else "on"

            elif port_index == 1 and i >= 8:
                state[key] = "off" if data[i - 8] == 0 else "on"

        return state

    def get_input_pin_state_dict(self) -> dict:
        """Reads the input configuration settings of the ports.

        Returns:
            Dictionary with state of input pins.
        """
        inputs = self._read_port_inputs(0)

        return {
            key: (inputs & (1 << index)) >> index
            for index, (key, value) in enumerate(self.pinout.items())
            if value["direction"] == "in"
        }

    def set_default_io_direction(self) -> bool:
        """Sets the IO configuration of the ports to default values.

        Returns:
            True if success else False.
        """
        default = self.get_default_io_direction()

        for i in range(2):
            port_config = 0xFF - default[i]
            self._write_port_configuration(i, port_config)

            # validate settings
            if self._read_port_configuration(i) != port_config:
                logger.error(f"Port {i} direction not set to {port_config}!")
                return False

            # update information
            self.config["input"][i] = port_config
            self.config["output"][i] = default[i]

        return True

    def set_all_pins_as_input(self) -> bool:
        """Sets all available pins as input.

        Returns:
            True if success else False.
        """
        for i in range(2):
            # set inputs
            self.set_gpio_port_as_input(i)
            # validate settings
            if self.config["input"][i] != 0xFF:
                return False

        return True

    def set_all_pins_as_output(self) -> bool:
        """Sets all available pins as output with the current output levels.
        Check the output levels first to prevent undefined behaviour.

        Returns:
            True if success else False.
        """
        for i in range(2):
            # set inputs
            self.set_gpio_port_as_output(i)
            # validate settings
            if self.config["output"][i] != 0xFF:
                return False

        return True

    def set_gpio_port_as_input(self, port_index: int) -> bool:
        """Sets a full port as input.

        Args:
            port_index: Port index of the I2C device.

        Returns:
            True if success else False.
        """
        self._write_port_configuration(port_index, 0xFF)

        # validate settings
        data = self._read_port_configuration(port_index)

        if data != 0xFF:
            return False

        # update information
        self.config["input"][port_index] = 0xFF
        self.config["output"][port_index] = 0
        return True

    def set_gpio_port_as_output(self, port_index: int) -> bool:
        """Sets s full port as output with the current output levels.
        Check the output levels first to prevent undefined behaviour.

        Args:
            port_index: Port index of the I2C device.

        Returns:
            True if success else False.
        """
        self._write_port_configuration(port_index, 0x00)

        # validate settings
        data = self._read_port_configuration(port_index)
        if data != 0x00:
            return False

        # update information
        self.config["input"][port_index] = 0
        self.config["output"][port_index] = 0xFF
        return True

    def set_gpio_pin_as_input(self, port_index: int, pin_number: int) -> bool:
        """Sets a GPIO pin as input.

        Args:
            port_index: Port index of the I2C device.
            pin_number: Pin number of the port.

        Returns:
            True if success else False.
        """
        # get current state
        data = self._read_port_configuration(port_index)

        if data is None:
            return False

        # update current state with new pin level
        new_data = (data & ~(1 << pin_number)) + (1 << pin_number)
        # write register
        self._write_port_configuration(port_index, new_data)
        # check new state
        data = self._read_port_configuration(port_index)

        if data != new_data:
            return False

        # update information
        self.config["input"][port_index] = data
        self.config["output"][port_index] = 0xFF - data
        return True

    def set_gpio_pin_as_output(self, port_index: int, pin_number: int) -> bool:
        """Sets a GPIO pin as output with the current output level.
        Check the output level first to prevent undefined behaviour.

        Args:
            port_index: Port index of the I2C device.
            pin_number: Pin number of the port.

        Returns:
            True if success else False.
        """
        # get current state
        data = self._read_port_configuration(port_index)

        if data is None:
            return False

        # update current state with new pin level
        new_data = (data & ~(1 << pin_number)) + (0 << pin_number)
        # write register
        self._write_port_configuration(port_index, new_data)
        # check new state
        data = self._read_port_configuration(port_index)

        if data != new_data:
            return False

        # update information
        self.config["input"][port_index] = data
        self.config["output"][port_index] = 0xFF - data
        return True

    def get_configuration(self) -> dict:
        """Reads the current configuration of the device.

        Returns:
            Configuration information of the device.
        """
        return self._get_configuration()

    def get_default_io_direction(self) -> list[int, int]:
        """Gets the default output configuration from pinout mapping.
        A high bit reflects an output and a low bit reflects an input.

        Returns:
            A list with two integers as a bitmask of each port.
        """
        default_output_settings = [0, 0]

        for value in self.pinout.values():
            # set bit position to high for output
            if value["direction"] == "out":
                default_output_settings[value["port"]] += 1 << value["pin"]

        return default_output_settings

    def enable_can_channel_relay(self, channel: int) -> bool:
        """Enables a hardware relay channel on the PCB.

        Args:
            channel: CAN channel (1...8)

        Returns:
            True if success else False.
        """
        # catch wrong channel selection
        if channel < 1 or channel > 8:
            raise CanSwitcherChannelError(f"CAN Switcher channel {channel} is not available.")

        # get the pin mask of channel
        for key, value in self.pinout.items():
            # select channel
            pinmask = (
                value["mask"]
                if (key.startswith("Route_CAN") and value["pin"] == channel - 1)
                else None
            )

            if pinmask is not None:
                port = value["port"]
                break

        # enable CAN channel and disable all other channel relays to prevent cross link,
        # channels needs to be on the same port
        return self.set_gpio_port_output_level(port, pinmask)

    def disable_can_channel_relay(self) -> bool:
        """Disables the hardware relay channels on PCB.

        Returns:
            True if success else False.
        """
        # grep the port of first CAN channel, all channels are on the same port
        return self.set_gpio_port_output_level(self.pinout["Route_CAN_1"]["port"], 0x00)

    def enable_can_interface_bridge(self) -> bool:
        """Connects CAN0 and CAN1 physically on the PCB.

        Returns:
            True if success else False.
        """
        if "Switch_CAN_Short" in self.pinout:
            return self.set_gpio_pin_output_level(
                self.pinout["Switch_CAN_Short"]["port"], self.pinout["Switch_CAN_Short"]["pin"], 1
            )
        return False

    def disable_can_interface_bridge(self) -> bool:
        """Disconnects CAN0 and CAN1 physically on the PCB.

        Returns:
            True if success else False.
        """
        if "Switch_CAN_Short" in self.pinout:
            return self.set_gpio_pin_output_level(
                self.pinout["Switch_CAN_Short"]["port"], self.pinout["Switch_CAN_Short"]["pin"], 0
            )
        return False

    def enable_usb_switch_pin(self) -> bool:
        """Sets the pin state to enable connection to Pi USB port.

        Returns:
            True if success else False.
        """
        return self.set_gpio_pin_output_level(
            self.pinout["USB_Switch"]["port"], self.pinout["USB_Switch"]["pin"], 1
        )

    def disable_usb_switch_pin(self) -> bool:
        """Sets the pin state to enable connection to external USB port.

        Returns:
            True if success else False.
        """
        return self.set_gpio_pin_output_level(
            self.pinout["USB_Switch"]["port"], self.pinout["USB_Switch"]["pin"], 0
        )

    def enable_eeprom_write_protection(self) -> bool:
        """Enables the EEPROM write protection if available.

        Returns:
            True if success else False.
        """
        if "Eeprom_WP" in self.pinout:
            return self.set_gpio_pin_output_level(
                self.pinout["Eeprom_WP"]["port"], self.pinout["Eeprom_WP"]["pin"], 1
            )

        return False

    def disable_eeprom_write_protection(self) -> bool:
        """Disables the EEPROM write protection if available.

        Returns:
            True if success else False.
        """
        if "Eeprom_WP" in self.pinout:
            return self.set_gpio_pin_output_level(
                self.pinout["Eeprom_WP"]["port"], self.pinout["Eeprom_WP"]["pin"], 0
            )

        return False

    def enable_external_relay(self, number: int) -> bool:
        """Enables the selected relay channel.

        Args:
            number: Number of the relay in range 1...6

        Returns:
            True if success else False.
        """
        if number not in range(1, 7):
            raise RelayIndexError()

        return self.set_gpio_pin_output_level(
            self.pinout[f"Relay_{number}"]["port"], self.pinout[f"Relay_{number}"]["pin"], 0
        )

    def disable_external_relay(self, number: int) -> bool:
        """Disables the selected relay channel.

        Args:
            number: Number of the relay in range 1...6

        Returns:
            True if success else False.

        Raises:
            RelayIndexError: If the specified relay index is out of range.
        """
        if number not in range(1, 7):
            raise RelayIndexError()

        return self.set_gpio_pin_output_level(
            self.pinout[f"Relay_{number}"]["port"], self.pinout[f"Relay_{number}"]["pin"], 1
        )

    @acquires_lock(lock=ResourceLock.TARGET_INTERACTION)
    def set_default_pin_state(self, name_filter: str = "") -> bool:
        """Reads the pin configuration from the pinout and sets the default values
        at the pins of the port expander.

        Args:
            name_filter: Optional string used to filter the pins to reset (infix match)

        Returns:
            True if success else False.
        """
        # flag as return value
        success = True

        for name, entry in self.pinout.items():
            if name_filter not in name:
                continue

            pin = entry["pin"]
            port = entry["port"]
            default = entry["default"]

            logger.debug(f"Set port {port} pin {pin} to level {default}")
            # try to set every pin
            if not self.set_gpio_pin_output_level(port, pin, default):
                logger.warning(f"Port {port} pin {pin} not set to {default}")
                # set flag
                success = False

        return success

    def get_default_pin_state(self) -> dict:
        """Returns the default pin state of the port expander.

        Returns:
            Dictionary with the default pin states.
        """
        return {key: value["default"] for key, value in self.pinout.items()}

    # Basics
    def _get_configuration(self) -> dict:
        """Reads the current configuration from the device.

        Returns:
            Configuration information of the device.
        """
        # check inputs and outputs
        self.config["input"][0] = self._read_port_configuration(0)
        self.config["input"][1] = self._read_port_configuration(1)

        # if a pin is not an input it is an output
        self.config["output"][0] = 0xFF - self.config["input"][0]
        self.config["output"][1] = 0xFF - self.config["input"][1]

        # check polarity inversion settings
        self.config["inverted"][0] = self._read_port_polarity_inversion(0)
        self.config["inverted"][1] = self._read_port_polarity_inversion(1)

        return self.config

    def _create_pin_mask_from_pinout(self) -> None:
        """Creates a mask byte for every pin from the pinout."""
        for value in self.pinout.values():
            value["mask"] = 1 << value["pin"]

    def _check_io_settings(self) -> bool:
        """Checks the current IO setting against the default setting.

        Returns:
            True if current setting matches the default else False.
        """
        # get current output settings
        output_settings = self.config["output"]
        # get default settings
        default_output_settings = self.get_default_io_direction()

        # compare to default settings
        if output_settings != default_output_settings:
            logger.debug("Current port configuration is not the default")
            logger.debug(f"-> expected: {default_output_settings}")
            logger.debug(f"-> current:  {output_settings}")
            return False

        return True

    def _read_port_configuration(self, port_index: int) -> int:
        """Reads port configuration register data.

        Args:
            port_index: Port index of the I2C device.

        Returns:
            One byte of data, None if port index does not exist.
        """
        reg = [self.__configurationReg0, self.__configurationReg1]

        try:
            return self._read_register_data(self.i2c_addr, reg[port_index])

        except IndexError:
            return None

    def _read_port_inputs(self, port_index: int):
        """Reads port input register data.

        Args:
            port_index: Port index of the I2C device.

        Returns:
            One byte of data, None if port index does not exist.
        """
        reg = [self.__inputReg0, self.__inputReg1]

        try:
            return self._read_register_data(self.i2c_addr, reg[port_index])

        except IndexError:
            return None

    def _read_port_outputs(self, port_index: int) -> int:
        """Reads port output register data.

        Args:
            port_index: Port index of the I2C device.

        Returns:
            One byte of data, None if port index does not exist.
        """
        reg = [self.__outputReg0, self.__outputReg1]

        try:
            return self._read_register_data(self.i2c_addr, reg[port_index])

        except IndexError:
            return None

    def _read_port_polarity_inversion(self, port_index: int) -> int:
        """Reads port polarity inversion register data.

        Args:
            port_index: Port index of the I2C device.

        Returns:
            One byte of data, None if port index does not exist.
        """
        reg = [self.__polarityInvReg0, self.__polarityInvReg1]

        try:
            return self._read_register_data(self.i2c_addr, reg[port_index])

        except IndexError:
            return None

    def _write_port_configuration(self, port_index: int, value: int) -> bool:
        """Writes port configuration register data.

        Args:
            port_index: Port index of the I2C device.
            value: Value to write to the register.

        Returns:
            True if success else False.
        """
        reg = [self.__configurationReg0, self.__configurationReg1]

        try:
            self._write_register_data(self.i2c_addr, reg[port_index], value)
            return True

        except IndexError:
            return False

    def _write_port_outputs(self, port_index: int, value: int) -> bool:
        """Writes port output register data.

        Args:
            port_index: Port index of the I2C device.
            value: Value to write to the register.

        Returns:
            True if success else False.
        """
        reg = [self.__outputReg0, self.__outputReg1]

        try:
            self._write_register_data(self.i2c_addr, reg[port_index], value)
            return True

        except IndexError:
            return False

    def _write_port_polarity_inversion(self, port_index: int, value: int) -> bool:
        """Writes port polarity inversion register data.

        Args:
            port_index: Port index of the I2C device.
            value: Value to write to the register.

        Returns:
            True if success else False.
        """
        reg = [self.__polarityInvReg0, self.__polarityInvReg1]

        try:
            self._write_register_data(self.i2c_addr, reg[port_index], value)
            return True

        except IndexError:
            return False

    def _read_register_data(self, i2c_addr: int, register: int) -> int:
        """Writes data from the device.

        Args:
            i2c_addr: Address of the I2C device.
            register: Register of the I2C device.

        Returns:
            One byte of data, None if port index does not exist.
        """
        return self.instance.read_byte_data(i2c_addr, register)

    def _write_register_data(self, i2c_addr: int, register: int, value: int) -> None:
        """Writes data to the device.

        Args:
            i2c_addr: Address of the I2C device.
            register: Register of the I2C device.
            value: Value to write to the register.
        """
        return self.instance.write_byte_data(i2c_addr, register, value)

    def _get_pin_output_level(self, port_level: int, pin_number: int) -> int:
        """Given the port level, returns the output level of a specific pin in the port.

        Args:
            port_level: State of the port.
            pin_number: Pin number in the selected port.

        Returns:
            The output level of a specific GPIO pin.
        """
        mask = 1 << pin_number
        return (port_level & mask) >> pin_number

    def get_clamp_pin_levels(self, clamp_ids: Iterable[str] = ("15", "30")) -> list[Clamp]:
        """Determines the output levels of the gpio pins associated with clamps and returns the
        results as a list of Clamp objects.

        Args:
            clamp_ids: Iterable which contains the clamp ids/names.

        Returns:
            A list of Clamp objects.
        """
        if not all(clamp_id in PortExpanderConfig.RELAYS for clamp_id in clamp_ids):
            raise USBConnectError(
                f"The specified IDs ({clamp_ids}) are not supported. "
                f"Please choose the following: "
                f"{', '.join(PortExpanderConfig.RELAYS)}"
            )

        clamps = [Clamp(name=clamp_id) for clamp_id in clamp_ids]
        if (gpio_port_level := self.get_gpio_port_level(PortExpanderConfig.EXTERNAL_PORT)) is None:
            return clamps

        for clamp in clamps:
            pin_number = PortExpanderConfig.RELAYS[clamp.name]
            pin_value = self._get_pin_output_level(gpio_port_level, pin_number)
            clamp.state = "on" if pin_value else "off"

        return clamps

    @acquires_lock(lock=ResourceLock.TARGET_INTERACTION)
    def set_clamp(self, clamp_id: str, action: Action, sleep_duration: int = 1) -> None:
        """Changes the status of the selected clamp/relay.

        Args:
            clamp_id: Name of the clamp.
            action: Whether the clamp should be turned on or off.
            sleep_duration: Amount of time to wait after setting the clamp (useful when chaining
                multiple calls).

        Raises:
            USBConnectError: If the specified clamp ID is not supported.
        """
        if clamp_id not in PortExpanderConfig.RELAYS:
            raise USBConnectError(
                f"The specified ID ({clamp_id}) is not supported. "
                f"Please choose one of the following: "
                f"{', '.join(PortExpanderConfig.RELAYS)}"
            )

        if not isinstance(action, Action):
            action = Action(action)

        pin_number = PortExpanderConfig.RELAYS[clamp_id]
        self.set_gpio_pin_output_level(
            PortExpanderConfig.EXTERNAL_PORT, pin_number, 1 if action else 0
        )
        time.sleep(sleep_duration)

class Switcher:
    """This class is a wrapper for the portexpander.

    Args:
        address: I2C device address of the port expander. Defaults to 0x74.

    Attributes:
        instance: Object for the port expander.
    """

    def __init__(self) -> None:
        # create the instance
        self.instance = Portexpander()

    def __enter__(self) -> object:
        """Context Manager initialisation.

        Returns:
            Switcher object.
        """
        return self

    def __exit__(
        self,
        exc_type: BaseException | None,
        exc_value: BaseException | None,
        traceback: "TracebackType | None",
    ) -> None:
        """Context Manager cleanup."""
        self.instance = None


class UsbSwitcher:
    """Constructor of the class initialises the portexpander to control the USB switch controller.

    Attributes:
        log_enable: Flag to enable log messages.
        switcher: Object for the port expander.
    """

    def __init__(self):
        self.log_enable = False

        try:
            self.__switcher = Switcher()
        except Exception:  # pylint: disable=broad-except
            self.__switcher = None

        with IdEeprom() as eep:
            self.version = eep.manufacturer_data["usb_switcher_standard"]

    def __enter__(self) -> "Self":
        """Context Manager initialisation.

        Returns:
            UsbSwitcher object.
        """
        return self

    def __exit__(
        self,
        exc_type: BaseException | None,
        exc_value: BaseException | None,
        traceback: "TracebackType | None",
    ) -> None:
        """Context Manager cleanup."""

    @property
    def switcher(self) -> Switcher:
        """Returns the Switcher instance.

        Raises:
            USBConnectError: If the Switcher instance is inactive.
        """
        if not self.__switcher:
            raise USBConnectError("The Switcher instance is unavailable.")
        return self.__switcher

    # HARDWARE FUNCTIONS #
    def connect_peripheral_to_pi(self) -> bool:
        """Set the portexpander pin state to select the routing of the peripheral to the
        Raspberry Pi.

        Returns:
            Pass indicator.
        """
        logger.info("Attach peripheral to Pi USB connection.")

        if self.version != "2.0":
            return self.switcher.instance.disable_usb_switch_pin()

        return self.switcher.instance.enable_usb_switch_pin()

    def connect_peripheral_to_external(self) -> bool:
        """Set the portexpander pin state to select the routing of the peripheral to the
        external USB connector.

        Returns:
            Pass indicator.
        """
        logger.info("Attach peripheral to external USB connector")

        if self.version != "2.0":
            return self.switcher.instance.enable_usb_switch_pin()

        return self.switcher.instance.disable_usb_switch_pin()


def usb_switcher_installed() -> bool:
    """Parses the device-tree directory and searches the content to see if the usb switcher
    is installed.

    Returns:
        True if the usb switcher is installed, False otherwise.
    """
    directory = Path("/proc/device-tree/hat/")
    usb_string = "usb_switcher"

    if not directory.is_dir():
        logger.error(f"Directory {directory} does not exist")
        return False

    for file_path in directory.glob("*"):
        if file_path.is_file():
            try:
                contents = file_path.read_text(encoding="utf-8")
                if usb_string in contents:
                    logger.debug(f"Found in {file_path}")
                    return True
            except Exception as exception:
                logger.error(f"Error reading file {file_path}: {exception}")
    return False


#######################
### USER EXCEPTIONS ###
#######################
class SMBusPeripheralError(Exception):
    """Peripheral is not initialised."""


class SMBusCommunicationError(Exception):
    """No communication to device address."""


class SMBusUndefinedError(Exception):
    """Undefined error on SMBus peripheral."""


class SMBusHardwareError(Exception):
    """Hardware not supported."""


class CanSwitcherChannelError(Exception):
    """Selected channel is out of range."""


class RelayIndexError(Exception):
    """Selected index is out of range."""
