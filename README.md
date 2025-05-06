# revpiepics

**revpiepics** is a Python library that allows you to create EPICS Process Variables (PVs) directly from Revolution Pi IOs, using `pythonSoftIoc` and `revpimodio2`.

## Prerequisites

- RevPi Base Module (Connect 5/4/S/SE, Core S/SE)
- AIO Extension Modules
- IOs configured using the PiCtory interface

To use this library, you need a 64-bit OS.  
If that’s not the case, follow this procedure:

👉 [Download and check a compatible image](https://revolutionpi.com/documentation/revpi-images/#download-and-check-image)

## Installation

```bash
pip install .
```

## Usage

### Example

```python
from softioc import builder, softioc
from revpiepics import RevPiEpics

builder.SetDeviceName("TEST")
a = RevPiEpics(debug=True, cycletime=200)  # debug and cycletime are optional

ai1 = a.builder("OutputStatus_2_i06")  # The PV name will match PiCtory
ai2 = a.builder("OutputStatus_1_i06", "Out1Status")  # The PV name will be TEST:Out1Status
ai3 = a.builder("InputStatus_1_i06")  # Automatic input type detection
ai3 = a.builder("InputValue_1_i06")
ao1 = a.builder(io_name="OutputValue_2_i06", pv_name="Out2", DESC="Out 1", EGU="mV")  # Configure like with softioc
ao2 = a.builder(io_name="OutputValue_1_i06", pv_name="Out1", DRVL="8000", DRVH=19000)  # Change limits

# Start the IOC
builder.LoadDatabase()
softioc.iocInit()
a.start()  # Start the IO loop

# Keep the IOC running in a shell
softioc.non_interactive_ioc() # or softioc.interactive_ioc(globals())
```

## Supported Modules

- AIO (Analog Input/Output)

Other modules may be supported in the future.

## Dependencies

- pythonSoftIoc
- revpimodio2

## Development

This library is still under development.  
Any help or contributions are welcome!

## Third-party Licenses

This project uses the following third-party components:

- **pythonSoftIOC**  
  License: Apache License 2.0  
  See the `LICENSE_pythonSoftIOC` file for details.

- **revpimodio2**  
  License: GNU Lesser General Public License (LGPL) v2.1  
  See the `LICENSE_revpimodio2` file for details.

## Project License

This project is licensed under the MIT License.

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

See the `LICENSE` file for details.