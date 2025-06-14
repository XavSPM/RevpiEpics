from dataclasses import dataclass, field
from revpimodio2.io import IntIO
from .recod import RecordDirection, RecordType
import logging
from typing import Any, Optional, Dict, TYPE_CHECKING
from threading import Lock
if TYPE_CHECKING:
    from softioc.pythonSoftIoc import RecordWrapper

logger = logging.getLogger(__name__)

@dataclass
class IOMap:
    """
    Mapping between a RevPi I/O point and an EPICS Process Variable.
    
    This class represents a bidirectional mapping that connects RevPi industrial
    I/O hardware with EPICS control system Process Variables (PVs). It handles
    the synchronization of data between the physical I/O and the EPICS database,
    maintaining state information and caching for optimal performance.
    
    Attributes:
        io_name: Name/identifier of the RevPi I/O point
        pv_name: Name of the corresponding EPICS Process Variable
        io_point: RevPi I/O object for hardware access
        record: EPICS record wrapper for PV access
        direction: Data flow direction (INPUT/OUTPUT)
        record_type: Type of EPICS record (ANALOG/BINARY/STATUS)
        update_record: Flag indicating if record needs update from PV
        last_io_value: Cached last known I/O value for change detection
        last_pv_value: Cached last known PV value for change detection
    """
    # Core mapping configuration
    io_name: str                   # RevPi I/O point identifier
    pv_name: str                   # EPICS Process Variable name
    io_point: IntIO                # RevPi I/O hardware interface
    record: 'RecordWrapper'        # EPICS record wrapper
    direction: RecordDirection     # Data flow direction (INPUT/OUTPUT)
    record_type: RecordType        # EPICS record type classification
    
    # State management for synchronization
    update_record: bool = False                   # Flag for pending record updates
    last_io_value: Optional[Any] = None           # Cached I/O value for change detection
    last_pv_value: Optional[Any] = None           # Cached PV value for change detection

    def __post_init__(self):
        """
        Initialize cache values after dataclass construction.
        
        Reads initial values from both RevPi I/O hardware and EPICS record
        to establish baseline for change detection. Handles initialization
        errors gracefully to avoid startup failures.
        """
        try:
            # Initialize cache with current hardware and PV values
            self.last_io_value = self.io_point.value
            self.last_pv_value = self.record.get()
        except Exception as e:
            # Log initialization errors but don't fail - values will be updated in sync cycle
            logger.warning("Erreur lors de l'initialisation du cache pour %s: %s", self.io_name, e)

    def get_record(self):
        """
        Get the EPICS record wrapper.
        
        Returns:
            RecordWrapper: The EPICS record associated with this mapping
        """
        return self.record

    def get_io_pint(self):
        """
        Get the RevPi I/O point object.
        
        Returns:
            IntIO: The RevPi I/O point for hardware access
        """
        return self.io_point

@dataclass
class DicIOMap:
    """
    Bidirectional dictionary for I/O mappings management.
    
    Provides efficient lookup of IOMap objects by either RevPi I/O name or
    EPICS PV name. Thread-safe implementation using locks to ensure data
    consistency in multi-threaded environments. Maintains synchronized
    dictionaries for fast bidirectional access.
    
    This class is essential for the synchronization thread to quickly locate
    mappings during the real-time sync cycles without performance overhead.
    """
    
    # Bidirectional mapping dictionaries
    map_io: Dict[str, IOMap] = field(default_factory=dict)    # I/O name -> IOMap lookup
    map_pv: Dict[str, IOMap] = field(default_factory=dict)    # PV name -> IOMap lookup
    
    # Thread safety for concurrent access
    _lock: Lock = field(default_factory=Lock, init=False)     # Protects dictionary operations

    def add(self, mapping: IOMap) -> None:
        """
        Add a new I/O mapping to both dictionaries.
        
        Thread-safe method to add an IOMap to both lookup dictionaries.
        Ensures consistency between I/O name and PV name mappings.
        
        Args:
            mapping: IOMap instance to add to the dictionaries
        """
        with self._lock:
            # Add to both dictionaries for bidirectional lookup
            self.map_io[mapping.io_name] = mapping
            self.map_pv[mapping.pv_name] = mapping

    def remove(self, io_name: str) -> bool:
        """
        Remove a mapping by I/O name.
        
        Thread-safe removal of an IOMap from both dictionaries.
        Maintains consistency by removing from both lookup tables.
        
        Args:
            io_name: Name of the I/O point to remove
            
        Returns:
            bool: True if mapping was found and removed, False otherwise
        """
        with self._lock:
            # Find mapping by I/O name
            mapping = self.map_io.get(io_name)
            if mapping:
                # Remove from both dictionaries to maintain consistency
                del self.map_io[io_name]
                del self.map_pv[mapping.pv_name]
                return True
            return False

    def get_by_io_name(self, name: str) -> Optional[IOMap]:
        """
        Retrieve a mapping by I/O name.
        
        Thread-safe lookup of IOMap by RevPi I/O point name.
        Used by synchronization thread to find mappings for I/O updates.
        
        Args:
            name: Name of the RevPi I/O point
            
        Returns:
            Optional[IOMap]: IOMap if found, None otherwise
        """
        with self._lock:
            return self.map_io.get(name)

    def get_by_pv_name(self, name: str) -> Optional[IOMap]:
        """
        Retrieve a mapping by PV name.
        
        Thread-safe lookup of IOMap by EPICS Process Variable name.
        Used when EPICS records are updated to find corresponding I/O mapping.
        
        Args:
            name: Name of the EPICS Process Variable
            
        Returns:
            Optional[IOMap]: IOMap if found, None otherwise
        """
        with self._lock:
            return self.map_pv.get(name)

    def get_all_mappings(self) -> Dict[str, IOMap]:
        """
        Return a copy of all mappings.
        
        Thread-safe method to get a snapshot of all current mappings.
        Returns a copy to prevent external modification of internal state.
        Used by synchronization thread to iterate over all mappings.
        
        Returns:
            Dict[str, IOMap]: Copy of all I/O name -> IOMap mappings
        """
        with self._lock:
            # Return copy to prevent external modification
            return self.map_io.copy()