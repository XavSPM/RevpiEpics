import atexit
import logging
from typing import Dict, Callable

import revpimodio2
from revpimodio2.io import IntIO
from revpimodio2.pictory import ProductType
from softioc.pythonSoftIoc import PythonDevice

# Registry that maps a ProductType to the builder function able to
# generate the appropriate EPICS record for that hardware.
builder_registry: Dict[ProductType, Callable] = {}

logger = logging.getLogger(__name__)


class RevPiEpics:
    
    """Bridge between a Revolution-Pi and EPICS.

    The class exposes RevPi IO points as EPICS process variables (PVs),
    keeps both sides synchronised.

    Attributes
    ----------
    __revpi : RevPiModIO | None
        The underlying *revpimodio2* connection.
    __map_io_to_pv : dict[str, str]
        Mapping *RevPi IO name → EPICS PV name*.
    __map_pv_to_io : dict[str, str]
        Mapping *EPICS PV name → RevPi IO name*.
    __liste_pv : dict[str, PythonDevice]
        Cache of all EPICS records.
    __liste_io : dict[str, IntIO]
        Cache of all IO objects.
    """

    __map_io_to_pv: Dict[str, str] = {}
    __map_pv_to_io: Dict[str, str] = {}
    __liste_pv: Dict[str, PythonDevice] = {}
    __liste_io: Dict[str, IntIO] = {}
    __revpi: revpimodio2.RevPiModIO | None = None

    # ------------------------------------------------------------------ #
    # Initialisation / shutdown                                          #
    # ------------------------------------------------------------------ #

    @classmethod
    def initialize(cls, *, cycletime: int = 200, debug: bool = False) -> None:
        """Open the connection to the Revolution-Pi.

        Parameters
        ----------
        cycletime :
            Refresh cycle time in **milliseconds** (default 200 ms).
        debug :
            If *True* the logger is put in *DEBUG* mode.
        """
        cls.__revpi = revpimodio2.RevPiModIO(autorefresh=True, debug=debug)
        cls.__revpi.cycletime = cycletime

        # Make sure outputs are reset even if the program crashes
        atexit.register(cls.cleanup)

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

    # ------------------------------------------------------------------ #
    # PV / IO binding                                                    #
    # ------------------------------------------------------------------ #

    @classmethod
    def builder(
        cls,
        io_name: str,
        pv_name: str | None = None,
        DRVL: int | float | None = None,
        DRVH: int | float | None = None,
        **fields,
    ) -> PythonDevice | None:
        """Create an EPICS record bound to the requested RevPi IO.

        The actual record type (ai/ao/bi/bo/etc.) is delegated to the
        *builder function* registered for the IO's *ProductType*.

        Parameters
        ----------
        io_name :
            Name of the IO as exported by *revpimodio2*.
        pv_name :
            Desired EPICS PV name. When *None* ``io_name`` is reused.
        DRVL / DRVH :
            Display limits passed to the underlying EPICS record.
        **fields :
            Arbitrary extra keyword arguments propagated to the builder.

        Returns
        -------
        PythonDevice | None
            The created record or *None* when something went wrong.
        """
        if cls.__revpi is None:
            logger.error("RevPiEpics has not been initialised; call 'initialize()' first.")
            return None

        if not hasattr(cls.__revpi.io, io_name):
            logger.error("IO name %s not found in RevPi IOs.", io_name)
            return None

        if io_name in cls.__liste_io:
            logger.error("The IO '%s' is already bound to a PV.", io_name)
            return None

        if pv_name is not None and pv_name in cls.__liste_pv:
            logger.error("The PV name '%s' is already in use.", pv_name)
            return None

        io_point: IntIO = getattr(cls.__revpi.io, io_name)
        product_type: ProductType = io_point._parentdevice._producttype
        builder_func = builder_registry.get(product_type)

        if builder_func is None:
            logger.warning("No builder registered for product type %s.", product_type)
            return None

        if pv_name is None:
            pv_name = io_name

        record = builder_func(
            cls=cls,
            io_point=io_point,
            pv_name=pv_name,
            DRVL=DRVL,
            DRVH=DRVH,
            **fields,
        )

        if record is not None:
            cls.__map_io_to_pv[io_name] = pv_name
            cls.__map_pv_to_io[pv_name] = io_name
            cls.__liste_io[io_name] = io_point
            cls.__liste_pv[pv_name] = record

        return record

    # ------------------------------------------------------------------ #
    # Event handlers                                                     #
    # ------------------------------------------------------------------ #

    @classmethod
    def _io_value_change(cls, event) -> None:
        """Callback executed by *revpimodio2* when an IO value changes."""
        pv_name = cls.__map_io_to_pv[event.ioname]
        record = cls.__liste_pv[pv_name]
        record.set(event.iovalue)
        logger.debug("IO %s → PV %s = %s", event.ioname, pv_name, event.iovalue)

    @classmethod
    def _io_status_change(cls, event) -> None:
        """Callback executed when the IO status word changes."""
        pv_name = cls.__map_io_to_pv[event.ioname]
        record = cls.__liste_pv[pv_name]
        record.set(cls._status_convert(event.iovalue))

    @staticmethod
    def _status_convert(value: int) -> int:
        """Return the number of significant bits in *value*.

        The result is used as a crude error-/status-code mapping.
        """
        return int(value).bit_length()

    # ------------------------------------------------------------------ #
    # Write record                                                       #
    # ------------------------------------------------------------------ #

    @classmethod
    def _record_write(cls, pv_name: str, value: float) -> None:
        """EPICS → hardware write handler."""
        try:
            io_name = cls.__map_pv_to_io[pv_name]
            io_point = cls.__liste_io[io_name]
            io_point.value = int(value)
            logger.debug("PV %s → IO %s = %d", pv_name, io_name, int(value))
        except Exception as exc:
            logger.error("Failed to write to %s: %s", pv_name, exc)

    # ------------------------------------------------------------------ #
    # Runtime                                                            #
    # ------------------------------------------------------------------ #

    @classmethod
    def start(cls) -> None:
        """Start the *revpimodio2* main loop (non-blocking)."""
        if cls.__revpi is None:
            raise RuntimeError("RevPiEpics has not been initialised.")
        cls.__revpi.autorefresh_all()
        cls.__revpi.mainloop(blocking=False)

    # ------------------------------------------------------------------ #
    # Exit                                                               #
    # ------------------------------------------------------------------ #

    @classmethod
    def cleanup(cls) -> None:
        """Reset every registered analogue output to its factory default."""
        for io_point in cls.__liste_io.values():
            # Type 301 corresponds to output in RevPi
            if getattr(io_point, "type", None) == 301:
                io_point.value = io_point.get_intdefaultvalue()
        logger.debug("Cleanup complete.")
