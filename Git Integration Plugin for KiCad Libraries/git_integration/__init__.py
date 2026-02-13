# -*- coding: utf-8 -*-
"""
Git Integration Plugin for KiCad Libraries
Registers the plugin with KiCad's PCB editor (pcbnew).
"""

try:
    import pcbnew

    from .main import GitIntegrationPlugin

    plugin = GitIntegrationPlugin()
    plugin.register()
except ImportError:
    # Running outside KiCad — skip registration (allows standalone testing)
    pass
except Exception as e:
    import logging
    logging.getLogger("kicad_git_plugin").error("Failed to register plugin: %s", e)
