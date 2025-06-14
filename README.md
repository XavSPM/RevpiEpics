# RevPiEpics

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

**RevPiEpics** is a Python library that simplifies the creation of EPICS Process Variables (PVs) directly from Revolution Pi I/Os, using [pythonSoftIOC](https://github.com/DiamondLightSource/pythonSoftIOC) and [revpimodio2](https://revpimodio.org/en/homepage/).

## 🎯 Key Features

- **Simplified configuration**: Quick creation of EPICS PVs from RevPi I/Os
- **Automatic detection**: Automatic recognition of input/output types
- **Advanced configuration**: Customization of PV names, units, limits and descriptions
- **Integrated update loop**: Configurable automatic read/write cycle
- **Multi-threading support**: Compatible with cothread and asyncio

## 🔧 Supported Hardware

### Compatible Revolution Pi Modules
- **RevPi Base**: Connect 5/4/S/SE, Core S/SE
- **Extension Modules**: AIO (Analog Input/Output)

> ⚠️ **Note**: Other modules may be supported in future versions.

### Requirements
- I/Os configured via [PiCtory interface](https://revolutionpi.com/documentation/pictory/)
- 64-bit operating system

> 💡 **32-bit OS**: If you're using a 32-bit OS, follow this guide: [Download a compatible image](https://revolutionpi.com/documentation/revpi-images/#download-and-check-image)

## 📦 Installation

### Step 1: Clone the repository

On your RevPi via SSH or Copilot interface:
```bash
git clone https://github.com/XavSPM/RevpiEpics.git
cd RevpiEpics
```

### Step 2: Installation

#### Option 1: Virtual environment
This approach is the cleanest and safest:
```bash
python3 -m venv venv
source venv/bin/activate
pip install .
```

> **Important**: Always activate the virtual environment before running your scripts:
> ```bash
> source venv/bin/activate
> ```

#### Option 2: System installation
```bash
pip install . --break-system-packages
```

> ⚠️ **Warning**: This method modifies system packages but allows usage with [RevPi Commander](https://revolutionpi.com/documentation/tutorials/python/).

### Step 3: Optional cothread installation

Depending on your implementation choice (cothread or asyncio), you might need to install cothread:
```bash
pip install cothread
```

> 📖 **More info**: [Differences between asyncio and cothread](https://diamondlightsource.github.io/pythonSoftIOC/master/explanations/asyncio-cothread-differences.html)

## 🚀 Usage

### Basic Example

```python
from revpiepics import RevPiEpics
from softioc import builder

# Configure EPICS prefix
builder.SetDeviceName("TEST")

# Initialization (debug and cycletime are optional)
RevPiEpics.init(debug=True, cycletime=200)

# Create PVs with automatic type detection
ai1 = RevPiEpics.builder("OutputStatus_2_i06")  # PV: TEST:OutputStatus_2_i06
ai2 = RevPiEpics.builder("OutputStatus_1_i06", "Out1Status")  # PV: TEST:Out1Status

# Examples with different I/O types
ai3 = RevPiEpics.builder("InputStatus_1_i06")   # Input Status
ai4 = RevPiEpics.builder(io_name="InputValue_2_i01", pv_name="IN2_1")    # Analog input / PV: TEST:IN2_1
ai5 = RevPiEpics.builder("InputStatus_1_i01")

# Advanced configuration with metadata
ao1 = RevPiEpics.builder(
    io_name="OutputValue_2_i06", 
    pv_name="Out2", 
    DESC="Analog output 2", 
    EGU="mV"
)

# Set limits (outputs only)
ao2 = RevPiEpics.builder(
    io_name="OutputValue_1_i06", 
    pv_name="Out1", 
    DRVL=8000,    # Low limit
    DRVH=19000    # High limit
)

# Start I/O loop and IOC
RevPiEpics.start()
```

### Using add_loop_task

RevPiEpics allows adding custom tasks to the main I/O loop with `add_loop_task()`. This approach is ideal for integrating business logic directly into the update cycle.

```python
from revpiepics import RevPiEpics
from softioc import builder

builder.SetDeviceName("ACCELERATOR")

# Initialization with 100ms cycle
# auto_prefix allows using names given to cards by PiCtory
RevPiEpics.init(debug=True, cycletime=100, auto_prefix=True)

temp_sensor = RevPiEpics.builder("InputValue_1_i06", EGU="°C") 
pump_speed = RevPiEpics.builder("OutputValue_1_i06", EGU="%", DRVL=0, DRVH=100)

# Using EPICS records
def temperature_control():
    if temp_sensor.get() > 50:
        pump_speed.set(100)
    else:
        pump_speed.set(20)   

# You can also use revpimodio2 directly
revpi = RevPiEpics.get_mod_io()
def system_watchdog():
    if revpi.io['InputValue_2_i06'].value > 0:
        revpi.io['OutputValue_2_i06'].value = 100
  
# Add tasks to the main loop
RevPiEpics.add_loop_task(temperature_control)
RevPiEpics.add_loop_task(system_watchdog)

# Start IOC with integrated tasks
RevPiEpics.start()
```

### Cyclic processing with cothread

You can also use cothread or asyncio processing. However, this may cause concurrency with the main RevPiEpics loop. Use with caution.

```python
from softioc import builder
from revpiepics import RevPiEpics
import cothread

builder.SetDeviceName("TEST")
RevPiEpics.init()

# Create PVs
output_pv = RevPiEpics.builder(io_name="OutputValue_1_i06", pv_name="Out1")
input_pv = RevPiEpics.builder(io_name="InputValue_1_i06", pv_name="In1")

def cyclic_processing():
    """Cyclic processing loop"""
    while True:
        # Read input and process
        input_value = input_pv.get()
        processed_value = input_value + 100
        
        # Write to output
        output_pv.set(processed_value)
        
        # Wait 1 second
        cothread.Sleep(1)

# Launch task in parallel
cothread.Spawn(cyclic_processing)

# Start IOC
RevPiEpics.start()
```

### Cyclic processing with asyncio

```python
from softioc import builder, asyncio_dispatcher
from revpiepics import RevPiEpics
import asyncio

# Create asyncio dispatcher
dispatcher = asyncio_dispatcher.AsyncioDispatcher()

builder.SetDeviceName("TEST")
RevPiEpics.init()

# Create PVs
output_pv = RevPiEpics.builder(io_name="OutputValue_1_i06", pv_name="Out1")
input_pv = RevPiEpics.builder(io_name="InputValue_1_i06", pv_name="In1")

async def async_processing():
    """Asynchronous processing"""
    while True:
        # Read and process
        input_value = input_pv.get()
        processed_value = input_value + 100
        output_pv.set(processed_value)
        
        # Asynchronous wait
        await asyncio.sleep(1)

# Launch asynchronous task
dispatcher(async_processing)

# Start with dispatcher
RevPiEpics.start(dispatcher=dispatcher)
```

## ⚙️ Advanced Configuration

### Initialization Parameters

```python
RevPiEpics.init(
    debug=True,        # Enable debug messages
    cycletime=100,     # Update cycle in ms (default: 200ms)
    auto_prefix=True   # Use PiCtory names for prefixes
    cleanup=True       # Enable automatic cleanup on exit. 
                       # Resets the default input/output value (PiControl) before exiting
)
```

### PV Configuration Options

| Parameter | Description | Type | Example |
|-----------|-------------|------|---------|
| `io_name` | RevPi I/O name (required) | str | `"OutputValue_1_i06"` |
| `pv_name` | EPICS PV name (optional) | str | `"Temperature"` |
| `DESC` | PV description | str | `"Room temperature"` |
| `EGU` | Engineering units | str | `"°C"`, `"mV"`, `"bar"` |
| `DRVL` | Low limit (outputs) | float | `0.0` |
| `DRVH` | High limit (outputs) | float | `100.0` |

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────┐    ┌─────────────────┐
│   Revolution Pi │    │  RevPiEpics  │    │  EPICS Network  │
│                 │◄──►│              │◄──►│                 │
│  I/O Modules    │    │  pythonSoftIOC│    │  Client Apps    │
└─────────────────┘    └──────────────┘    └─────────────────┘
```

## 🔍 Troubleshooting

### Common Issues

**PV not found:**
- Check PiCtory configuration
- Make sure I/O name is correct
- Enable debug mode: `RevPiEpics.init(debug=True)`

**Performance:**
- For fast cycles (< 100ms), test performance
- Reduce number of PVs if necessary
- Use `add_loop_task` for better performance

## 🤝 Contributing

Contributions and feedback are very welcome! 🚀

### How to contribute
1. Fork the project
2. Create a branch for your feature
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

### Roadmap
- [ ] Support for DIO/DI/DO modules
- [ ] EPICS alarm handling
- [ ] Graphical configuration interface
- [ ] Unit and integration tests
- [ ] Complete API documentation

## 📄 Licenses

This project uses several components under different licenses:

- **RevPiEpics**: MIT License
- **pythonSoftIOC**: Apache License 2.0 (see `LICENSE_pythonSoftIOC`)
- **revpimodio2**: GNU LGPL v2.1 (see `LICENSE_revpimodio2`)

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/XavSPM/RevpiEpics/issues)
- **EPICS Documentation**: [EPICS Documentation](https://epics-controls.org/)
- **Revolution Pi**: [Official Documentation](https://revolutionpi.com/documentation/)

---

**MIT License**

Copyright (c) 2025 Xavier Goiziou

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.