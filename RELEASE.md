# Release Notes - RevPiEpics v0.2.1

## What's New: Architecture, Flexibility, and Autosave

### 1. Internal Architecture Refactoring (IOMap)
The monolithic `IOMap` object has been refactored into a cleaner object-oriented hierarchy. Analog inputs/outputs now use the `AnalogIOMap` class, which reduces the memory footprint for simple binary signals and removes numerous redundant conditional checks.

### 2. Native Autosave Integration (softioc.autosave)
It is now possible to enable automatic backup of EPICS configuration states:
- **Global Activation:** In `RevPiEpics.init(..., autosave=True, autosave_dir="/tmp/save")`.
- **Granular Control:** When creating an analog PV, you can specify `autosave_multiplier=True` or `autosave_offset=True` to specifically save these parameters to the `.softsav` file.
- The standard `autosave=...` parameter for primary variables is fully supported out of the box (e.g., `autosave=["PREC", "EGU", "VAL"]`).

### 3. Simplified Software Scaling (Float PVs)
The previous behavior that generated an integer "DIVISOR" PV has been safely removed. The system now strictly relies on a `:MULTIPLIER` and an `:OFFSET`. Both PVs are now exported as Floating-point Records (`aOut`). They fully accept standard decimal computations (e.g. `0.1` instead of dividing by `10`) and negative values.

### 4. Direct Scaling Parameter Setup
When building an analog I/O, developers can disregard PiCtory's system hardware defaults and manually inject the soft EPICS startup configuration straight from python:
`RevPiEpics.builder("IN1", initial_multiplier=1.5, initial_offset=20.0)`

### 5. Enriched Object API
The `RecordWrapper` Python object returned by `RevPiEpics.builder(...)` when targeting an analog module now structurally integrates its child scaling records. You can dynamically drive tracking parameters from Python execution logic: `my_sensor.offset.set(10)`.

---

## AIO Engine Core Mechanics (Reminder)

### Delegated Mathematical Computation (SoftIOC)
At initialization, the system imports the software parameters mapped in PiCtory to establish an absolute factory baseline. The new scalable conversion is managed entirely by live synchronized computations across the soft PV backend (`pvsync.py`).

### Real-time EPICS Editing
An operator can freely modify the mapped Soft PVs (like `caput IN2_1:MULTIPLIER 0.5`) to instantly adjust the underlying behavior:
* **Reading (IN)**: Inverse calculation from the initial raw binary value scaling back to base zero, subsequently layered dynamically beneath the new EPICS ratio.
* **Writing (OUT)**: Resolves the SCADA request according to the EPICS layer, then translates and applies the factory hardware ratio to pipeline directly to the Digital-to-Analog hardware converter.
