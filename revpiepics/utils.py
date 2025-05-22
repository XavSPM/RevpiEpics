def status_bit_length(value: int) -> int:
    """
    Converts a status value to an integer representing the number
    of significant bits (used as a basic error code).

    Parameters
    ----------
    value : int
        The status word value.

    Returns
    -------
    int
        Number of significant bits.
    """
    return int(value).bit_length()