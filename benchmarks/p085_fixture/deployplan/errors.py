class ManifestError(ValueError):
    """A stable, machine-readable manifest failure."""

    def __init__(self, code: str, path: str, message: str) -> None:
        raise NotImplementedError
