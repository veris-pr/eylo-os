"""Errors for the `tts` socket."""


class TTSConfigurationError(ValueError):
    """Invalid runtime input; messages must never contain credentials."""


class TTSConnectionClosed(Exception):
    pass


class TTSConnectionFailed(Exception):
    pass
