from enum import IntEnum

class RecordDirection(IntEnum):
    """Direction of record synchronization between EPICS and RevPi.
    
    Defines the data flow direction for PV-IO synchronization:
    - INPUT: Data flows from RevPi IO to EPICS PV (read-only PV)
    - OUTPUT: Data flows from EPICS PV to RevPi IO (writable PV)
    """
    INPUT = 1   # RevPi IO → EPICS PV (read from hardware)
    OUTPUT = 2  # EPICS PV → RevPi IO (write to hardware)


class RecordType(IntEnum):
    """Type of EPICS record to create for RevPi IO points.
    
    Defines the data type and record structure:
    - BINARY: Boolean/digital values (bi/bo records)
    - ANALOG: Numeric values (ai/ao records)  
    - STATUS: Status/diagnostic information (often multi-bit)
    """
    BINARY = 1  # Digital I/O (0/1, True/False)
    ANALOG = 2  # Numeric values (integers, floats)
    STATUS = 3  # Status words, error codes, multi-bit fields