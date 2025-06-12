from .revpiepics import logger,IOMap
from .recod import RecordDirection, RecordType
from .utils import status_bit_length
from threading import Event, Thread
from timeit import default_timer

class PVSyncThread(Thread):
    """Thread de synchronisation entre RevPi et EPICS."""

    def __init__(self, bridge_cls):
        super().__init__(daemon=True, name="PVSyncThread")
        self._bridge_cls = bridge_cls
        self._revpi = bridge_cls._revpi
        self._dictmap = bridge_cls._dictmap
        self._cycle_time_ms = bridge_cls._cycle_time_ms
        self._custom_functions = bridge_cls._custom_functions
        self._custom_functions_lock = bridge_cls._custom_functions_lock
        self._stop_event = Event()
        self._consecutive_errors = 0

    def run(self) -> None:
        """Boucle principale de synchronisation."""
        logger.info(f"Thread de synchronisation démarré (cycle: {self._cycle_time_ms}ms)")
        cycle_time_s = self._cycle_time_ms / 1000.0

        while not self._stop_event.is_set() and not self._revpi.exitsignal.is_set():
            cycle_start = default_timer()

            try:
                self._sync_cycle()

            except Exception as e:

                logger.critical(
                    f"Erreur : {e}"
                    f"Arrêt de la synchronisation"
                )
                self._bridge_cls.stop()
                break

            # Gestion du timing
            cycle_time = default_timer() - cycle_start
            cycle_time_ms = cycle_time * 1000

            if cycle_time < cycle_time_s:
                sleep_time = cycle_time_s - cycle_time
                self._stop_event.wait(timeout=sleep_time)
            else:
                logger.warning(f"Temps de cycle dépassé: {cycle_time_ms:.1f}ms > {self._cycle_time_ms}ms")

        logger.info("Thread de synchronisation arrêté")

    def _sync_cycle(self) -> None:
        """Effectue un cycle de synchronisation."""

        # Lecture de l'image de process
        self._revpi.readprocimg()

        # Synchronisation de tous les mappings
        mappings = self._dictmap.get_all_mappings()

        for mapping in mappings.values():
            try:
                if mapping.direction == RecordDirection.OUTPUT:
                    self._sync_output(mapping)
                elif mapping.direction == RecordDirection.INPUT:
                    self._sync_input(mapping)

            except Exception as e:
                logger.warning(
                    f"Erreur sync {mapping.io_name}: {e}"
                )

        # Écriture de l'image de process
        self._revpi.writeprocimg()

        # Exécution des fonctions personnalisées
        self._execute_custom_functions()

    def _sync_output(self, mapping: IOMap) -> None:
        """Synchronise une sortie (PV -> RevPi)."""
        if mapping.update_record:
            # Mise à jour depuis le PV vers l'E/S
            pv_value = mapping.record.get()
            pv_value = round(pv_value) if isinstance(pv_value, float) else pv_value

            if pv_value != mapping.io_point.value:
                mapping.io_point.value = pv_value
                mapping.last_io_value = pv_value

            mapping.update_record = False

        else:
            # Mise à jour depuis l'E/S vers le PV (feedback)
            io_value = mapping.io_point.value
            pv_value = mapping.record.get()
            pv_value = round(pv_value) if isinstance(pv_value, float) else pv_value

            if pv_value != io_value:
                mapping.record.set(io_value, process=False)
                mapping.last_pv_value = io_value

    def _sync_input(self, mapping: IOMap) -> None:
        """Synchronise une entrée (RevPi -> PV)."""
        io_value = mapping.io_point.value

        # Optimisation: éviter les mises à jour inutiles
        if io_value == mapping.last_io_value:
            return

        if mapping.record_type == RecordType.ANALOG:
            if mapping.record.get() != io_value:
                mapping.record.set(io_value)

        elif mapping.record_type == RecordType.STATUS:
            status_value = status_bit_length(io_value)
            if mapping.record.get() != status_value:
                mapping.record.set(status_value)

        elif mapping.record_type == RecordType.BINARY:
            binary_value = bool(io_value)
            if mapping.record.get() != binary_value:
                mapping.record.set(binary_value)

        mapping.last_io_value = io_value

    def _execute_custom_functions(self) -> None:
        """Exécute toutes les fonctions personnalisées"""
        if not self._custom_functions:
            return

        # Lecture d'image fraîche pour les fonctions personnalisées
        self._revpi.readprocimg()

        with self._custom_functions_lock:
            functions_to_execute = self._custom_functions.items()

        for func_name, func in functions_to_execute:
            try:
                func()

            except Exception as e:
                raise RuntimeError(f"Fonction personnalisée '{func_name}' a échoué: {e}")

        # Écriture d'image après toutes les fonctions personnalisées
        self._revpi.writeprocimg()

    def stop(self) -> None:
        """Arrête le thread de synchronisation."""
        self._stop_event.set()
        self.join(timeout=self._cycle_time_ms*10)

        if self.is_alive():
            logger.warning("Le thread de synchronisation n'a pas pu être arrêté proprement")