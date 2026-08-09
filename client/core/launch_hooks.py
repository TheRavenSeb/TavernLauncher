"""
Extension point for addons that need to run something after a successful
auth handshake but before the game process actually launches -- e.g.
custom_models needs to sync asset bundles down at exactly this point.
Core's _do_launch calls run_post_auth_hooks() once, unconditionally;
it never needs to know which (if any) addons registered a hook.
"""

_hooks = []


def register_post_auth_hook(fn):
    """fn(host, log_fn) is called once per launch, right after
    "Welcomed as <username>" and before the game subprocess starts."""
    _hooks.append(fn)


def run_post_auth_hooks(host, log_fn):
    for fn in _hooks:
        fn(host, log_fn)
