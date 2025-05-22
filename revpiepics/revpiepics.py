import atexit
import logging
import functools
from typing import Dict, Callable, Optional, cast

import revpimodio2
from revpimodio2.io import IntIO
from softioc.pythonSoftIoc import RecordWrapper

from softioc import softioc, builder



# Registers builder functions depending on the module type

logger = logging.getLogger(__name__)

class RevPiEpics:
    """
    Bridge between a Revolution Pi and EPICS.

    The class exposes RevPi I/O points as EPICS process variables (PVs),
    and keeps both systems synchronized.
    """

    __map_io_to_pv: Dict[str, str] = {}
    __map_pv_to_io: Dict[str, str] = {}
    __liste_pv: Dict[str, RecordWrapper] = {}
    __liste_io: Dict[str, IntIO] = {}
    __revpi: revpimodio2.RevPiModIO | None = None
    __builder_registry: Dict[int, Callable] = {}
    __cleanup = False

    @staticmethod
    def _requires_initialization(func):
        """
        Static decorator used to check that the class has been properly
        initialized before calling certain methods.
        """
        @functools.wraps(func)
        def wrapper(cls, *args, **kwargs):
            if cls.__revpi is None:
                raise RuntimeError("RevPiEpics must be initialized before calling this.")
            return func(cls, *args, **kwargs)
        return wrapper

    @classmethod
    def initialize(cls, cycletime: int = 200, debug: bool = False, cleanup: bool = True) -> None:
        """
        Initializes the connection to the Revolution Pi with the given parameters.

        Parameters
        ----------
        cycletime : int
            Cycle time in milliseconds (default: 200 ms).
        debug : bool
            Enables debug logging mode if True.
        cleanup : bool
            Enables reset of outputs on exit if True.
        """
        cls.__revpi = revpimodio2.RevPiModIO(autorefresh=True, debug=debug)
        cls.__revpi.cycletime = cycletime

        cls.__cleanup = cleanup

        logging.basicConfig(
            level=logging.DEBUG if debug else logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s" if debug else "[%(levelname)s]: %(message)s"
        )

    @classmethod
    @_requires_initialization
    def builder(
        cls,
        io_name: str,
        pv_name: Optional[str] = None,
        DRVL: Optional[float] = None,
        DRVH: Optional[float] = None,
        **fields,
    ) -> (RecordWrapper | None):
        """
        Creates an EPICS record (PV) and binds it to a RevPi IO.

        Parameters
        ----------
        io_name : str
            Name of the IO to bind.
        pv_name : Optional[str]
            Name of the PV to create (optional, defaults to io_name).
        DRVL : Optional[float]
            Lower display limit.
        DRVH : Optional[float]
            Upper display limit.
        **fields :
            Additional fields passed to the PV constructor.

        Returns
        -------
        PythonDevice
            The created EPICS record, or None if an error occurred.
        """
        if cls.__revpi is None:
            logger.error("RevPi instance is not initialized. Call 'initialize()' before using 'builder()'.")
            return None

        if not hasattr(cls.__revpi.io, io_name):
            logger.error("IO name %s not found in RevPi IOs.", io_name)
            return None

        if io_name in cls.__liste_io:
            logger.error("The IO '%s' is already bound to a PV.", io_name)
            return None

        if pv_name and pv_name in cls.__liste_pv:
            logger.error("The PV name '%s' is already in use.", pv_name)
            return None

        io_point = getattr(cls.__revpi.io, io_name)
        product_type = io_point._parentdevice._producttype
        builder_func = cls.__builder_registry.get(product_type)

        if builder_func is None:
            logger.warning("No builder registered for product type %s.", product_type)
            return None

        if pv_name is None:
            pv_name = io_name

        record = builder_func(io_point=io_point, pv_name=pv_name, DRVL=DRVL, DRVH=DRVH, **fields)

        if record:
            cls.__map_io_to_pv[io_name] = pv_name
            cls.__map_pv_to_io[pv_name] = io_name
            cls.__liste_io[io_name] = io_point
            cls.__liste_pv[pv_name] = record

        return record

    @classmethod
    def _io_value_change(cls, event) -> None:
        """
        Callback triggered by revpimodio2 when an input value changes.

        Parameters
        ----------
        event : Event
            Event containing the IO name and its new value.
        """
        pv_name = cls.__map_io_to_pv.get(event.ioname)
        if pv_name is not None:
            record = cls.__liste_pv.get(pv_name)
            if record:
                record.set(event.iovalue)
                logger.debug("IO %s → PV %s = %s", event.ioname, pv_name, event.iovalue)
            else:
                logger.error("PV '%s' mapped from IO '%s' is not found in internal registry.", pv_name, event.ioname)
        else:
            logger.error("No PV is mapped to IO '%s' in '_io_value_change'.", event.ioname)

    @classmethod
    def _io_status_change(cls, event) -> None:
        """
        Callback triggered when the IO status word changes.

        Parameters
        ----------
        event : Event
            Event containing the IO status.
        """
        pv_name = cls.__map_io_to_pv.get(event.ioname)
        if pv_name is not None:
            record = cls.__liste_pv.get(pv_name)
            if record:
                record.set(cls._status_convert(event.iovalue))
            else:
                logger.error("PV '%s' mapped from IO '%s' is not found in internal registry (status).", pv_name, event.ioname)
        else:
            logger.error("No PV is mapped to IO '%s' in '_io_status_change'.", event.ioname)

    @staticmethod
    def _status_convert(value: int) -> int:
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

    @classmethod
    def _record_write(cls, value: float, pv_name: str) -> None:
        """
        Callback triggered when a value is written from EPICS to RevPi hardware.

        Parameters
        ----------
        value : float
            New value to write to the IO.
        pv_name : str
            Name of the originating PV.
        """
        try:
            pv_name = pv_name.split(':')[-1]
            io_name = cls.__map_pv_to_io.get(pv_name)
            if io_name is None:
                raise KeyError(f"PV '{pv_name}' is not associated with any IO.")
            io_point = cls.__liste_io[io_name]
            io_point.value = round(value)
            logger.debug("PV %s → IO %s = %d", pv_name, io_name, round(value))
        except Exception as exc:
            logger.error("Failed to write using PV %s: %s", pv_name, exc)

    @classmethod
    def get_revpi(cls) -> (revpimodio2.RevPiModIO | None):
        """
        Returns the active RevPiModIO instance.

        Returns
        -------
        RevPiModIO | None
            The RevPi communication object or None if not Initialized
        """
        if isinstance(cls.__revpi, revpimodio2.RevPiModIO):
            return cls.__revpi
        else:
            return None

    @classmethod
    def get_io_name(cls, pv_name: str) -> (str | None):
        """
        Returns the IO name associated with a given PV.

        Parameters
        ----------
        pv_name : str
            Name of the EPICS process variable.

        Returns
        -------
        str | None
            Name of corresponding IO or None if there is no correspondence
        """
        return cls.__map_pv_to_io.get(pv_name)

    @classmethod
    def get_io_point(cls, io_name: str) -> (IntIO | None):
        """
        Returns the IO object associated with an IO name.

        Parameters
        ----------
        io_name : str
            Name of the IO.

        Returns
        -------
        IntIO | None
            The RevPi IO object or None if there is no correspondence
        """
        return cls.__liste_io.get(io_name)

    @classmethod
    def get_pv_name(cls, io_name: str) -> (str | None):
        """
        Returns the EPICS PV name associated with a given IO.

        Parameters
        ----------
        io_name : str
            Name of the IO.

        Returns
        -------
        str | None
            Associated PV name or None if there is no correspondence
        """
        return cls.__map_io_to_pv.get(io_name)

    @classmethod
    def get_pv_record(cls, pv_name: str) -> (RecordWrapper | None):
        """
        Returns the PythonDevice object corresponding to a given PV.

        Parameters
        ----------
        pv_name : str
            Name of the EPICS process variable.

        Returns
        -------
        PythonDevice | None
            The corresponding PythonDevice object or None if there is no correspondence
        """
        return cls.__liste_pv.get(pv_name)
    
    @classmethod
    def get_io_offset_value(cls, offset: int) -> (int | None):
        """
        """
        if cls.__revpi and cls.__revpi.io:
            io = cast(list, cls.__revpi.io[offset])
            io_point = cast(IntIO,io[0])
            value = io_point.value
            return value
        else:
            logger.error("Unable to access RevPi IOs when reading offset value %d.", offset)
            return None

    @classmethod
    @_requires_initialization
    def start(cls, blocking: bool = True) -> None:
        """
        
        """
        if cls.__revpi is not None:
            cls.__revpi.autorefresh_all()
            cls.__revpi.handlesignalend(cls.cleanup)
            builder.LoadDatabase()
            softioc.iocInit()
            if blocking:
                cls.__revpi.handlesignalend(softioc.safeEpicsExit)
                cls.__revpi.mainloop()
            else:
                cls.__revpi.mainloop(blocking=False)
                softioc.interactive_ioc(globals())
                cls.__revpi.exit()

        else:
            logger.error("Cannot start RevPi loop: RevPi instance is not initialized.")
    
    @classmethod
    def exit(cls) -> None:
        """
        """
        softioc.safeEpicsExit(0)
        if cls.__revpi is not None:
            if cls.__cleanup:
                cls.cleanup()
            cls.__revpi.exit()
    
    @classmethod
    @_requires_initialization
    def cycleloop(cls, func, cycletime: bool=False) -> None:
        """
        """
        if cls.__revpi is not None:
            if cycletime == False:
                cls.__revpi.cycleloop(func, blocking=False)
            else:
                cls.__revpi.cycleloop(func, cycletime=cycletime, blocking=False)
        else:
            logger.error("Cannot start RevPi loop: RevPi instance is not initialized.")
    
    @classmethod
    def SetDeviceName(cls, name: str) -> None:
        """
        Set the record prefix
        """
        builder.SetDeviceName(name)

    @classmethod
    def cleanup(cls) -> None:
        """
        Resets all registered analog outputs to their default values
        when the program exits (registered via atexit).
        """
        for io_point in cls.__liste_io.values():
            if getattr(io_point, "type", None) == 301:
                io_point.value = io_point.get_intdefaultvalue()
        logger.debug("Cleanup complete.")
    
    @classmethod
    def _register_builder(cls, product_type: int, builder_func: Callable) -> None:
        """
        Stores a construction function for a given module type.

        Parameters
        ----------
        product_type : ProductType
            Type of product (ProductType.AIO, ProductType.DIO, etc.).
        builder_func : Callable
            Function that takes the arguments (io_point, pv_name, DRVL, DRVH, **fields)
            and returns a PythonDevice object.
        """
        if not isinstance(product_type, int):
            raise TypeError("product_type must be an int (from revpimodio2.pictory.ProductType)")
        if not callable(builder_func):
            raise TypeError("builder_func must be callable")

        cls.__builder_registry[product_type] = builder_func