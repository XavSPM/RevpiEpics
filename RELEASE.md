# Notes de mise à jour (Release) - RevPiEpics

## Nouveautés et Améliorations : Architecture, Flexibilité et Autosave

### 1. Refonte de l'Architecture Interne (IOMap)
L'objet monolithique `IOMap` a été refactoré en une hiérarchie orientée objet plus propre. Désormais, les entrées/sorties analogiques utilisent la classe `AnalogIOMap`, ce qui allège l'empreinte mémoire des signaux binaires simples et supprime de nombreuses vérifications conditionnelles redondantes.

### 2. Intégration Native de l'Autosave (softioc.autosave)
Il est maintenant possible d'activer la sauvegarde automatique des états de configuration EPICS :
- **Activation Globale :** Dans `RevPiEpics.init(..., autosave=True, autosave_dir="/tmp/save")`.
- **Contrôle Granulaire :** Lors de la création d'un PV analogique, vous pouvez spécifier `autosave_multiplier=True` ou `autosave_offset=True` pour sauvegarder ces paramètres.
- Le paramètre natif `autosave=...` pour les variables principales est également supporté de base pour sauvegarder des tableaux (ex: `["PREC", "EGU", "VAL"]`).

### 3. Simplification des Échelles Logicielles (Float PVs)
L'ancien comportement qui générait un PV "DIVISEUR" entier a été retiré. Le système s'appuie désormais uniquement sur un `:MULTIPLIER` et un `:OFFSET`. Ces deux PVs sont aujourd'hui exportés en Record Flottant (`aOut`). Ils acceptent donc pleinement les mathématiques décimales (ex: `0.1` au lieu de diviser par `10`) et les valeurs négatives.

### 4. Flexibilité sur les PVs de Statut
Les PVs de statut (ex: `...:STATUS`) ne sont plus créés de manière forcée pour chaque I/O analogique. L'IHM gagne en flexibilité : il suffit de déclarer manuellement via `RevPiEpics.builder("InputStatus_1...")` les statuts à exposer sur le réseau.

### 5. API Objet Enrichie
L'objet RecordWrapper retourné par `RevPiEpics.builder(...)` lors du ciblage d'un module analogique embarque dorénavant ses propriétés filles. Vous pouvez ainsi dynamiquement piloter les paramètres internes via Python : `my_sensor.offset.set(10)`.

---

## Fonctionnement du Moteur AIO (Rappel)

### Calcul mathématique déporté (SoftIOC)
À l'initialisation, le système importe vos paramètres logiciels figurant dans PiCtory pour calquer la base matérielle par défaut (hardware scale). La nouvelle mise à l'échelle demandée s'effectue intégralement par un calcul dynamique via des Soft PV intégrés dans la boucle interne (`pvsync.py`).

### Édition temps-réel via EPICS
Un opérateur peut librement modifier les Soft PVs virtuels générés (comme `caput IN2_1:MULTIPLIER 0.5`) pour ajuster instantanément le comportement :
* **Lecture (IN)** : Calcul inversé depuis la valeur binaire (brute) à l'aide des paramètres hardware initiaux, puis application en direct de la nouvelle échelle EPICS.
* **Écriture (OUT)** : Convertit la requête SCADA via l'échelle EPICS, puis réapplique l'échelle matérielle usine pour fournir la configuration binaire exacte exigée par le convertisseur DA.
