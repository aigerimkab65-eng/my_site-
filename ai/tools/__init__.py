from ai.tools.catalog import register_catalog_tools
from ai.tools.leads import register_lead_tools


def register_builtin_tools(registry, *, create_order=None):
    register_catalog_tools(registry)
    register_lead_tools(registry, create_order=create_order)
