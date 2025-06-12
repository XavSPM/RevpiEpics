from enum import IntEnum

class RecordDirection(IntEnum):
    """Direction de synchronisation des enregistrements."""
    INPUT = 1
    OUTPUT = 2


class RecordType(IntEnum):
    """Type d'enregistrement."""
    BINARY = 1
    ANALOG = 2
    STATUS = 3