"""Shared validation of refresh configuration defaults."""


def config_defaults(config):
    if not isinstance(config, dict) or set(config) - {"reports", "defaults"} or not isinstance(config.get("reports"), list):
        raise ValueError("Invalid refresh configuration")
    defaults = config.get("defaults", {})
    if not isinstance(defaults, dict) or set(defaults) - {"archive", "replace"}:
        raise ValueError("Defaults support only archive and replace")
    if "archive" in defaults and (not isinstance(defaults["archive"], str) or not defaults["archive"].strip()):
        raise ValueError("Default archive must be a nonempty path")
    if "replace" in defaults and type(defaults["replace"]) is not bool:
        raise ValueError("Default replace must be true or false")
    return defaults
