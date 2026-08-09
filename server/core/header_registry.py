import os

from tavern_shared.orderable_registry import OrderableRegistry
from tavern_shared.paths import _tavern_data_dir

_registry = OrderableRegistry(os.path.join(_tavern_data_dir(), "server_header_order.json"))


def register_header_button(key, icon_text, command_attr, label=None, built_in=False):
    """command_attr is the name of a method ServerLauncher should call
    when clicked -- the addon is expected to also monkeypatch that
    method onto ServerLauncher itself. built_in=True only affects the
    default order (core buttons first) before a user saves their own.
    """
    _registry.register(key, built_in=built_in, icon_text=icon_text,
                        command_attr=command_attr, label=label or icon_text)


def ordered_buttons():
    return _registry.ordered_items()


def registry():
    return _registry
