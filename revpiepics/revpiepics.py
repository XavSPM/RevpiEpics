# -*- coding: utf-8 -*-
"""RevPi ⇔ EPICS bridge (SoftIOC-only, event‑driven sync).

Synchronisation contrôlée avec lecture/écriture explicite de l'image de process
via readprocimg() et writeprocimg(). Rafraîchissement régulier à fréquence définie.

Version améliorée avec corrections de bugs, meilleure gestion d'erreurs,
et optimisations de performance. Utilise des méthodes de classe (cls).
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
    """Pont entre RevPi et EPICS avec synchronisation bidirectionnelle."""
    _dictmap = DicIOMap()
    _revpi: Optional[revpimodio2.RevPiModIO] = None
    _builder_registry: Dict[int, Callable] = {}
    _initialized = False
    _cleanup = False
    _auto_prefix = False
    _cycle_time_ms = None
    _pv_sync: Optional["PVSyncThread"] = None
    _lock = Lock()
    _custom_functions: Dict[str, Callable] = {}
    _custom_functions_lock = Lock()

    @staticmethod
    def _requires_init(func):
        """Décorateur pour vérifier l'initialisation."""

        @functools.wraps(func)
        def wrapper(cls, *args, **kwargs):
            if not cls._initialized:
                raise RevPiEpicsInitError(
                    f"RevPiEpics non initialisé. Appelez init() d'abord."
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
        """
        Initialise le pont RevPi-EPICS.

        Args:
            cycletime_ms: Temps de cycle en millisecondes
            debug: Mode debug
            cleanup: Nettoyage automatique à la sortie
            auto_prefix: Préfixe automatique des PV
            refresh_rate: Taux de rafraîchissement (non utilisé actuellement)
        """
        with cls._lock:
            if cls._initialized:
                logger.warning("RevPiEpics déjà initialisé")
                return

            try:
                cls._revpi = revpimodio2.RevPiModIO(autorefresh=False, debug=debug)

                if cycletime_ms is not None:
                    if cycletime_ms < 20:
                        raise ValueError(f"Temps de cycle minimum: 20 ms")
                    cls._cycle_time_ms = cycletime_ms

                cls._cleanup = cleanup
                cls._auto_prefix = auto_prefix

                log_level = logging.DEBUG if debug else logging.INFO
                log_format = (
                    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                    if debug else "[%(levelname)s]: %(message)s"
                )
                logging.basicConfig(level=log_level, format=log_format)

                cls._pv_sync = PVSyncThread(cls)
                cls._initialized = True

                logger.info(f"RevPiEpics initialisé")

            except Exception as e:
                logger.error(f"Erreur lors de l'initialisation: {e}")
                raise RevPiEpicsInitError(f"Échec de l'initialisation: {e}") from e

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
        """
        Crée un PV EPICS lié à une E/S RevPi.

        Args:
            io_name: Nom de l'E/S RevPi
            pv_name: Nom du PV EPICS (optionnel)
            DRVL: Limite basse (optionnel)
            DRVH: Limite haute (optionnel)
            **fields: Champs supplémentaires pour l'enregistrement

        Returns:
            RecordWrapper créé ou None en cas d'erreur
        """
        try:
            if not cls._revpi:
                cls._initialized = False
                raise RevPiEpicsBuilderError(f"Erreure d'inialisation")
            
            if not hasattr(cls._revpi.io, io_name):
                raise RevPiEpicsBuilderError(f"E/S '{io_name}' introuvable")

            if cls._dictmap.get_by_io_name(io_name):
                raise RevPiEpicsBuilderError(f"E/S '{io_name}' déjà liée")

            if pv_name and cls._dictmap.get_by_pv_name(pv_name):
                raise RevPiEpicsBuilderError(f"PV '{pv_name}' déjà existant")

            # Récupération de l'E/S
            io_point = getattr(cls._revpi.io, io_name)
            product_type = io_point._parentdevice._producttype

            # Sélection du builder
            build_func = cls._builder_registry.get(product_type)
            if build_func is None:
                raise RevPiEpicsBuilderError(
                    f"Aucun builder pour le type de produit {product_type}"
                )

            if pv_name is None:
                pv_name = io_name

            if cls._auto_prefix:
                mapping = cls._build_with_prefix(
                    build_func, io_point, pv_name, DRVL, DRVH, **fields
                )
            else:
                mapping = build_func(
                    io_point=io_point, pv_name=pv_name,
                    DRVL=DRVL, DRVH=DRVH, **fields
                )

            if mapping:
                cls._dictmap.add(mapping)
                logger.debug(f"PV '{pv_name}' créé pour E/S '{io_name}'")
                return mapping.get_recode()
            else:
                return None

        except Exception as e:
            logger.error(f"Erreur lors de la création du PV: {e}")
            return None

    @classmethod
    def _build_with_prefix(cls, build_func, io_point, pv_name, DRVL, DRVH, **fields):
        """Construit un PV avec préfixe automatique."""
        rec_names = cast(SimpleRecordNames, builder.GetRecordNames())
        saved_prefix = rec_names.prefix.copy()

        try:
            if cls._revpi:
                if cls._revpi.core and cls._revpi.core.name:
                    rec_names.PushPrefix(cls._revpi.core.name)
                if io_point._parentdevice and io_point._parentdevice.name:
                    rec_names.PushPrefix(io_point._parentdevice.name)

            return build_func(
                io_point=io_point, pv_name=pv_name,
                DRVL=DRVL, DRVH=DRVH, **fields
            )
        finally:
            rec_names.prefix = saved_prefix

    @classmethod
    @_requires_init
    def start(
            cls,
            interactive: bool = False,
            dispatcher: Optional[AsyncioDispatcher] = None
    ) -> None:
        """
        Démarre le pont RevPi-EPICS.

        Args:
            interactive: Mode interactif
            dispatcher: Dispatcher asyncio optionnel
        """
        try:
            builder.LoadDatabase()

            if dispatcher:
                softioc.iocInit(dispatcher)
            else:
                softioc.iocInit()

            if cls._cleanup:
                atexit.register(cls.stop)

            if cls._pv_sync:
                cls._pv_sync.start()
                logger.info("Pont RevPi-EPICS démarré")
            else:
                raise RuntimeError(f"Erreure dans le Thread de synchronisation")

            if interactive:
                softioc.interactive_ioc(globals())
            else:
                softioc.non_interactive_ioc()

        except Exception as e:
            logger.error(f"Erreur lors du démarrage: {e}")
            raise

    @classmethod
    @_requires_init
    def stop(cls) -> None:
        """Arrête le pont RevPi-EPICS."""
        logger.info("Arrêt du pont RevPi-EPICS...")

        if cls._pv_sync:
            cls._pv_sync.stop()

        if cls._revpi:
            cls._revpi.exit()
        
        if cls._pv_sync:
            cls._pv_sync._stop_event.set()
            
        with cls._lock:
            cls._initialized = False


    @classmethod
    def register_builder(cls, product_type: int, func: Callable) -> None:
        """
        Enregistre un builder pour un type de produit.

        Args:
            product_type: Type de produit RevPi
            func: Fonction de construction des PV
        """
        if not isinstance(product_type, int):
            raise TypeError("product_type doit être un entier")
        if not callable(func):
            raise TypeError("func doit être callable")

        cls._builder_registry[product_type] = func
        logger.debug(f"Builder enregistré pour le type {product_type}")

    @classmethod
    def get_mappings(cls) -> Dict[str, IOMap]:
        """Retourne tous les mappings."""
        return cls._dictmap.get_all_mappings()

    @classmethod
    def remove_mapping(cls, io_name: str) -> bool:
        """Supprime un mapping."""
        return cls._dictmap.remove(io_name)

    @classmethod
    def add_custom_function(cls, func: Callable) -> None:
        """
        Ajoute une fonction personnalisée à exécuter dans le cycle de synchronisation.

        Args:
            func: Fonction à exécuter
        Raises:
            TypeError: Si func n'est pas callable
        """
        if not callable(func):
            raise TypeError("func doit être callable")

        with cls._custom_functions_lock:
            func_name = getattr(func, '__name__', None)
            if func_name is None:
                raise ValueError(f"Erreure avec la fonction")

            elif func_name in cls._custom_functions:
                raise ValueError(f"Une fonction {func_name} existe déjà")

            # Stockage de la fonction avec ses arguments
            cls._custom_functions[func_name] = func

        logger.debug(f"Fonction personnalisée ajoutée au cycle de synchronisation")

    @classmethod
    def clear_custom_functions(cls) -> int:
        """
        Supprime toutes les fonctions personnalisées.

        Returns:
            Nombre de fonctions supprimées
        """
        with cls._custom_functions_lock:
            count = len(cls._custom_functions)
            cls._custom_functions.clear()
            logger.debug(f"{count} fonction(s) personnalisée(s) supprimée(s)")
            return count

    @classmethod
    def get_dic_io_map(cls) -> DicIOMap:
        """Retourne le dictionnaire des mappings"""
        return cls._dictmap

    @classmethod
    def get_mod_io(cls) -> Optional[revpimodio2.RevPiModIO]:
        """Retourne l'instance RevPiModIO"""
        return cls._revpi
    
class RevPiEpicsError(Exception):
    """Exception de base pour RevPiEpics."""
    pass


class RevPiEpicsInitError(RevPiEpicsError):
    """Erreur d'initialisation."""
    pass


class RevPiEpicsBuilderError(RevPiEpicsError):
    """Erreur de construction de PV."""
    pass