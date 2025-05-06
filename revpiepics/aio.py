from softioc import builder
from .revpiepics import builder_registry, RevPiEpics, logger
from revpimodio2.pictory import ProductType
from revpimodio2.io import IntIO

def builder_aio(parent: RevPiEpics, io_point: IntIO, pv_name: str, DRVL, DRVH, **fields):
    """
    Builder function for Analog Input/Output (AIO) devices.

    Args:
        parent (RevPiEpics): Parent EPICS manager instance.
        io_point: RevPi IO point object.
        pv_name (str): EPICS process variable name.
        DRVL (optional): Lower display limit.
        DRVH (optional): Upper display limit.
        **fields: Additional EPICS record fields.

    Returns:
        record: The created EPICS record or None.
    """
    offset = io_point.address - io_point._parentdevice._offset
    record = None

    if offset in [0, 2, 4, 6]:
        record = builder.aIn(pv_name, initial_value=io_point.value, **fields)
        io_point.reg_event(
            lambda event: parent._io_change(record, event.iovalue, event.ioname),
            as_thread=True
        )

    elif offset in [8, 9, 10, 11]:
        record = builder.mbbIn(
            pv_name, 'OK',
            ('Below the range', 'MAJOR'),
            ('Above the range', 'MAJOR'),
            initial_value = parent._status_convert(io_point.value),
            **fields
        )
        io_point.reg_event(
            lambda event: parent._io_change(record, parent._status_convert(event.iovalue), event.ioname),
            as_thread=True
        )

    elif offset in [12, 14]:
        record = builder.aIn(pv_name, initial_value=io_point.value, **fields)
        io_point.reg_event(
            lambda event: parent._io_change(record, event.iovalue, event.ioname),
            as_thread=True
        )

    elif offset in [16, 17]:
        record = builder.mbbIn(
            pv_name, 'OK',
            ('T<-200°C/short circuit', 'MAJOR'),
            ('T>850°C/not connected', 'MAJOR'),
            initial_value = parent._status_convert(io_point.value),
            **fields
        )
        io_point.reg_event(
            lambda event: parent._io_change(record, parent._status_convert(event.iovalue), event.ioname),
            as_thread=True
        )

    elif offset in [18, 19]:
        record = builder.mbbIn(
            pv_name, 'OK',
            ('Temperature error', 'MAJOR'),
            ('Open load', 'MAJOR'),
            ('Internal error', 'MAJOR'),
            ('Range error', 'MAJOR'),
            ('Internal purposes', 'MAJOR'),
            ('Supply voltage <10.2 V', 'MAJOR'),
            ('Supply voltage >28.8 V', 'MAJOR'),
            ('Timeout when connecting', 'MAJOR'),
            initial_value=parent._status_convert(io_point.value),
            **fields
        )
        io_point.reg_event(
            lambda event: parent._io_change(record, parent._status_convert(event.iovalue), event.ioname),
            as_thread=True
        )

    elif offset in [20, 22]:

        out_range = None
        out_divisor = None
        out_multiplier = None
        out_offset = None

        if offset == 20 :
            out_range = parent._revpi.io[io_point._parentdevice._offset + 69][0].value
            out_multiplier = parent._revpi.io[io_point._parentdevice._offset + 73][0].value
            out_divisor = parent._revpi.io[io_point._parentdevice._offset + 75][0].value
            out_offset = parent._revpi.io[io_point._parentdevice._offset + 77][0].value

        if offset == 22:
            out_range = parent._revpi.io[io_point._parentdevice._offset + 79][0].value
            out_multiplier = parent._revpi.io[io_point._parentdevice._offset + 83][0].value
            out_divisor = parent._revpi.io[io_point._parentdevice._offset + 85][0].value
            out_offset = parent._revpi.io[io_point._parentdevice._offset + 87][0].value
        
        if out_range > 0:

            range_min, range_max = _out_range(out_range)

            if range_min != None and range_max != None:

                if DRVL is not None :
                    if isinstance(DRVL, (int, float)):
                        value_min = DRVL
                    elif isinstance(DRVL, str):
                        try:
                            value_min = float(DRVL)
                        except ValueError:
                            value_min = ((range_min * out_multiplier) / out_divisor) + out_offset
                else:
                    value_min = ((range_min*out_multiplier)/out_divisor)+out_offset
                
                if DRVH is not None: 
                    if isinstance(DRVH, (int, float)):
                        value_max = DRVH
                    elif isinstance(DRVH, str):
                        try:
                            value_max = float(DRVH)
                        except ValueError:
                            value_max = ((range_max*out_divisor)/out_divisor)+out_offset
                else:
                    value_max = ((range_max*out_divisor)/out_divisor)+out_offset

                record = builder.aOut(
                    pv_name,
                    initial_value=io_point.value,
                    on_update=lambda value: parent._record_write(value, io_point, pv_name),
                    DRVH=value_max,
                    DRVL=value_min, 
                    **fields)
        else:
            logger.error(f"Output {io_point.name} is not enabled")

    else:
        logger.error(f"Unsupported offset: {offset}")

    return record

def _out_range(range: int):
    match range: 
        case 0 : 
            return (None,None)
        case 1:
            return (0,5000)
        case 2:
            return (0,10000)
        case 3:
            return (-5000,5000)
        case 4:
            return (-10000,10000)
        case 5:
            return (0,5500)
        case 6:
            return (0,11000)
        case 7:
            return (-5500,5500)
        case 8:
            return (-11000,11000)
        case 9:
            return (4000,20000)
        case 10:
            return (0,20000)
        case 11:
            return (0,24000)
        case _:
            return (None,None)

builder_registry[ProductType.AIO] = builder_aio
