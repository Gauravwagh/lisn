"""Exception hierarchy for lisn. Every user-facing failure maps to one of these."""


class LisnError(Exception):
    """Base class for all lisn errors. The message is safe to show to the user."""


class ExtractionError(LisnError):
    """A source (file, URL, clipboard, stdin) could not be turned into text."""


class UnsupportedSourceError(ExtractionError):
    """No extractor knows how to handle the given source."""


class EngineError(LisnError):
    """A TTS engine failed to load or synthesize."""


class EngineUnavailableError(EngineError):
    """The requested engine's dependencies are not installed."""


class ConfigError(LisnError):
    """The user configuration is invalid."""


class PlaybackError(LisnError):
    """The audio output device could not be opened or driven."""
