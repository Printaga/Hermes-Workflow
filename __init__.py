"""Root shim: Hermes loads the plugin directory root, so re-export ``register`` here.

The import must work in two contexts:
  * the host loader executes this file as a package whose ``submodule_search_locations`` is
    the plugin directory (no plugin dir is on ``sys.path``) — hence the relative import;
  * pytest and plain tooling import this directory as a top-level ``__init__`` module, where
    there is no parent package — hence the absolute fallback.
"""
if __package__:
    # Host loader: this file is ``<plugin pkg>.__init__``, so the relative import is the
    # only correct one. Branching on ``__package__`` (rather than catching ImportError)
    # means an ImportError raised *inside* the package is never masked by a second import
    # of a same-named module somewhere else on sys.path.
    from .visual_workflow_hermes import register  # noqa: F401
else:  # imported as a top-level module (tests, `hermes plugins doctor` probe)
    from visual_workflow_hermes import register  # noqa: F401
