"""EPICS builder helper for Revolution-Pi *AIO* modules.

This module provides a *builder* function capable of translating raw IOs
exposed by *revpimodio2* into appropriate EPICS records (ai, ao, mbbi, etc.),
and registers it in the shared :data:`builder_registry` so that
:pymeth:`RevPiEpics.builder` can automatically discover and use it.
"""

from softioc import builder
from .revpiepics import RevPiEpics, logger
from .utils import status_bit_length, io_value_change, io_status_change, record_write, get_io_offset_value
from revpimodio2.pictory import ProductType, AIO
from revpimodio2.io import IntIO
from softioc.pythonSoftIoc import RecordWrapper

from typing import cast, Tuple

# ---------------------------------------------------------------------------
# Offset definitions — See the Revolution Pi documentation for the meaning
# of each address in an AIO module.
# ---------------------------------------------------------------------------
ANALOG_INPUT_OFFSETS = [0, 2, 4, 6]
ANALOG_INPUT_STATUS_OFFSETS = [8, 9, 10, 11]
TEMPERATURE_INPUT_OFFSETS = [12, 14]
TEMPERATURE_INPUT_STATUS_OFFSETS = [16, 17]
ANALOG_OUTPUT_STATUS_OFFSETS = [18, 19]
ANALOG_OUTPUT_OFFSETS = [20, 22]


def builder_aio(
    io_point: IntIO,
    pv_name: str,
    DRVL=None,
    DRVH=None,
    **fields,
) -> (RecordWrapper | None):
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
    parent_offset = io_point._parentdevice._offset
    offset = io_point.address - parent_offset
    record = None

    # ------------------------------------------------------------------
    # Analog inputs                                                    
    # ------------------------------------------------------------------
    if offset in ANALOG_INPUT_OFFSETS:
        record = builder.aIn(pv_name, initial_value=io_point.value, **fields)
        io_point.reg_event(io_value_change, as_thread=True)

    elif offset in ANALOG_INPUT_STATUS_OFFSETS:
        record = builder.mbbIn(
            pv_name,
            "OK",
            ("Below the range", "MAJOR"),
            ("Above the range", "MAJOR"),
            initial_value=status_bit_length(io_point.value),
            **fields,
        )
        io_point.reg_event(io_status_change, as_thread=True)

    # ------------------------------------------------------------------
    # Temperature inputs                                               
    # ------------------------------------------------------------------
    elif offset in TEMPERATURE_INPUT_OFFSETS:
        record = builder.aIn(pv_name, initial_value=io_point.value, **fields)
        io_point.reg_event(io_value_change, as_thread=True)

    elif offset in TEMPERATURE_INPUT_STATUS_OFFSETS:
        record = builder.mbbIn(
            pv_name,
            "OK",
            ("T<-200°C / short circuit", "MAJOR"),
            ("T>850°C / not connected", "MAJOR"),
            initial_value=status_bit_length(io_point.value),
            **fields,
        )
        io_point.reg_event(io_status_change, as_thread=True)

    # ------------------------------------------------------------------
    # Analog outputs                                                   
    # ------------------------------------------------------------------
    elif offset in ANALOG_OUTPUT_STATUS_OFFSETS:
        record = builder.mbbIn(
            pv_name,
            "OK",
            ("Temperature error", "MAJOR"),
            ("Open load", "MAJOR"),
            ("Internal error", "MAJOR"),
            ("Range error", "MAJOR"),
            ("Internal purposes", "MAJOR"),
            ("Supply voltage < 10.2V", "MAJOR"),
            ("Supply voltage > 28.8V", "MAJOR"),
            ("Connection timeout", "MAJOR"),
            initial_value=status_bit_length(io_point.value),
            **fields,
        )
        io_point.reg_event(io_status_change, as_thread=True)

    elif offset in ANALOG_OUTPUT_OFFSETS:
        revpi = RevPiEpics.get_revpi()

        if not revpi or not revpi.io:
            logger.error("Cannot access RevPi IOs for analog output processing.")
        else:
            out_range, out_multiplier, out_divisor, out_offset = _read_analog_out_params(offset, parent_offset)

            if out_range is not None and out_range > 0:
                range_min, range_max = _output_range(out_range)

                if (
                    isinstance(range_min, int) and
                    isinstance(range_max, int) and
                    isinstance(out_multiplier, int) and
                    isinstance(out_divisor, int) and
                    out_divisor != 0 and
                    isinstance(out_offset, int)
                ):
                    try:
                        value_min = float(DRVL) if DRVL is not None else ((range_min * out_multiplier) / out_divisor) + out_offset
                    except (TypeError, ValueError):
                        value_min = ((range_min * out_multiplier) / out_divisor) + out_offset

                    try:
                        value_max = float(DRVH) if DRVH is not None else ((range_max * out_multiplier) / out_divisor) + out_offset
                    except (TypeError, ValueError):
                        value_max = ((range_max * out_multiplier) / out_divisor) + out_offset

                    record = builder.aOut(
                        pv_name,
                        initial_value=io_point.value,
                        on_update_name=record_write,
                        DRVH=value_max,
                        DRVL=value_min,
                        **fields
                    )
                else:
                    logger.error("Incomplete conversion parameters for analog output '%s'", io_point.name)
            else:
                logger.error("Analog output '%s' is disabled or has invalid parameters", io_point.name)

    return record


def _output_range(range: int) -> Tuple[int | None, int | None]:
    """
    Converts an AIO range code into its corresponding engineering unit limits.

    Returns
    -------
    Tuple[int | None, int | None]
        A (min, max) tuple in either millivolts or microamps depending on the range.
    """
    match range:
        case AIO.OUT_RANGE_OFF:
            return (None, None)
        case AIO.OUT_RANGE_0_5V:
            return (0, 5000)
        case AIO.OUT_RANGE_0_10V:
            return (0, 10000)
        case AIO.OUT_RANGE_N5_5V:
            return (-5000, 5000)
        case AIO.OUT_RANGE_N10_10V:
            return (-10000, 10000)
        case AIO.OUT_RANGE_0_5P5V:
            return (0, 5500)
        case AIO.OUT_RANGE_0_11V:
            return (0, 11000)
        case AIO.OUT_RANGE_N5P5_5P5V:
            return (-5500, 5500)
        case AIO.OUT_RANGE_N11_11V:
            return (-11000, 11000)
        case AIO.OUT_RANGE_4_20MA:
            return (4000, 20000)
        case AIO.OUT_RANGE_0_20MA:
            return (0, 20000)
        case AIO.OUT_RANGE_0_24MA:
            return (0, 24000)
        case _:
            return (None, None)


def _read_analog_out_params(offset: int, parent_offset: int) -> Tuple[int | None, int | None, int | None, int | None]:
    """
    Reads range and scaling parameters for a given analog output channel.

    Parameters
    ----------
    offset : int
        The output offset within the module (e.g. 20 or 22).
    parent_offset : int
        The base offset of the AIO module.

    Returns
    -------
    Tuple[int | None, int | None, int | None, int | None]
        A tuple of (range, multiplier, divisor, offset) parameters.
    """
    offset_map = {
        20: {'range': 69, 'multiplier': 73, 'divisor': 75, 'offset': 77},
        22: {'range': 79, 'multiplier': 83, 'divisor': 85, 'offset': 87},
    }

    map_entry = offset_map.get(offset)
    if not map_entry:
        logger.error("Unknown analog output offset: %s", offset)
        return (None, None, None, None)

    return (
        get_io_offset_value(parent_offset + map_entry['range']),
        get_io_offset_value(parent_offset + map_entry['multiplier']),
        get_io_offset_value(parent_offset + map_entry['divisor']),
        get_io_offset_value(parent_offset + map_entry['offset']),
    )

# Register the builder for AIO modules
RevPiEpics._register_builder(ProductType.AIO, builder_aio)
