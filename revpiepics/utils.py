"""
Utilities for EPICS and Revolution Pi IO interactions.

This module provides helper functions used by EPICS builders to:
- interpret RevPi IO values (e.g. bit-level status words),
- handle write callbacks from EPICS to RevPi,
- extract values from raw offset addresses.

Functions
---------
- status_bit_length: returns the bit length of a status word.
- record_write: callback to write from PV to RevPi output.
- get_io_offset_value: reads an IO value at a specific offset (low-level).

See Also
--------
RevPiEpics : Main class managing EPICS-PV bindings.
aio.builder_aio : Uses these helpers to define EPICS records from RevPi AIO modules.
"""

from typing import cast, Optional
from revpimodio2.io import IntIO
import logging

logger = logging.getLogger(__name__)

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
    from .revpiepics import RevPiEpics
    try:
        pv_name = pv_name.split(':')[-1]
        dic_mapping = RevPiEpics.get_dic_io_map()
        mapping = dic_mapping.get_by_pv_name(pv_name)
        if mapping is None:
            raise KeyError(f"PV '{pv_name}' is not associated with any IO.")
        if not mapping.update_record:
            mapping.update_record = True
    except Exception as exc:
        logger.error("Failed to write using PV %s: %s", pv_name, exc)

def get_io_offset_value(offset: int) -> Optional[int]:
    """Read the value of a RevPi IO by its memory offset.
    
    Returns the value of a RevPi IO by its memory offset.
    This is a low-level function for direct memory access.
    
    Parameters
    ----------
    offset : int
        The memory offset of the IO point.
        
    Returns
    -------
    int or None
        The value at the offset or None if unavailable.
        
    Raises
    ------
    TypeError
        If offset is not an integer.
    """
    from .revpiepics import RevPiEpics, RevPiEpicsInitError
    
    if not isinstance(offset, int):
        raise TypeError("offset must be an integer")
    
    try:
        # Get RevPi ModIO instance
        rev_pi = RevPiEpics.get_mod_io()
        
        if not rev_pi:
            raise RevPiEpicsInitError("RevPi ModIO instance not available")
        elif not rev_pi.io:
            raise RevPiEpicsInitError("RevPi IO interface not available")
        
        # Access IO point at offset
        io = cast(list, rev_pi.io[offset])
        io_point = cast(IntIO, io[0])
        value = io_point.value
        return value
        
    except IndexError:
        logger.error("Unable to access RevPi IO at offset %d - offset out of range", offset)
        return None
    except RevPiEpicsInitError as e:
        logger.error("RevPi not initialized when reading offset %d: %s", offset, e)
        return None
    except Exception as e:
        logger.error("Unexpected error reading offset %d: %s", offset, e)
        return None
