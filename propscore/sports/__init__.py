"""Sport adapters. Add a new sport by implementing sports/<name>.py and registering it here."""

from .nba import NBA

SPORTS = {
    "nba": NBA,
}


def get_sport(name: str, client=None):
    key = name.lower().strip()
    try:
        cls = SPORTS[key]
    except KeyError:
        known = ", ".join(sorted(SPORTS))
        raise SystemExit(f"Unknown sport {name!r}. Built so far: {known}.")
    return cls(client) if client is not None else cls
