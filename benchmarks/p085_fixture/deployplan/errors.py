class ManifestError(ValueError):
    """A stable, machine-readable manifest failure."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(self.__str__())

    def __str__(self) -> str:
        return f"{self.code}@{self.path}: {self.message}"
