"""Errors raised while turning a RigSpec into a Skeleton."""


class BuildError(ValueError):
    """The spec cannot be built into a skeleton. The message says why, for the repair loop."""
