"""EPICS builder helper for Revolution-Pi *AIO* modules.

This module exposes a *builder* callable able to translate the raw IO
exported by *revpimodio2* into the proper EPICS record (ai/ao/mbbi…) and
registers it inside the shared :data:`builder_registry` so that
:pymeth:`RevPiEpics.builder` can discover it automatically.
"""
from softioc import builder

from .revpiepics import builder_registry, RevPiEpics, logger
from revpimodio2.pictory import ProductType, AIO
from revpimodio2.io import IntIO

# ---------------------------------------------------------------------------
# Offset maps — see the Revolution‑Pi documentation for the exact meaning of
# each address inside an AIO module.
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
):
    """Create an EPICS record bound to *io_point*.

    The record type depends on the IO *offset* inside the AIO module:

    * **0/2/4/6** → analogue *input* (ai)
    * **8/9/10/11** → status for the analogue inputs (mbbi)
    * **12/14** → temperature *input* (ai)
    * **16/17** → status for the temperature channels (mbbi)
    * **18/19** → status for an analogue *output* (mbbi)
    * **20/22** → analogue *output*  (ao)

    Parameters
    ----------
    io_point : IntIO
        Handle returned by *revpimodio2*.
    pv_name : str
        Name of the EPICS PV to create.
    DRVL / DRVH : int | float | str | None
        Display limits forwarded to *builder.aOut()* when applicable.
    **fields : dict
        Extra keyword arguments passed verbatim to *softioc.builder*.

    Returns
    -------
    PythonDevice | None
        The created record or *None* on error.
    """
    parent_offset = io_point._parentdevice._offset
    offset = io_point.address - parent_offset
    record = None

    # ------------------------------------------------------------------
    # Analogue inputs                                                   
    # ------------------------------------------------------------------
    if offset in ANALOG_INPUT_OFFSETS:
        record = builder.aIn(pv_name, initial_value=io_point.value, **fields)
        io_point.reg_event(RevPiEpics._io_value_change, as_thread=True)

    elif offset in ANALOG_INPUT_STATUS_OFFSETS:
        record = builder.mbbIn(
            pv_name,
            "OK",
            ("Below the range", "MAJOR"),
            ("Above the range", "MAJOR"),
            initial_value=RevPiEpics._status_convert(io_point.value),
            **fields,
        )
        io_point.reg_event(RevPiEpics._io_status_change, as_thread=True)

    # ------------------------------------------------------------------
    # Temperature inputs                                                
    # ------------------------------------------------------------------
    elif offset in TEMPERATURE_INPUT_OFFSETS:
        record = builder.aIn(pv_name, initial_value=io_point.value, **fields)
        io_point.reg_event(RevPiEpics._io_value_change, as_thread=True)

    elif offset in TEMPERATURE_INPUT_STATUS_OFFSETS:
        record = builder.mbbIn(
            pv_name,
            "OK",
            ("T < -200°C / short circuit", "MAJOR"),
            ("T > 850°C / not connected", "MAJOR"),
            initial_value=RevPiEpics._status_convert(io_point.value),
            **fields,
        )
        io_point.reg_event(RevPiEpics._io_status_change, as_thread=True)

    # ------------------------------------------------------------------
    # Analogue outputs                                                  
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
            ("Supply voltage <10.2V", "MAJOR"),
            ("Supply voltage >28.8V", "MAJOR"),
            ("Timeout when connecting", "MAJOR"),
            initial_value=RevPiEpics._status_convert(io_point.value),
            **fields,
        )
        io_point.reg_event(RevPiEpics._io_status_change, as_thread=True)

    elif offset in ANALOG_OUTPUT_OFFSETS:
        
        out_range = None
        out_divisor = None
        out_multiplier = None
        out_offset = None

        if offset == 20:
            out_range = RevPiEpics._revpi.io[parent_offset + 69][0].value
            out_multiplier = RevPiEpics._revpi.io[parent_offset + 73][0].value
            out_divisor = RevPiEpics._revpi.io[parent_offset + 75][0].value
            out_offset = RevPiEpics._revpi.io[parent_offset + 77][0].value

        if offset == 22:
            out_range = RevPiEpics._revpi.io[parent_offset + 79][0].value
            out_multiplier = RevPiEpics._revpi.io[parent_offset + 83][0].value
            out_divisor = RevPiEpics._revpi.io[parent_offset + 85][0].value
            out_offset = RevPiEpics._revpi.io[parent_offset + 87][0].value

        if out_range > 0:
            range_min, range_max = _output_range(out_range)

            # Calculate default limits when none supplied by the caller
            if DRVL is not None:
                try:
                    value_min = float(DRVL)
                except (TypeError, ValueError):
                    value_min = ((range_min * out_multiplier) / out_divisor) + out_offset
            else:
                value_min = ((range_min * out_multiplier) / out_divisor) + out_offset

            if DRVH is not None:
                try:
                    value_max = float(DRVH)
                except (TypeError, ValueError):
                    value_max = ((range_max * out_multiplier) / out_divisor) + out_offset
            else:
                value_max = ((range_max * out_multiplier) / out_divisor) + out_offset

            record = builder.aOut(
                pv_name,
                initial_value=io_point.value,
                on_update_name=RevPiEpics._record_write,
                DRVH=value_max,
                DRVL=value_min,
                **fields,
            )
        else:
            logger.error("Output %s is not enabled", io_point.name)

    else:
        logger.error("Unsupported offset: %d", offset)

    return record

def _output_range(range: int):    
    """Translate the *AIO* range code into engineering units.

    Returns a *(min, max)* tuple expressed either in **millivolts** or
    **micro-amps** depending on the selected range.
    """

    match range: 
        case AIO.OUT_RANGE_OFF : 
            return (None,None) # OFF
        case AIO.OUT_RANGE_0_5V:
            return (0,5000) # 0V - +5 V
        case AIO.OUT_RANGE_0_10V:
            return (0,10000) # 0V - +10 V
        case AIO.OUT_RANGE_N5_5V:
            return (-5000,5000) # -5V - +5V
        case AIO.OUT_RANGE_N10_10V:
            return (-10000,10000) # -10V - +10V
        case AIO.OUT_RANGE_0_5P5V:
            return (0,5500) # 0V - 5,5V
        case AIO.OUT_RANGE_0_11V:
            return (0,11000) # 0V - 11V
        case AIO.OUT_RANGE_N5P5_5P5V:
            return (-5500,5500) # -5,5 V - 5,5V
        case AIO.OUT_RANGE_N11_11V:
            return (-11000,11000) # -11V - 11V
        case AIO.OUT_RANGE_4_20MA:
            return (4000,20000) # 4mA - 20mA
        case AIO.OUT_RANGE_0_20MA:
            return (0,20000) # 0mA - 20mA
        case AIO.OUT_RANGE_0_20MA:
            return (0,24000) # 0mA - 24mA
        case _:
            return (None,None)

builder_registry[ProductType.AIO] = builder_aio
