"""
Shopping Browser Adapter Registry.

Maps site names to their ShopperBase implementations.
"""

from .amazon import AmazonShopper

ADAPTERS = {
    "amazon": AmazonShopper,
}

# Lazily imported to avoid requiring all dependencies at startup
_LAZY_ADAPTERS = {
    "newegg": ("adapters.newegg", "NeweggShopper"),
}


def get_adapter(site: str):
    """Get adapter class by site name."""
    if site in ADAPTERS:
        return ADAPTERS[site]
    if site in _LAZY_ADAPTERS:
        module_path, class_name = _LAZY_ADAPTERS[site]
        import importlib
        mod = importlib.import_module(f".{module_path.split('.')[-1]}", package=__package__)
        cls = getattr(mod, class_name)
        ADAPTERS[site] = cls
        return cls
    raise ValueError(f"Unknown site: {site}. Available: {list(ADAPTERS.keys()) + list(_LAZY_ADAPTERS.keys())}")


def list_sites() -> list[str]:
    """List all available site names."""
    return sorted(set(list(ADAPTERS.keys()) + list(_LAZY_ADAPTERS.keys())))
