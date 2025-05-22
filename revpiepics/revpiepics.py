import atexit
import logging
import functools
from typing import Dict, Callable, Optional
from dataclasses import dataclass, field

import revpimodio2
from revpimodio2.io import IntIO

from softioc import softioc, builder, pythonSoftIoc
from epicsdbbuilder import recordnames

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class IOMap:
    io_name: str
    pv_name: str
    io_point: IntIO
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

    __dictmap = DicIOMap()
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

        if cls.__dictmap.get_by_io_name(io_name):
            mapping = cls.__dictmap.get_by_io_name(io_name)
            logger.error("The IO '%s' is already linked to PV '%s'.", io_name, mapping.record.name) # type: ignore
            return None

        if pv_name and cls.__dictmap.get_by_pv_name(pv_name):
            mapping = cls.__dictmap.get_by_pv_name(pv_name)
            logger.error("The PV name '%s' is already linked to IO '%s'.", mapping.record.name, mapping.io_name) # type: ignore
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
            mapping = IOMap(io_name, pv_name, io_point, record)
            cls.__dictmap.add(mapping)

        return record

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
    def get_io_name(cls, io_name: str) -> (IOMap | None):
        """
        """
        return cls.__dictmap.get_by_pv_name(io_name)

    @classmethod
    def get_pv_name(cls, pv_name: str) -> (IOMap | None):
        """
        """
        return cls.__dictmap.get_by_pv_name(pv_name)

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
            cls.__revpi.cycleloop(func, cycletime=cycletime, blocking=False) # type: ignore
        else:
            cls.__revpi.cycleloop(func, blocking=False) # type: ignore

    @classmethod
    def cleanup(cls) -> None:
        """
        Resets all analog outputs to their default value.

        This method is typically called at exit if cleanup is enabled.
        """
        for mapping in cls.__dictmap.map_io.values():
            if getattr(mapping.io_point, "type", None) == 301:
                mapping.io_point.value = mapping.io_point.get_intdefaultvalue()
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