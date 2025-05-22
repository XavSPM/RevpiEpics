import atexit
import logging
import functools
from typing import Dict, Callable, Optional, cast

import revpimodio2
from revpimodio2.io import IntIO

from softioc import softioc, builder, pythonSoftIoc
from epicsdbbuilder import recordnames

from .utils import status_bit_length

logger = logging.getLogger(__name__)

class RevPiEpics:
    """
    Bridge between a Revolution Pi and EPICS.

    The class exposes RevPi I/O points as EPICS process variables (PVs),
    and keeps both systems synchronized.
    """

    __map_io_to_pv: Dict[str, str] = {}
    __map_pv_to_io: Dict[str, str] = {}
    __liste_pv: Dict[str, pythonSoftIoc.RecordWrapper] = {}
    __liste_io: Dict[str, IntIO] = {}
    __revpi: revpimodio2.RevPiModIO | None = None
    __builder_registry: Dict[int, Callable] = {}
    __cleanup = False
    __initialize = False
    __auto_prefix = False

    @staticmethod
    def _requires_initialization(func):
        """
        Decorator to ensure the class has been initialized before executing a method.

        Raises
        ------
        RuntimeError
            If the class has not been initialized via `init()`.
        """
        @functools.wraps(func)
        def wrapper(cls, *args, **kwargs):
            if not cls.__initialize:
                raise RuntimeError("RevPiEpics must be initialized before calling this.")
            return func(cls, *args, **kwargs)
        return wrapper

    @classmethod
    def init(cls, cycletime: int = 200, debug: bool = False, cleanup: bool = True, auto_prefix: bool = False) -> None:
        """
        Initializes the RevPi connection with given parameters.

        Parameters
        ----------
        cycletime : int, optional
            Cycle time in milliseconds (default is 200).
        debug : bool, optional
            Enable debug logging (default is False).
        cleanup : bool, optional
            Reset outputs on exit if True (default is True).
        auto_prefix : bool, optional
            Automatically prefix PV names with core/device names (default is False).
        """
        cls.__revpi = revpimodio2.RevPiModIO(autorefresh=True, debug=debug)
        cls.__revpi.cycletime = cycletime
        cls.__cleanup = cleanup
        cls.__initialize = True
        cls.__auto_prefix = auto_prefix

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
    ) -> (pythonSoftIoc.RecordWrapper | None):
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
        RecordWrapper or None
            The created EPICS PV record or None if creation failed.
        """

        if not hasattr(cls.__revpi.io, io_name): # type: ignore
            logger.error("IO name %s not found in RevPi IOs.", io_name)
            return None

        if io_name in cls.__liste_io:
            logger.error("The IO '%s' is already bound to a PV.", io_name)
            return None

        if pv_name and pv_name in cls.__liste_pv:
            logger.error("The PV name '%s' is already in use.", pv_name)
            return None

        io_point = getattr(cls.__revpi.io, io_name) # type: ignore
        product_type = io_point._parentdevice._producttype
        builder_func = cls.__builder_registry.get(product_type)

        if builder_func is None:
            logger.warning("No builder registered for product type %s.", product_type)
            return None

        if pv_name is None:
            pv_name = io_name
        
        if cls.__auto_prefix: 
            record_name : recordnames.SimpleRecordNames = builder.GetRecordNames()  # type: ignore
            default_prefix = record_name.prefix
            record_name.prefix = []
            if cls.__revpi.core and cls.__revpi.core.name: # type: ignore
                record_name.PushPrefix(cls.__revpi.core.name) # type: ignore
            if io_point._parentdevice and io_point._parentdevice.name:
                record_name.PushPrefix(io_point._parentdevice.name)
            record = builder_func(io_point=io_point, pv_name=pv_name, DRVL=DRVL, DRVH=DRVH, **fields)
            record_name.prefix = default_prefix
        else:
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
        Callback for handling changes in IO values.

        Updates the corresponding EPICS PV when the RevPi IO changes.

        Parameters
        ----------
        event : object
            Event object containing `ioname` and `iovalue` attributes.
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
        Callback for changes in IO status values.

        Converts the status word and updates the associated PV accordingly.

        Parameters
        ----------
        event : object
            Event with `ioname` and `iovalue` attributes.
        """
        pv_name = cls.__map_io_to_pv.get(event.ioname)
        if pv_name is not None:
            record = cls.__liste_pv.get(pv_name)
            if record:
                record.set(status_bit_length(event.iovalue))
            else:
                logger.error("PV '%s' mapped from IO '%s' is not found in internal registry (status).", pv_name, event.ioname)
        else:
            logger.error("No PV is mapped to IO '%s' in '_io_status_change'.", event.ioname)

    @classmethod
    def _record_write(cls, value: float, pv_name: str) -> None:
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
            io_name = cls.__map_pv_to_io.get(pv_name)
            if io_name is None:
                raise KeyError(f"PV '{pv_name}' is not associated with any IO.")
            io_point = cls.__liste_io[io_name]
            io_point.value = round(value)
            logger.debug("PV %s → IO %s = %d", pv_name, io_name, round(value))
        except Exception as exc:
            logger.error("Failed to write using PV %s: %s", pv_name, exc)

    @classmethod
    @_requires_initialization
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
        Retrieves the IO name mapped to a PV name.

        Parameters
        ----------
        pv_name : str
            The name of the EPICS PV.

        Returns
        -------
        str or None
            The associated IO name or None.
        """
        return cls.__map_pv_to_io.get(pv_name)

    @classmethod
    def get_io_point(cls, io_name: str) -> (IntIO | None):
        """
        Retrieves the RevPi IO object for a given IO name.

        Parameters
        ----------
        io_name : str
            The name of the IO.

        Returns
        -------
        IntIO or None
            The IO object or None if not found.
        """
        return cls.__liste_io.get(io_name)

    @classmethod
    def get_pv_name(cls, io_name: str) -> (str | None):
        """
        Retrieves the PV name mapped to a given IO name.

        Parameters
        ----------
        io_name : str
            The name of the IO.

        Returns
        -------
        str or None
            The associated PV name or None.
        """
        return cls.__map_io_to_pv.get(io_name)

    @classmethod
    def get_pv_record(cls, pv_name: str) -> (pythonSoftIoc.RecordWrapper | None):
        """
        Retrieves the EPICS record (PV) object for a given PV name.

        Parameters
        ----------
        pv_name : str
            The name of the PV.

        Returns
        -------
        RecordWrapper or None
            The record object or None.
        """
        return cls.__liste_pv.get(pv_name)
    
    @classmethod
    @_requires_initialization
    def get_io_offset_value(cls, offset: int) -> (int | None):
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
            io = cast(list, cls.__revpi.io[offset]) # type: ignore
            io_point = cast(IntIO,io[0])
            value = io_point.value
            return value
        except IndexError:
            logger.error("Unable to access RevPi IOs when reading offset value %d.", offset)
            return None

    @classmethod
    @_requires_initialization
    def start(cls, interactive: bool = False) -> None:
        """
        Starts the EPICS IOC and the RevPi main loop.

        Depending on the `interactive` flag, the method will
        either start a interactive IOC or a background one.

        Parameters
        ----------
        interactive : bool, optional
        Whether to run the IOC in interactive mode (default is False).
        """
        cls.__revpi.autorefresh_all() # type: ignore
        builder.LoadDatabase()
        softioc.iocInit()
        if interactive:
            cls.__revpi.mainloop(blocking=False) # type: ignore
            atexit.register(cls.stop)
            softioc.interactive_ioc(globals())
        else:
            cls.__revpi.mainloop(blocking=False) # type: ignore
            atexit.register(cls.stop)
            softioc.non_interactive_ioc()
    
    @classmethod
    @_requires_initialization
    def stop(cls) -> None:
        """
        Stops the RevPi main loop and optionally resets outputs.

        If `cleanup` was enabled during initialization, this method
        will reset all analog outputs to their default values.
        """
        if cls.__cleanup:
            cls.cleanup()
        cls.__revpi.exit() # type: ignore
        logger.debug("RevPi main loop stopped.")

    @classmethod
    @_requires_initialization
    def cycleloop(cls, func, cycletime: int=False) -> None:
        """
        Starts a custom function inside the RevPi cyclic loop.

        This allows custom logic to be executed at each cycle.
        The loop runs non-blocking in a background thread.

        Parameters
        ----------
        func : callable
            A function to be executed every cycle.
        cycletime : int, optional
            Optional custom cycle time in milliseconds.
            If False, the default cycle time is used.
        """

        if cycletime:
            cls.__revpi.cycleloop(func, cycletime=cycletimeblocking=False) # type: ignore
        else:
            cls.__revpi.cycleloop(func, blocking=False) # type: ignore


    @classmethod
    def cleanup(cls) -> None:
        """
        Resets all analog outputs to their default value.

        This method is typically called at exit if cleanup is enabled.
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
            and returns a RecordWrapper object.
        """
        if not isinstance(product_type, int):
            raise TypeError("product_type must be an int (from revpimodio2.pictory.ProductType)")
        if not callable(builder_func):
            raise TypeError("builder_func must be callable")

        cls.__builder_registry[product_type] = builder_func