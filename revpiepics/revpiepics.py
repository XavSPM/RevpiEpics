# -*- coding: utf-8 -*-
"""RevPi ⇔ EPICS bridge (SoftIOC-only, event-driven sync).

RevPi to EPICS bidirectional bridge with SoftIOC-only implementation and event-driven synchronization.
Controlled synchronization with explicit process image read/write via readprocimg() and writeprocimg().
Regular refresh at defined frequency.
"""
from __future__ import annotations

import atexit
import functools
import logging
from threading import Lock
from timeit import default_timer
from typing import Callable, Dict, Optional, cast

from .pvsync import PVSyncThread
from .iomap import DicIOMap, IOMap

import revpimodio2
from softioc import builder, pythonSoftIoc, softioc
from softioc.asyncio_dispatcher import AsyncioDispatcher
from epicsdbbuilder.recordnames import SimpleRecordNames

logger = logging.getLogger(__name__)

class RevPiEpics:
    """Bridge between RevPi and EPICS with bidirectional synchronization.
    
    This class provides a bridge between Revolution Pi (RevPi) hardware and EPICS 
    control system, enabling bidirectional communication and synchronization of 
    process variables.
    """
    # Internal mapping dictionary for I/O mappings
    _dictmap = DicIOMap()
    # RevPi ModIO instance for hardware communication
    _revpi: Optional[revpimodio2.RevPiModIO] = None
    # Registry of builder functions for different product types
    _builder_registry: Dict[int, Callable] = {}
    # Initialization state flag
    _initialized = False
    # Cleanup flag for automatic resource cleanup
    _cleanup = True
    # Auto-prefix flag for PV naming
    _auto_prefix = False
    # Cycle time in milliseconds
    _cycle_time_ms = None
    # PV synchronization thread
    _pv_sync: Optional["PVSyncThread"] = None
    # Thread synchronization lock
    _lock = Lock()
    # Custom user functions to execute in sync cycle
    _custom_functions: Dict[str, Callable] = {}
    # Lock for custom functions access
    _custom_functions_lock = Lock()

    @staticmethod
    def _requires_init(func):
        """Decorator to check initialization before method execution."""

        @functools.wraps(func)
        def wrapper(cls, *args, **kwargs):
            if not cls._initialized:
                raise RevPiEpicsInitError(
                    "RevPiEpics not initialized. Call init() first."
                )
            return func(cls, *args, **kwargs)

        return wrapper

    @classmethod
    def init(
            cls,
            *,
            cycletime_ms: Optional[int] = 200,
            debug: bool = False,
            cleanup: bool = True,
            auto_prefix: bool = False
    ) -> None:
        """Initialize the RevPi-EPICS bridge.

        Sets up the connection to RevPi hardware and configures the bridge parameters.
        Must be called before using any other methods.

        Args:
            cycletime_ms: Cycle time in milliseconds (minimum 20ms)
            debug: Enable debug mode with verbose logging
            cleanup: Enable automatic cleanup on exit
            auto_prefix: Enable automatic PV prefixing based on device hierarchy
            
        Raises:
            RevPiEpicsInitError: If initialization fails
            ValueError: If cycletime_ms is less than 20ms
        """
        with cls._lock:
            if cls._initialized:
                logger.warning("RevPiEpics already initialized")
                return

            try:
                # Initialize RevPi ModIO without auto-refresh (we handle sync manually)
                cls._revpi = revpimodio2.RevPiModIO(autorefresh=False, debug=debug)

                # Validate and set cycle time
                if cycletime_ms is not None:
                    if cycletime_ms < 20:
                        raise ValueError(f"Minimum cycle time: 20 ms")
                    cls._cycle_time_ms = cycletime_ms

                cls._cleanup = cleanup
                cls._auto_prefix = auto_prefix

                # Configure logging based on debug mode
                log_level = logging.DEBUG if debug else logging.INFO
                log_format = (
                    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                    if debug else "[%(levelname)s]: %(message)s"
                )
                logging.basicConfig(level=log_level, format=log_format)

                # Initialize PV synchronization thread
                cls._pv_sync = PVSyncThread(cls)
                cls._initialized = True

                logger.debug(f"RevPiEpics initialized")

            except Exception as e:
                logger.error(f"Initialization error: {e}")
                raise RevPiEpicsInitError(f"Initialization failed: {e}") from e

    @classmethod
    @_requires_init
    def builder(
            cls,
            io_name: str,
            pv_name: Optional[str] = None,
            DRVL: Optional[float] = None,
            DRVH: Optional[float] = None,
            **fields,
    ) -> Optional[pythonSoftIoc.RecordWrapper]:
        """Create an EPICS PV linked to a RevPi I/O point.

        This method creates a bidirectional mapping between a RevPi I/O point and an EPICS PV.
        The appropriate builder function is selected based on the RevPi device product type.

        Args:
            io_name: Name of the RevPi I/O point (must exist in RevPi configuration)
            pv_name: Name of the EPICS PV (defaults to io_name if not specified)
            DRVL: Drive low limit for the PV (optional)
            DRVH: Drive high limit for the PV (optional)
            **fields: Additional EPICS record fields

        Returns:
            RecordWrapper instance if successful, None if creation failed
            
        Raises:
            RevPiEpicsBuilderError: If I/O name not found, already mapped, or no builder available
        """
        try:
            # Verify RevPi instance is available
            if not cls._revpi:
                cls._initialized = False
                raise RevPiEpicsBuilderError(f"Initialization error")
            
            # Check if I/O point exists in RevPi configuration
            if not hasattr(cls._revpi.io, io_name):
                raise RevPiEpicsBuilderError(f"I/O '{io_name}' not found")

            # Check if I/O is already mapped
            if cls._dictmap.get_by_io_name(io_name):
                raise RevPiEpicsBuilderError(f"I/O '{io_name}' already mapped")

            # Check if PV name already exists
            if pv_name and cls._dictmap.get_by_pv_name(pv_name):
                raise RevPiEpicsBuilderError(f"PV '{pv_name}' already exists")

            # Get I/O point and its parent device information
            io_point = getattr(cls._revpi.io, io_name)
            product_type = io_point._parentdevice._producttype

            # Select appropriate builder function based on product type
            build_func = cls._builder_registry.get(product_type)
            if build_func is None:
                raise RevPiEpicsBuilderError(
                    f"No builder for product type {product_type}"
                )

            # Use I/O name as PV name if not specified
            if pv_name is None:
                pv_name = io_name

            # Build with or without automatic prefixing
            if cls._auto_prefix:
                mapping = cls._build_with_prefix(
                    build_func=build_func, 
                    io_name=io_name, 
                    io_point=io_point, 
                    pv_name=pv_name, 
                    DRVL=DRVL, 
                    DRVH=DRVH, 
                    **fields
                )
            else:
                mapping = build_func(
                    io_name=io_name,
                    io_point=io_point,
                    pv_name=pv_name,
                    DRVL=DRVL,
                    DRVH=DRVH, 
                    **fields
                )

            # Add mapping to dictionary and return record wrapper
            if mapping:
                cls._dictmap.add(mapping)
                logger.debug(f"PV '{pv_name}' created for I/O '{io_name}'")
                return mapping.get_record()
            else:
                return None

        except Exception as e:
            logger.error(f"PV creation error: {e}")
            return None

    @classmethod
    def _build_with_prefix(cls, build_func, io_name ,io_point, pv_name, DRVL, DRVH, **fields):
        """Build a PV with automatic prefix based on device hierarchy.
        
        Constructs PV names with automatic prefixes derived from RevPi core and device names.
        """
        rec_names = cast(SimpleRecordNames, builder.GetRecordNames())
        saved_prefix = rec_names.prefix.copy()

        try:
            # Add core name as prefix if available
            if cls._revpi:
                if cls._revpi.core and cls._revpi.core.name:
                    rec_names.PushPrefix(cls._revpi.core.name)
                # Add parent device name as additional prefix if available
                if io_point._parentdevice and io_point._parentdevice.name:
                    rec_names.PushPrefix(io_point._parentdevice.name)

            return build_func(
                io_name=io_name,
                io_point=io_point, pv_name=pv_name,
                DRVL=DRVL, DRVH=DRVH, **fields
            )
        finally:
            # Always restore original prefix
            rec_names.prefix = saved_prefix

    @classmethod
    @_requires_init
    def start(
            cls,
            interactive: bool = False,
            dispatcher: Optional[AsyncioDispatcher] = None
    ) -> None:
        """Start the RevPi-EPICS bridge.

        Loads the EPICS database, initializes the IOC, and starts the synchronization thread.
        This method blocks until the IOC is stopped.

        Args:
            interactive: Run in interactive mode (allows command line interaction)
            dispatcher: Optional asyncio dispatcher for advanced async operations
            
        Raises:
            RuntimeError: If synchronization thread fails to initialize
        """
        try:
            # Load EPICS database with all created PVs
            builder.LoadDatabase()

            # Ensure automatic cleanup on program exit
            atexit.register(cls.stop)

            # Initialize EPICS IOC with optional dispatcher
            if dispatcher:
                softioc.iocInit(dispatcher)
            else:
                softioc.iocInit()

            # Start PV synchronization thread
            if cls._pv_sync:
                cls._pv_sync.start()
                logger.debug("RevPi-EPICS bridge started")
            else:
                raise RuntimeError(f"Synchronization thread error")

            # Run IOC in interactive or non-interactive mode
            if interactive:
                softioc.interactive_ioc(globals())
            else:
                softioc.non_interactive_ioc()

        except Exception as e:
            logger.error(f"Startup error: {e}")
            raise

        finally:
            # Always attempt cleanup on exit
            cls.stop()

    @classmethod
    @_requires_init
    def stop(cls) -> None:
        """Stop the RevPi-EPICS bridge and cleanup resources.
        
        Stops the synchronization thread, closes RevPi connection, and resets initialization state.
        """
        logger.debug("Stopping RevPi-EPICS bridge...")

        # Stop synchronization thread
        if cls._pv_sync:
            cls._pv_sync.stop()

        # Close RevPi connection
        if cls._revpi:
            cls._revpi.exit()
            
        # Reset initialization state
        with cls._lock:
            cls._initialized = False


    @classmethod
    def register_builder(cls, product_type: int, func: Callable) -> None:
        """Register a builder function for a specific RevPi product type.

        Builder functions are responsible for creating appropriate EPICS PVs for different 
        types of RevPi modules (e.g., digital I/O, analog I/O, etc.).

        Args:
            product_type: RevPi product type identifier (integer)
            func: Builder function that creates PV mappings
            
        Raises:
            TypeError: If product_type is not an integer or func is not callable
        """
        if not isinstance(product_type, int):
            raise TypeError("product_type must be an integer")
        if not callable(func):
            raise TypeError("func must be callable")

        cls._builder_registry[product_type] = func
        logger.debug(f"Builder registered for type {product_type}")

    @classmethod
    def get_mappings(cls) -> Dict[str, IOMap]:
        """Return all current I/O to PV mappings.
        
        Returns:
            Dictionary of all active mappings keyed by I/O name
        """
        return cls._dictmap.get_all_mappings()

    @classmethod
    def remove_mapping(cls, io_name: str) -> bool:
        """Remove an I/O to PV mapping.
        
        Args:
            io_name: Name of the I/O point to remove from mapping
            
        Returns:
            True if mapping was removed, False if not found
        """
        return cls._dictmap.remove(io_name)

    @classmethod
    def add_loop_task(cls, func: Callable) -> None:
        """Add a custom function to execute in the synchronization cycle.

        Custom functions are executed during each synchronization cycle, allowing users 
        to implement custom logic that runs alongside the standard I/O synchronization.

        Args:
            func: Function to execute (must be callable with a unique __name__)
            
        Raises:
            TypeError: If func is not callable
            ValueError: If function name is None or already exists
        """
        if not callable(func):
            raise TypeError("func must be callable")

        with cls._custom_functions_lock:
            func_name = getattr(func, '__name__', None)
            if func_name is None:
                raise ValueError(f"Function error")

            elif func_name in cls._custom_functions:
                raise ValueError(f"Function {func_name} already exists")

            # Store function for execution in sync cycle
            cls._custom_functions[func_name] = func

        logger.debug(f"Custom function added to synchronization cycle")
    
    @classmethod
    def remove_loop_task(cls, func: Callable) -> bool:
        """Remove a loop task from the synchronization cycle.

        Args:
        func: Function to remove from the loop cycle

        Returns:
            True if the task was found and removed, False if not found
        
        Raises:
            TypeError: If func is not callable
            ValueError: If function name cannot be determined
        """
        if not callable(func):
            raise TypeError("func must be callable")
    
        # Get function name for lookup
        func_name = getattr(func, '__name__', None)
        if func_name is None:
            raise ValueError("Function name cannot be determined")
    
        with cls._custom_functions_lock:
            # Check if function exists and is the same object
            if func_name in cls._custom_functions and cls._custom_functions[func_name] is func:
                # Remove the function from the dictionary
                removed_func = cls._custom_functions.pop(func_name)
                logger.debug(f"Loop task '{func_name}' removed from synchronization cycle")
                return True
            else:
                logger.warning(f"Loop task '{func_name}' not found in synchronization cycle")
                return False
    
    @classmethod
    def get_loop_tasks(cls) -> Dict[str, Callable]:
        """Get all registered loop tasks.

        Returns:
            Dictionary mapping function names to their callable objects.
            Returns a copy to prevent external modifications.
        """
        with cls._custom_functions_lock:
            # Return a copy to prevent external modifications
            return cls._custom_functions.copy()

    @classmethod
    def clear_loop_tasks(cls) -> int:
        """Remove all custom functions from the synchronization cycle.

        Returns:
            Number of functions that were removed
        """
        with cls._custom_functions_lock:
            count = len(cls._custom_functions)
            cls._custom_functions.clear()
            logger.debug(f"{count} custom function(s) removed")
            return count
    
    @classmethod
    def get_loop_task_names(cls) -> list[str]:
        """Get the names of all registered loop tasks.

        Returns:
            List of function names currently registered as loop tasks.
        """
        with cls._custom_functions_lock:
            return list(cls._custom_functions.keys())
    

    @classmethod
    def get_loop_task_count(cls) -> int:
        """Get the number of registered loop tasks.

        Returns:
            Number of loop tasks currently registered.
        """
        with cls._custom_functions_lock:
            return len(cls._custom_functions)
    

    @classmethod
    def get_dic_io_map(cls) -> DicIOMap:
        """Return the I/O mapping dictionary instance.
        
        Returns:
            DicIOMap instance containing all current mappings
        """
        return cls._dictmap

    @classmethod
    def get_mod_io(cls) -> Optional[revpimodio2.RevPiModIO]:
        """Return the RevPi ModIO instance.
        
        Returns:
            RevPiModIO instance if initialized, None otherwise
        """
        return cls._revpi
    

class RevPiEpicsError(Exception):
    """Base exception class for RevPi-EPICS bridge errors."""
    pass


class RevPiEpicsInitError(RevPiEpicsError):
    """Exception raised during bridge initialization failures."""
    pass


class RevPiEpicsBuilderError(RevPiEpicsError):
    """Exception raised during PV creation/building failures."""
    pass