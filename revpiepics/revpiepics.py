import atexit
import logging
import functools
from typing import Dict, Callable, Optional
from dataclasses import dataclass, field

import revpimodio2

from softioc import softioc, builder, pythonSoftIoc
from softioc.asyncio_dispatcher import AsyncioDispatcher
from epicsdbbuilder import recordnames

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class IOMap:
    io_name: str
    pv_name: str
    io_point: revpimodio2.io.IntIO
    record: pythonSoftIoc.RecordWrapper

@dataclass
class DicIOMap:
    map_io: dict[str, IOMap] = field(default_factory=dict)
    map_pv: dict[str, IOMap] = field(default_factory=dict)

    def add(self, mapping: IOMap) -> None:
        self.map_io[mapping.io_name] = mapping
        self.map_pv[mapping.pv_name] = mapping

    def get_by_io_name(self, io_name: str) -> Optional[IOMap]:
        return self.map_io.get(io_name)

    def get_by_pv_name(self, pv_name: str) -> Optional[IOMap]:
        return self.map_pv.get(pv_name)

class RevPiEpics:
    """
    Bridge between a Revolution Pi and EPICS.

    The class exposes RevPi I/O points as EPICS process variables (PVs),
    and keeps both systems synchronized.
    """

    _dictmap = DicIOMap()
    _revpi: revpimodio2.RevPiModIO | None = None
    _builder_registry: Dict[int, Callable] = {}
    _cleanup = False
    _initialize = False
    _auto_prefix = False

    @staticmethod
    def _requires_initialization(func):
        """
        Decorator to ensure the class has been initialized before executing a method.

        If the class has not been initialized, the call is ignored and a warning is logged.
        """
        @functools.wraps(func)
        def wrapper(cls, *args, **kwargs):
            if not cls._initialize:
                logger.warning("Call to '%s' ignored: RevPiEpics is not initialized.", func.__name__)
                return  # Do nothing
            return func(cls, *args, **kwargs)
        return wrapper

    @classmethod
    def init(cls, 
             cycletime: Optional[int] = None, 
             debug: bool = False, 
             cleanup: bool = True, 
             auto_prefix: bool = False) -> None:
        """
        Initializes the RevPi connection with given parameters.

        Parameters
        ----------
        cycletime : int, optional
            Cycle time in milliseconds.
        debug : bool, optional
            Enable debug logging (default is False).
        cleanup : bool, optional
            Reset outputs on exit if True (default is True).
        auto_prefix : bool, optional
            Automatically prefix PV names with core/device names (default is False).
        """
        cls._revpi = revpimodio2.RevPiModIO(autorefresh=True, debug=debug)
        if cycletime is not None:
            cls._revpi.cycletime = cycletime
        cls._cleanup = cleanup
        cls._initialize = True
        cls._auto_prefix = auto_prefix

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
        **fields) -> Optional[pythonSoftIoc.RecordWrapper]:
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

        if not hasattr(cls._revpi.io, io_name): # type: ignore
            logger.error("IO name %s not found in RevPi IOs.", io_name)
            return None
        
        io_point = getattr(cls._revpi.io, io_name) # type: ignore

        mapping_io = cls._dictmap.get_by_io_name(io_name)
        if mapping_io:
            logger.error("The IO '%s' is already linked to PV '%s'.", io_name, mapping_io.record.name)
            return None

        if pv_name:
            mapping_pv = cls._dictmap.get_by_pv_name(pv_name)
            if mapping_pv:
                logger.error("The PV name '%s' is already linked to IO '%s'.", mapping_pv.record.name, mapping_pv.io_name)
                return None
        
        product_type = io_point._parentdevice._producttype
        builder_func = cls._builder_registry.get(product_type)

        if builder_func is None:
            logger.error("No builder registered for product type %s.", product_type)
            return None

        if pv_name is None:
            pv_name = io_name
        
        if cls._auto_prefix: 
            record_name : recordnames.SimpleRecordNames = builder.GetRecordNames()  # type: ignore
            default_prefix = record_name.prefix
            record_name.prefix = []
            if cls._revpi.core and cls._revpi.core.name: # type: ignore
                record_name.PushPrefix(cls._revpi.core.name) # type: ignore
            if io_point._parentdevice and io_point._parentdevice.name:
                record_name.PushPrefix(io_point._parentdevice.name)
            record = builder_func(io_point=io_point, pv_name=pv_name, DRVL=DRVL, DRVH=DRVH, **fields)
            record_name.prefix = default_prefix
        else:
            record = builder_func(io_point=io_point, pv_name=pv_name, DRVL=DRVL, DRVH=DRVH, **fields)
            
        if record:
            mapping = IOMap(io_name, pv_name, io_point, record)
            cls._dictmap.add(mapping)

        return record

    @classmethod
    @_requires_initialization
    def get_revpi(cls) -> Optional[revpimodio2.RevPiModIO]:
        """
        Returns the active RevPiModIO instance.

        Returns
        -------
        RevPiModIO | None
            The RevPi communication object or None if not Initialized
        """
        if isinstance(cls._revpi, revpimodio2.RevPiModIO):
            return cls._revpi
        else:
            return None

    @classmethod
    def get_io_name(cls, io_name: str) -> Optional[IOMap]:
        """
        Returns the IOMap associated with a given IO name.

        Parameters
        ----------
        io_name : str
            Name of the IO.

        Returns
        -------
        IOMap or None
            The associated IO mapping object, or None if not found.
        """
        return cls._dictmap.get_by_io_name(io_name)

    @classmethod
    def get_pv_name(cls, pv_name: str) -> Optional[IOMap]:
        """
        Returns the IOMap associated with a given PV name.

        Parameters
        ----------
        pv_name : str
            Name of the PV.

        Returns
        -------
        IOMap or None
            The associated IO mapping object, or None if not found.
        """
        return cls._dictmap.get_by_pv_name(pv_name)

    @classmethod
    @_requires_initialization
    def start(cls, interactive: bool = False, dispatcher: Optional[AsyncioDispatcher] = None) -> None:
        """
        Starts the EPICS IOC and the RevPi main loop.

        Depending on the `interactive` flag, the method will
        either start a interactive IOC or a background one.

        Parameters
        ----------
        interactive : bool, optional
            Whether to run the IOC in interactive mode (default is False).
        dispatcher : AsyncioDispatcher, optional
            use asyncio dispatcher.
        """
        cls._revpi.autorefresh_all() # type: ignore
        builder.LoadDatabase()
        if dispatcher:
            softioc.iocInit(dispatcher)
        else:
            softioc.iocInit()
        if interactive:
            cls._revpi.mainloop(blocking=False) # type: ignore
            atexit.register(cls.stop)
            softioc.interactive_ioc(globals())
        else:
            cls._revpi.mainloop(blocking=False) # type: ignore
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
        if cls._cleanup:
            cls.cleanup()
        cls._revpi.exit() # type: ignore
        logger.debug("RevPi main loop stopped.")

    @classmethod
    def cleanup(cls) -> None:
        """
        Resets all analog outputs (type 301) to their default value.

        This method is typically called at exit if cleanup is enabled.
        """
        for mapping in cls._dictmap.map_io.values():
            if getattr(mapping.io_point, "type", None) == 301:
                try:
                    mapping.io_point.value = mapping.io_point.get_intdefaultvalue()
                except Exception as e:
                    logger.warning("Failed to reset IO '%s': %s", mapping.io_name, e)
        logger.debug("Cleanup complete.")
    
    @classmethod
    def register_builder(cls, product_type: int, builder_func: Callable) -> None:
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

        cls._builder_registry[product_type] = builder_func