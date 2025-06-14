import logging
from .recod import RecordDirection, RecordType
from .utils import status_bit_length
from .iomap import IOMap
from threading import Event, Thread
from timeit import default_timer

logger = logging.getLogger(__name__)

class PVSyncThread(Thread):
    """
    Synchronization thread between RevPi and EPICS.
    
    This thread handles the continuous synchronization of I/O data between
    a Revolution Pi (RevPi) industrial controller and EPICS Process Variables (PVs).
    It runs in a loop at a specified cycle time, reading from RevPi I/O,
    synchronizing with EPICS records, and executing custom functions.
    """

    def __init__(self, bridge_cls):
        """
        Initialize the PV synchronization thread.
        
        Args:
            bridge_cls: Bridge class instance containing all necessary references
                       (RevPi instance, mappings, cycle time, custom functions, etc.)
        """
        super().__init__(daemon=True, name="PVSyncThread")
        # Store references to bridge class components
        self._bridge_cls = bridge_cls
        self._revpi = bridge_cls._revpi
        self._dictmap = bridge_cls._dictmap
        self._cycle_time_ms = bridge_cls._cycle_time_ms
        self._custom_functions = bridge_cls._custom_functions
        self._custom_functions_lock = bridge_cls._custom_functions_lock
        self._cleanup =  bridge_cls._cleanup
        # Event for graceful thread shutdown
        self._stop_event = Event()

    def run(self) -> None:
        """
        Main synchronization loop.
        
        Continuously synchronizes I/O data between RevPi and EPICS at the
        specified cycle time. Handles timing control and error recovery.
        """
        logger.info("Synchronization thread started (cycle: %s ms)", self._cycle_time_ms)
        cycle_time_s = self._cycle_time_ms / 1000.0  # Convert to seconds for timing

        # Main synchronization loop
        while not self._stop_event.is_set():
            cycle_start = default_timer()  # Record cycle start time

            try:
                # Execute one synchronization cycle
                self._sync_cycle()

            except Exception as e:
                # Critical error handling - stop the bridge on any exception
                logger.critical(
                    f"Error: {e}"
                    f"Stopping synchronization"
                )
                self._bridge_cls.stop()
                break

            # Cycle timing management
            cycle_time = default_timer() - cycle_start
            cycle_time_ms = cycle_time * 1000

            # Sleep for remaining cycle time or warn if cycle time exceeded
            if cycle_time < cycle_time_s:
                sleep_time = cycle_time_s - cycle_time
                self._stop_event.wait(timeout=sleep_time)
            else:
                logger.warning(f"Cycle time exceeded: {cycle_time_ms:.1f} ms > {self._cycle_time_ms} ms")
        
        # Perform cleanup if requested
        if self._cleanup:
            self._sync_cleanup()

        logger.debug("Synchronization thread stopped")

    def _sync_cycle(self) -> None:
        """
        Execute one synchronization cycle.
        
        Performs the complete synchronization sequence:
        1. Read RevPi process image (once for the entire cycle)
        2. Synchronize all I/O mappings (both input and output)
        3. Write RevPi process image
        4. Execute custom functions (using the same process image)
        5. Write RevPi process image again (for custom function changes)
        """

        # Read current state from RevPi I/O modules (single read for entire cycle)
        if not self._revpi.readprocimg():
            raise RuntimeError("Failed to read RevPi process image")

        # Get all configured I/O mappings
        mappings = self._dictmap.get_all_mappings()

        # Process each mapping according to its direction
        for mapping in mappings.values():
            try:
                if mapping.direction == RecordDirection.OUTPUT:
                    # Handle EPICS -> RevPi direction (control outputs)
                    self._sync_output(mapping)
                elif mapping.direction == RecordDirection.INPUT:
                    # Handle RevPi -> EPICS direction (read inputs)
                    self._sync_input(mapping)

            except Exception as e:
                # Log individual mapping errors but continue processing others
                logger.warning("Sync error %s: %s", mapping.io_name, e)

        # Write updated values to RevPi I/O modules after mapping sync
        if not self._revpi.writeprocimg():
            raise RuntimeError("Failed to write RevPi process image")

        # Execute any registered custom functions (reuses current process image)
        self._execute_custom_functions()

    def _sync_output(self, mapping: IOMap) -> None:
        """
        Synchronize an output mapping (PV -> RevPi).
        
        Handles bidirectional synchronization for output channels:
        - When EPICS PV is updated: PV value -> RevPi output
        - Otherwise: RevPi output -> PV (feedback for confirmation)
        
        Args:
            mapping: IOMap instance containing the mapping configuration
        """
        if mapping.update_record:
            # EPICS PV was updated - propagate to RevPi I/O
            pv_value = mapping.record.get()
            # Round float values to avoid precision issues
            pv_value = round(pv_value) if isinstance(pv_value, float) else pv_value

            # Only update if value has changed
            if pv_value != mapping.io_point.value:
                mapping.io_point.value = pv_value
                mapping.last_io_value = pv_value
                logger.debug("OUTPUT: PV %s → IO %s = %s",mapping.pv_name, mapping.io_name, pv_value)

            # Clear update flag
            mapping.update_record = False

        else:
            # Provide feedback - read actual I/O state back to PV
            io_value = mapping.io_point.value
            pv_value = mapping.record.get()
            pv_value = round(pv_value) if isinstance(pv_value, float) else pv_value

            # Update PV if I/O value differs (without processing to avoid loops)
            if pv_value != io_value:
                mapping.record.set(io_value, process=False)
                mapping.last_pv_value = io_value
                logger.debug("OUTPUT: IO %s → PV %s = %s",mapping.io_name, mapping.pv_name, pv_value)

    def _sync_input(self, mapping: IOMap) -> None:
        """
        Synchronize an input mapping (RevPi -> PV).
        
        Reads RevPi input values and updates corresponding EPICS PVs.
        Handles different record types (analog, status, binary) appropriately.
        
        Args:
            mapping: IOMap instance containing the mapping configuration
        """
        io_value = mapping.io_point.value

        # Optimization: skip processing if value hasn't changed
        if io_value == mapping.last_io_value:
            return

        # Handle different EPICS record types
        if mapping.record_type == RecordType.ANALOG:
            # Direct analog value transfer
            if mapping.record.get() != io_value:
                mapping.record.set(io_value)
                logger.debug("INPUT: IO %s → PV %s = %s", mapping.io_name, mapping.pv_name, io_value)

        elif mapping.record_type == RecordType.STATUS:
            # Convert to status bit representation
            status_value = status_bit_length(io_value)
            if mapping.record.get() != status_value:
                mapping.record.set(status_value)
                logger.debug("STATUS: IO %s → PV %s = %s", mapping.io_name, mapping.pv_name, status_value)

        elif mapping.record_type == RecordType.BINARY:
            # Convert to boolean for binary records
            binary_value = bool(io_value)
            if mapping.record.get() != binary_value:
                mapping.record.set(binary_value)
                logger.debug("INPUT: IO %s → PV %s = %s", mapping.io_name, mapping.pv_name, binary_value)

        # Update last known value for optimization
        mapping.last_io_value = io_value
    
    def _sync_cleanup(self) -> None:
        """
        Cleanup synchronization - reset outputs to default values.
        
        Called during shutdown to ensure all RevPi outputs are returned
        to their safe default states before the thread terminates.
        """

        logger.debug(f"Reset outputs to initial state")
        # Read defaul values process image
        self._revpi.setdefaultvalues()
        # Write the reset values to RevPi I/O
        if not self._revpi.writeprocimg():
            logger.warning("Failed to write process image")


    def _execute_custom_functions(self) -> None:
        """
        Execute all registered custom functions.
        
        Custom functions are user-defined callbacks that run during each
        synchronization cycle. They operate on the current process image
        that was read at the beginning of the cycle, avoiding unnecessary
        I/O operations for better performance.
        
        Raises:
            RuntimeError: If any custom function fails
        """
        if not self._custom_functions:
            return

        # Custom functions use the process image already read in _sync_cycle()
        # No additional readprocimg() call needed - performance optimization

        # Get thread-safe copy of functions to execute
        with self._custom_functions_lock:
            functions_to_execute = self._custom_functions.items()

        # Execute each custom function
        for func_name, func in functions_to_execute:
            try:
                func()

            except Exception as e:
                # Re-raise with context about which function failed
                raise RuntimeError(f"Custom function '{func_name}' failed: {e}")

        # Write I/O image after all custom functions complete
        if not self._revpi.writeprocimg():
            raise RuntimeError("Failed to write RevPi process image after custom functions")

    def stop(self) -> None:
        """
        Stop the synchronization thread gracefully.
        
        Sets the stop event and waits for the thread to finish.
        Includes timeout handling in case the thread doesn't respond.
        """
        # Signal thread to stop
        self._stop_event.set()
        # Wait for thread completion with timeout
        self.join(timeout=self._cycle_time_ms*10)

        # Warn if thread didn't stop cleanly
        if self.is_alive():
            logger.warning("Synchronization thread could not be stopped cleanly")