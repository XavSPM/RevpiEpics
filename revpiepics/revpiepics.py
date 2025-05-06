import revpimodio2
from revpimodio2.pictory import ProductType
import atexit
import logging
from typing import Optional, Dict, Tuple

# Global registry to associate product types with their builder functions
builder_registry = {}

logger = logging.getLogger(__name__)

class RevPiEpics:
    """
    Main class to interface Revolution Pi with EPICS.
    It manages IOs, creates PVs, and synchronizes changes.

    Attributes:
        _revpi (RevPiModIO): RevPiModIO instance to access IOs.
        _liste_pv (dict[str, tuple]): Maps IO names to (record, io_point) pairs.
        _debug (bool): Enables debug logging.

    Public Methods:
        builder(io_name, pv_name, DRVL=None, DRVH=None, **fields): Creates an EPICS PV for a given IO.
        start(): Starts the main RevPi event loop.
        cleanup(): Resets analog outputs to default values.

    Internal Methods:
        _io_change(record, iovalue, ioname): Handles IO → EPICS updates.
        _record_write(value, io_point, pv_name): Handles EPICS → IO writes.
        _status_convert(n): Converts an integer to its bit length (used for status decoding).
    """

    def __init__(self, debug: bool = False, cycletime: int = 200) -> None:
        """
        Initializes the RevPiEpics instance.

        Args:
            debug (bool): Enable debug messages.
            cycletime (int): Refresh cycle time in milliseconds.
        """
        self._revpi = revpimodio2.RevPiModIO(autorefresh=True, debug = debug)
        self._revpi.cycletime = cycletime
        self._liste_pv: Dict[str, Tuple] = {}  # Stores registered PVs: {io_name: (record, io_point)}

        # Ensure cleanup runs on program exit
        atexit.register(self.cleanup)

       # Configure the global logging system only once
        if debug:
            logging.basicConfig(
                level=logging.DEBUG,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                )
        else:
            logging.basicConfig(
                level=logging.INFO,
                format="[%(levelname)s]: %(message)s",
                )

        if self._revpi._debug:
            logger.info("Debug mode enabled.")

    def builder(self, io_name: str, pv_name: str=None, DRVL=None, DRVH=None, **fields):
        """
        Creates an EPICS PV record linked to a Revolution Pi IO.

        Args:
            io_name (str): Name of the IO in RevPiModIO.
            pv_name (str) (optional): Name of the EPICS process variable (PV).
            DRVL (optional): Lower display limit.
            DRVH (optional): Upper display limit.
            **fields: Additional EPICS fields.

        Returns:
            record object or None if no matching builder.
        """
        if not hasattr(self._revpi.io, io_name):
            logger.error(f"IO name '{io_name}' not found in RevPi IOs.")
            return None
        io_point = getattr(self._revpi.io, io_name)
        product_type = io_point._parentdevice._producttype

        builder_func = builder_registry.get(product_type)
        if not builder_func:
            logger.warning(f"No builder found for {product_type}")
            return None
        
        if pv_name == None:
            pv_name = io_name
        
        record = builder_func(self, io_point, pv_name, DRVL, DRVH, **fields)
        if record:
            self._liste_pv[io_point.name] = (record, io_point)
        return record

    def _io_change(self, record, iovalue, ioname: str):
        """
        Updates an EPICS record when its linked IO value changes.

        Args:
            record: EPICS record object.
            iovalue: New IO value (int, float, or bool depending on IO type).
            ioname (str): Name of the IO point.
        """
        record.set(iovalue)
        if self._revpi._debug:
            logging.debug(f"Change detected on {ioname} → {record.name} = {iovalue}")

    def _record_write(self, value, io_point, pv_name: str):
        """
        Writes a value from an EPICS record back to the physical IO.

        Args:
            value: Value to write (int or float).
            io_point: The RevPiModIO IO point object.
            pv_name (str): The EPICS PV name.
        """
        try:
            io_point.value = int(value)
            if self._revpi._debug:
                logger.debug(f"Write to {pv_name} → {io_point.name} = {int(value)}")
        except Exception as e:
            logger.error(f"Failed to write to {pv_name}: {e}")
    
    @staticmethod
    def _status_convert(n: int) -> int:
        """
        Converts an integer to its bit length (useful for status decoding).

        Args:
            n (int): Input integer.

        Returns:
            int: Number of significant bits.
        """
        return int(n).bit_length()

    def start(self):
        """
        Starts the RevPiModIO main loop (non-blocking).
        Automatically refreshes all IOs and listens for changes.
        """
        if self._revpi._debug:
            logger.debug("Starting RevPi main")
        self._revpi.autorefresh_all()
        self._revpi.mainloop(blocking=False)

    def cleanup(self):
        """
        Resets all registered analog output IOs to their default values.
        Called automatically on program exit.
        """
        if self._liste_pv:
            for key, data in self._liste_pv.items():
                record, io = data
                if io.type == 301:  # Type 301 → analog output
                    io.value = io.get_intdefaultvalue()
        if self._revpi._debug:
            logger.debug("Cleanup done.")