"""
Utilities for EPICS and Revolution Pi IO interactions.

This module provides helper functions used by EPICS builders to:
- interpret RevPi IO values (e.g. bit-level status words),
- manage PV-to-IO and IO-to-PV value propagation,
- handle write callbacks from EPICS to RevPi,
- extract values from raw offset addresses.

Functions
---------
- status_bit_length: returns the bit length of a status word.
- io_value_change: callback to propagate RevPi input changes to EPICS PVs.
- io_status_change: callback to update status PVs based on status words.
- record_write: callback to write from PV to RevPi output.
- get_io_offset_value: reads an IO value at a specific offset (low-level).

See Also
--------
RevPiEpics : Main class managing EPICS-PV bindings.
aio.builder_aio : Uses these helpers to define EPICS records from RevPi AIO modules.
"""

from .revpiepics import RevPiEpics, logger
from typing import cast
from revpimodio2.io import IntIO

def status_bit_length(value: int) -> int:
    """
    Converts a status value to an integer representing the number
    of significant bits (used as a basic error code).

    Parameters
    ----------
    value : int
        The status word value.

    Returns
    -------
    int
        Number of significant bits.
    """
    return int(value).bit_length()

def io_value_change(event) -> None:
    """
    Callback for changes in IO status values.
    """
    mapping = RevPiEpics.get_io_name(event.ioname)
    if mapping is not None:
        mapping.record.set(event.iovalue)
        logger.debug("IO %s → PV %s = %s", event.ioname, mapping.pv_name, event.iovalue)
    else:
        logger.error("No PV is mapped to IO '%s' in 'io_value_change'.", event.ioname)

def io_status_change(event) -> None:
    """
    Callback for changes in IO status values.
    Converts the status word and updates the associated PV accordingly.

    Parameters
    ----------
    event : object
        Event with `ioname` and `iovalue` attributes.
    """
    mapping = RevPiEpics.get_io_name(event.ioname)
    if mapping is not None:
        mapping.record.set(status_bit_length(event.iovalue))
        logger.debug("IO %s → PV %s = %s", event.ioname, mapping.pv_name, event.iovalue)
    else:
        logger.error("No PV is mapped to IO '%s' in '_io_status_change'.", event.ioname)

def record_write(value: float, pv_name: str) -> None:
    """
    Callback when an EPICS PV value is written to.
    Converts and writes the new value to the corresponding RevPi IO.

    Parameters
    ----------
    value : float
        New value from the EPICS PV.
    pv_name : str
        Name of the PV.
    """
    try:
        pv_name = pv_name.split(':')[-1]
        mapping = RevPiEpics.get_pv_name(pv_name)
        if mapping is None:
            raise KeyError(f"PV '{pv_name}' is not associated with any IO.")
        mapping.io_point.value = round(value)
        logger.debug("PV %s → IO %s = %d", mapping.pv_name, mapping.io_name, round(value))
    except Exception as exc:
        logger.error("Failed to write using PV %s: %s", pv_name, exc)

def get_io_offset_value(offset: int) -> (int | None):
    """
    Returns the value of a RevPi IO by its memory offset.

    Parameters
    ----------
    offset : int
        The memory offset of the IO point.
    
    Returns
    -------
    int or None
        The value at the offset or None if unavailable.
    """
    try:
        revpi = RevPiEpics.get_revpi()
        io = cast(list, revpi.io[offset]) # type: ignore
        io_point = cast(IntIO,io[0])
        value = io_point.value
        return value
    except IndexError:
        logger.error("Unable to access RevPi IOs when reading offset value %d.", offset)
        return None