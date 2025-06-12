from dataclasses import dataclass, field
from revpimodio2.io import IntIO
from softioc.pythonSoftIoc import RecordWrapper

from .recod import RecordDirection, RecordType
from .revpiepics import logger

from typing import Any, Optional, Dict
from threading import Lock

@dataclass
class IOMap:
    """Mapping entre une E/S RevPi et un PV EPICS."""
    io_name: str
    pv_name: str
    io_point: IntIO
    record: RecordWrapper
    direction: RecordDirection
    record_type: RecordType
    update_record: bool = False
    last_io_value: Optional[Any] = None
    last_pv_value: Optional[Any] = None

    def __post_init__(self):
        """Initialise les valeurs de cache."""
        try:
            self.last_io_value = self.io_point.value
            self.last_pv_value = self.record.get()
        except Exception as e:
            logger.warning(f"Erreur lors de l'initialisation du cache pour {self.io_name}: {e}")
    
    def get_record(self):
        return self.record
    
    def get_io_pint(self):
        return self.io_point
    
@dataclass
class DicIOMap:
    """Dictionnaire bidirectionnel pour les mappings IO."""
    map_io: Dict[str, IOMap] = field(default_factory=dict)
    map_pv: Dict[str, IOMap] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, init=False)

    def add(self, mapping: IOMap) -> None:
        with self._lock:
            self.map_io[mapping.io_name] = mapping
            self.map_pv[mapping.pv_name] = mapping

    def remove(self, io_name: str) -> bool:
        """Supprime un mapping par nom d'IO."""
        with self._lock:
            mapping = self.map_io.get(io_name)
            if mapping:
                del self.map_io[io_name]
                del self.map_pv[mapping.pv_name]
                return True
            return False

    def get_by_io_name(self, name: str) -> Optional[IOMap]:
        """Récupère un mapping par nom d'IO."""
        with self._lock:
            return self.map_io.get(name)

    def get_by_pv_name(self, name: str) -> Optional[IOMap]:
        """Récupère un mapping par nom de PV."""
        with self._lock:
            return self.map_pv.get(name)

    def get_all_mappings(self) -> Dict[str, IOMap]:
        """Retourne une copie de tous les mappings."""
        with self._lock:
            return self.map_io.copy()