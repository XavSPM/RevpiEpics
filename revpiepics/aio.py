"""
EPICS builder for Revolution Pi AIO modules.

This module defines a `builder_aio` function that converts raw `revpimodio2` IO points
from AIO modules into EPICS records (`ai`, `ao`, `mbbi`, etc.) using `softioc.builder`.

The function is automatically registered with `RevPiEpics` so that all AIO modules
can be handled transparently via `RevPiEpics.builder()`.

Supported mappings
------------------
Offset → Record type:

- 0, 2, 4, 6 → Analog input (`ai`)
- 8–11 → Analog input status (`mbbi`)
- 12, 14 → Temperature input (`ai`)
- 16, 17 → Temperature input status (`mbbi`)
- 18, 19 → Analog output status (`mbbi`)
- 20, 22 → Analog output (`ao`)

See Also
--------
RevPiEpics.builder : High-level automatic builder method
"""

from softioc import builder

import logging
from .recod import RecordDirection, RecordType
from .iomap import IOMap
from .utils import status_bit_length, record_write, get_io_offset_value

from revpimodio2.pictory import ProductType, AIO
from revpimodio2.io import IntIO

from typing import Tuple, Optional

# ---------------------------------------------------------------------------
# Offset definitions — See the Revolution Pi documentation for the meaning
# of each address in an AIO module.
# ---------------------------------------------------------------------------
# Analog input channels
ANALOG_INPUT_OFFSETS = [0, 2, 4, 6]

# Status registers for analog inputs
ANALOG_INPUT_STATUS_OFFSETS = [8, 9, 10, 11]

# Temperature input channels
TEMPERATURE_INPUT_OFFSETS = [12, 14]

# Status registers for temperature inputs
TEMPERATURE_INPUT_STATUS_OFFSETS = [16, 17]

# Status registers for analog outputs
ANALOG_OUTPUT_STATUS_OFFSETS = [18, 19]

# Analog output channels
ANALOG_OUTPUT_OFFSETS = [20, 22]

logger = logging.getLogger(__name__)

def builder_aio(
    io_name: str,
    io_point: IntIO,
    pv_name: str,
    DRVL=None,
    DRVH=None,
    **fields,
) -> Optional[IOMap]:
    """
    Create an EPICS record bound to *io_point*.

    The record type is determined by the IO *offset* inside the AIO module:

    * **0/2/4/6** → analog *input* (ai)
    * **8/9/10/11** → input *status* (mbbi)
    * **12/14** → temperature *input* (ai)
    * **16/17** → temperature *status* (mbbi)
    * **18/19** → output *status* (mbbi)
    * **20/22** → analog *output* (ao)

    Parameters
    ----------
    io_point : IntIO
        The IO object returned by *revpimodio2*.
    pv_name : str
        The EPICS process variable name to create.
    DRVL / DRVH : int | float | str | None
        Display limits forwarded to *builder.aOut()*, if applicable.
    **fields : dict
        Additional keyword arguments passed directly to *softioc.builder*.

    Returns
    -------
    RecordWrapper | None
        The created record, or *None* if an error occurred.
    """
    # Calculate the relative offset within the AIO module
    parent_offset = io_point._parentdevice._offset
    offset = io_point.address - parent_offset
    
    # Initialize variables to track the created record and its properties
    record = None
    record_direction = None
    record_type = None

    # ------------------------------------------------------------------
    # Analog inputs
    # ------------------------------------------------------------------
    if offset in ANALOG_INPUT_OFFSETS:
        # Create analog input record with current IO value as initial value
        record = builder.aIn(pv_name, initial_value=io_point.value, **fields)
        record_direction = RecordDirection.INPUT
        record_type = RecordType.ANALOG

    elif offset in ANALOG_INPUT_STATUS_OFFSETS:
        # Create multi-bit binary input for analog input status
        record = builder.mbbIn(
            pv_name,
            "OK",                          # State 0: Normal operation
            ("Below the range", "MAJOR"),  # State 1: Under-range alarm
            ("Above the range", "MAJOR"),  # State 2: Over-range alarm
            initial_value=status_bit_length(io_point.value),
            **fields,
        )
        record_direction = RecordDirection.INPUT
        record_type = RecordType.STATUS

    # ------------------------------------------------------------------
    # Temperature inputs
    # ------------------------------------------------------------------
    elif offset in TEMPERATURE_INPUT_OFFSETS:
        # Create analog input record for temperature measurement
        record = builder.aIn(pv_name, initial_value=io_point.value, **fields)
        record_direction = RecordDirection.INPUT
        record_type = RecordType.ANALOG

    elif offset in TEMPERATURE_INPUT_STATUS_OFFSETS:
        # Create multi-bit binary input for temperature sensor status
        record = builder.mbbIn(
            pv_name,
            "OK",                                   # State 0: Normal operation
            ("T<-200°C / short circuit", "MAJOR"),  # State 1: Sensor short circuit
            ("T>850°C / not connected", "MAJOR"),   # State 2: Sensor disconnected
            initial_value=status_bit_length(io_point.value),
            **fields,
        )
        record_direction = RecordDirection.INPUT
        record_type = RecordType.ANALOG

    # ------------------------------------------------------------------
    # Analog outputs
    # ------------------------------------------------------------------
    elif offset in ANALOG_OUTPUT_STATUS_OFFSETS:
        # Create multi-bit binary input for analog output status monitoring
        record = builder.mbbIn(
            pv_name,
            "OK",                                   # State 0: Normal operation
            ("Temperature error", "MAJOR"),         # State 1: Thermal protection
            ("Open load", "MAJOR"),                 # State 2: Load disconnected
            ("Internal error", "MAJOR"),            # State 3: Hardware malfunction
            ("Range error", "MAJOR"),               # State 4: Output value out of range
            ("Internal purposes", "MAJOR"),         # State 5: Reserved for internal use
            ("Supply voltage < 10.2V", "MAJOR"),    # State 6: Under-voltage condition
            ("Supply voltage > 28.8V", "MAJOR"),    # State 7: Over-voltage condition
            ("Connection timeout", "MAJOR"),        # State 8: Communication timeout
            initial_value=status_bit_length(io_point.value),
            **fields,
        )
        record_direction = RecordDirection.INPUT
        record_type = RecordType.STATUS

    elif offset in ANALOG_OUTPUT_OFFSETS:
        # Create analog output record with proper scaling and range validation
        from .revpiepics import RevPiEpics
        revpi = RevPiEpics.get_mod_io()

        if not revpi or not revpi.io:
            logger.error("Cannot access RevPi IOs for analog output processing.")
        else:
            # Read output configuration parameters from the device
            out_range, out_multiplier, out_divisor, out_offset = _read_analog_out_params(offset, parent_offset)

            # Validate that the output channel is properly configured
            if out_range is not None and out_range > 0:
                # Get the physical range limits based on the configured output type
                range_min, range_max = _output_range(out_range)

                # Ensure all parameters are valid integers for calculation
                if (
                    isinstance(range_min, int) and
                    isinstance(range_max, int) and
                    isinstance(out_multiplier, int) and
                    isinstance(out_divisor, int) and
                    out_divisor != 0 and
                    isinstance(out_offset, int)
                ):
                    # Calculate engineering unit limits from raw ADC values
                    # Apply user-defined limits if provided, otherwise use calculated limits
                    try:
                        value_min = float(DRVL) if DRVL is not None else ((range_min * out_multiplier) / out_divisor) + out_offset
                    except (TypeError, ValueError):
                        value_min = ((range_min * out_multiplier) / out_divisor) + out_offset

                    try:
                        value_max = float(DRVH) if DRVH is not None else ((range_max * out_multiplier) / out_divisor) + out_offset
                    except (TypeError, ValueError):
                        value_max = ((range_max * out_multiplier) / out_divisor) + out_offset

                    # Create analog output record with proper limits and write callback
                    record = builder.aOut(
                        pv_name,
                        initial_value=io_point.value,
                        on_update_name=record_write,  # Callback for writing to hardware
                        DRVH=value_max,               # High operating range
                        DRVL=value_min,               # Low operating range
                        **fields
                    )
                    record_direction = RecordDirection.OUTPUT
                    record_type = RecordType.ANALOG
                else:
                    logger.error("Incomplete conversion parameters for analog output '%s'", io_point.name)
            else:
                logger.error("Analog output '%s' is disabled or has invalid parameters", io_point.name)
    
    # Create and return the IO mapping if record creation was successful
    if record and record_direction and record_type : 
        mapping = IOMap(
                    io_name=io_name,
                    pv_name=pv_name,
                    io_point=io_point,
                    record=record,
                    direction=record_direction,
                    record_type=record_type
                )
        return mapping
    else:
        return None


def _output_range(range: int) -> Tuple[int | None, int | None]:
    """
    Convert an AIO range code into its corresponding engineering unit limits.

    This function maps the Revolution Pi AIO module's range configuration codes
    to their physical output limits in millivolts (for voltage outputs) or 
    microamps (for current outputs).

    Parameters
    ----------
    range : int
        The range configuration code from the AIO module configuration.
        See revpimodio2.pictory.AIO for available range constants.

    Returns
    -------
    Tuple[int | None, int | None]
        A (min, max) tuple representing the output range:
        - For voltage outputs: values in millivolts (mV)
        - For current outputs: values in microamps (μA)
        - Returns (None, None) for disabled or unknown ranges

    Examples
    --------
    >>> _output_range(AIO.OUT_RANGE_0_10V)
    (0, 10000)  # 0 to 10V in millivolts
    
    >>> _output_range(AIO.OUT_RANGE_4_20MA)
    (4000, 20000)  # 4 to 20mA in microamps
    """
    match range:
        case AIO.OUT_RANGE_OFF:
            return None, None
        # Voltage output ranges (in millivolts)
        case AIO.OUT_RANGE_0_5V:
            return 0, 5000
        case AIO.OUT_RANGE_0_10V:
            return 0, 10000
        case AIO.OUT_RANGE_N5_5V:
            return -5000, 5000
        case AIO.OUT_RANGE_N10_10V:
            return -10000, 10000
        case AIO.OUT_RANGE_0_5P5V:
            return 0, 5500
        case AIO.OUT_RANGE_0_11V:
            return 0, 11000
        case AIO.OUT_RANGE_N5P5_5P5V:
            return -5500, 5500
        case AIO.OUT_RANGE_N11_11V:
            return -11000, 11000
        # Current output ranges (in microamps)
        case AIO.OUT_RANGE_4_20MA:
            return 4000, 20000
        case AIO.OUT_RANGE_0_20MA:
            return 0, 20000
        case AIO.OUT_RANGE_0_24MA:
            return 0, 24000
        case _:
            # Unknown or unsupported range
            return None, None


def _read_analog_out_params(offset: int, parent_offset: int) -> Tuple[int | None, int | None, int | None, int | None]:
    """
    Read range and scaling parameters for a given analog output channel.

    This function retrieves the configuration parameters stored in the Revolution Pi
    AIO module's process image that are used for converting between engineering units
    and raw DAC values for analog outputs.

    Parameters
    ----------
    offset : int
        The output offset within the module (20 for channel 1, 22 for channel 2).
        This corresponds to the data register addresses in the AIO module.
    parent_offset : int
        The base offset of the AIO module in the global process image.
        Used to calculate absolute addresses for parameter retrieval.

    Returns
    -------
    Tuple[int | None, int | None, int | None, int | None]
        A tuple containing (range, multiplier, divisor, offset) parameters:
        - range: Output range configuration code (voltage/current type and limits)
        - multiplier: Scaling factor numerator for unit conversion
        - divisor: Scaling factor denominator for unit conversion  
        - offset: Zero-point offset for the conversion formula
        Returns (None, None, None, None) if the offset is not recognized.
    """
    # Mapping of output data offsets to their corresponding parameter addresses
    # These offsets are defined in the Revolution Pi AIO documentation
    offset_map = {
        20: {  # Channel 1 parameter addresses
            'range': 69,       # Range configuration register
            'multiplier': 73,  # Multiplier register
            'divisor': 75,     # Divisor register
            'offset': 77,      # Offset register
        },
        22: {  # Channel 2 parameter addresses
            'range': 79,       # Range configuration register
            'multiplier': 83,  # Multiplier register
            'divisor': 85,     # Divisor register
            'offset': 87,      # Offset register
        },
    }

    # Look up the parameter addresses for the given output channel
    map_entry = offset_map.get(offset)
    if not map_entry:
        logger.error("Unknown analog output offset: %s", offset)
        return None, None, None, None

    # Read the actual parameter values from the process image
    return (
        get_io_offset_value(parent_offset + map_entry['range']),
        get_io_offset_value(parent_offset + map_entry['multiplier']),
        get_io_offset_value(parent_offset + map_entry['divisor']),
        get_io_offset_value(parent_offset + map_entry['offset']),
    )

def _register_builder():
    """
    Register the AIO builder function with the RevPiEpics framework.
    
    This function automatically registers the builder_aio function to handle
    all AIO (Analog Input/Output) module types when RevPiEpics.builder() is called.
    The registration allows transparent handling of AIO modules without requiring
    explicit module type checking in user code.
    
    This function is called automatically when the module is imported.
    """
    from .revpiepics import RevPiEpics
    RevPiEpics.register_builder(ProductType.AIO, builder_aio)

# Automatically register the builder when the module is imported
_register_builder()