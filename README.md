
# revpiepics

**revpiepics** is a Python library that makes it easy to create EPICS Process Variables (PVs) directly from Revolution Pi IOs, using `pythonSoftIoc` and `revpimodio2`.

---

## ✨ Features

- Simple and fast creation of EPICS PVs from RevPi IOs  
- Automatic detection of input/output types  
- Advanced PV configuration (names, units, limits, descriptions)  
- Built-in IO update loop

---

## 🔧 Prerequisites

- RevPi Base Module (Connect 5/4/S/SE, Core S/SE)  
- AIO Extension Modules  
- IOs configured via the [PiCtory interface](https://revolutionpi.com/documentation/pictory/)  
- 64-bit operating system

👉 If you’re not using a 64-bit OS, follow this guide:  
[Download and check a compatible image](https://revolutionpi.com/documentation/revpi-images/#download-and-check-image)

---

## 📥 Download

After connecting to your RevPi via SSH or using the Copilote interface:

```bash
git clone https://github.com/XavSPM/RevpiEpics.git
```

---

## 💾 Installation

Because Debian and its derivatives (like Raspberry Pi OS) protect the system environment from direct `pip` installations,  
you **cannot** simply run:

```bash
cd RevpiEpics
pip install .
```

### ✅ Recommended: use a virtual environment

This is the cleanest and safest approach because it won’t affect system-wide packages:

```bash
python3 -m venv venv
source venv/bin/activate
cd RevpiEpics
pip install .
```

Once installed, always run your scripts **with the virtual environment activated** (`source venv/bin/activate`).

### ⚠️ Alternative (not recommended): install system-wide

If you really want to install at the system level:

```bash
cd RevpiEpics
pip install . --break-system-packages
```

⚠️ Warning: This can cause conflicts with packages installed via `apt`.

---

### Install cothread (if needed)

Depending on whether you’re using `cothread` or `asyncio` in your program, you might need to install the `cothread` library.  
For more details, see:  
[What are the differences between asyncio and using the cothread Library?](https://diamondlightsource.github.io/pythonSoftIOC/master/explanations/asyncio-cothread-differences.html)

```bash
pip install cothread
```

---

## 🚀 Usage

### Minimal example

```python
from softioc import builder, softioc
from revpiepics import RevPiEpics

builder.SetDeviceName("TEST")
a = RevPiEpics(debug=True, cycletime=200)  # debug and cycletime are optional

ai1 = a.builder("OutputStatus_2_i06")  # PV name = TEST:OutputStatus_2_i06
ai2 = a.builder("OutputStatus_1_i06", "Out1Status")  # PV name = TEST:Out1Status
ai3 = a.builder("InputStatus_1_i06")  # Automatic type detection
ai4 = a.builder("InputValue_1_i06")
ao1 = a.builder(io_name="OutputValue_2_i06", pv_name="Out2", DESC="Out 1", EGU="mV")  # Advanced config
ao2 = a.builder(io_name="OutputValue_1_i06", pv_name="Out1", DRVL="8000", DRVH=19000)  # Set limits

# Start the IOC
builder.LoadDatabase()
softioc.iocInit()

# Start IO loop
a.start() 

# Keep the IOC running
softioc.non_interactive_ioc()  # or softioc.interactive_ioc(globals())
```

---

## 📦 Supported Modules

- AIO (Analog Input/Output)

➡️ Other modules may be supported in the future.

---

## 📚 Dependencies

- [pythonSoftIoc](https://pypi.org/project/pythonSoftIOC/)  
- [revpimodio2](https://pypi.org/project/revpimodio2/)

---

## 🛠 Development

This library is under active development.  
Contributions and feedback are very welcome! 🚀

---

## 📄 Third-party Licenses

- **pythonSoftIOC**  
  License: Apache License 2.0  
  See the `LICENSE_pythonSoftIOC` file for details.

- **revpimodio2**  
  License: GNU LGPL v2.1  
  See the `LICENSE_revpimodio2` file for details.

---

## ⚖️ Project License

MIT License  
See the `LICENSE` file for details.

```
MIT License

Copyright (c) 2025 Xavier Goiziou

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```