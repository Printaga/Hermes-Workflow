"""Root shim: Hermes loads the plugin directory root, so re-export ``register`` here.

The import must work in two contexts:
  * the host loader executes this file as a package whose ``submodule_search_locations`` is
    the plugin directory (no plugin dir is on ``sys.path``) — hence the relative import;
  * pytest and plain tooling import this directory as a top-level ``__init__`` module, where
    there is no parent package — hence the absolute fallback.
"""
try:  # host loader: this file is ``<plugin pkg>.__init__``
    from .visual_workflow_hermes import register  # noqa: F401
except ImportError:  # imported as a top-level module (tests, `hermes plugins doctor` probe)
    from visual_workflow_hermes import register  # noqa: F401
