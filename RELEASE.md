# Notes de mise à jour (Release) - RevPiEpics

## Nouveautés et Améliorations : Intégration avancée de la carte AIO

### 1. Génération automatique de variables (Auto-PV)
L'appel à `RevPiEpics.builder(...)` pour une entrée ou sortie dynamique de la carte AIO (Analogique et Température) ne se contente plus de créer une seule variable. Il déploie désormais **automatiquement 5 PVs EPICS** associés pour faciliter le pilotage :
- Le signal principal de mesure (ex: `TEST:IN2_1`)
- Son statut opérationnel (ex: `TEST:IN2_1:STATUS`)
- Son échelle multiplicatrice (ex: `TEST:IN2_1:MULTIPLIER`)
- Son échelle de division (ex: `TEST:IN2_1:DIVISEUR`)
- Son décalage (ex: `TEST:IN2_1:OFFSET`)

### 2. Calcul mathématique déporté (SoftIOC)
Le driver noyau RevPi interdisant la réécriture dynamique sur les offsets de configuration en cours d'exécution, la mise à l'échelle pour l'AIO ne dépend plus uniquement de la couche matérielle figée.
- À l'initialisation, le système importe vos paramètres configurés dans **PiCtory** pour définir la base matérielle par défaut.
- Ensuite, la mise à l'échelle (Multiplier, Divisor, Offset) s'effectue intégralement par le biais d'un calcul logiciel dynamique intégré à la boucle de synchronisation (`pvsync.py`).

### 3. Édition temps-réel via EPICS
L'opérateur ou un IHM peuvent librement modifier l'un des Soft PVs virtuels générés (comme `caput TEST:IN2_1:DIVISEUR 100`) pour ajuster instantanément la valeur des signaux en cours d'acquisition ou d'émission. Le moteur Python `RevPiEpics` récupère dynamiquement :
* **En lecture** : la véritable mesure brute par *back-calcul* à l'aide des paramètres hardware initiaux, puis y applique vos nouvelles échelles logicielles.
* **En écriture** : désescalade votre signal de commande EPICS selon vos paramètres logiciels, puis applique l'échelle matérielle pour fournir à la carte AIO la grandeur physique numérisée correcte attendue par le Convertisseur Numérique/Analogique.

---
### Fichiers impactés
- **`aio.py`** : Refonte de `builder_aio` afin d'implémenter les multi-PVs, ajout de l'analyse des offsets de process image pour isoler les paramètres d'usine originels.
- **`revpiepics.py`** : La méthode principale du constructeur accepte dorénavant un tableau groupé (List) contenant la structure IOMap éclatée par l'AIO.
- **`iomap.py`** : Élargissement de la DataClass pour stocker les pointeurs EPICS vers les Soft PV (`pv_divisor`...) et préserver les constantes matérielles extraites (`hw_divisor`...).
- **`pvsync.py`** : Les routines `_sync_input` et `_sync_output` englobent désormais de formidables algorithmes croisés inversant les signaux dynamiquement en l'espace de quelques millisecondes.
- **`.gitignore`** : Présence garantie et vérifiée pour isoler les fichiers temporaires.
