"""KiCad discovers and imports this package from its scripting/plugins directory."""
import logging

try:
    import pcbnew
except ImportError:
    pcbnew = None

if pcbnew is not None:
    try:
        from .main import ConnectivityRecoveryPlugin
        ConnectivityRecoveryPlugin().register()
    except Exception:
        logging.getLogger(__name__).exception('Cannot register connectivity recovery plugin')
