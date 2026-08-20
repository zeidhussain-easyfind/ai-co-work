"""
Test configuration for efps-geotag-manager.

Adds the parent module directory to sys.path so that ``geotag_manager``
can be imported directly from the tests package.
"""

import sys
import os

# Add the module root (parent of tests/) to sys.path
MODULE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if MODULE_DIR not in sys.path:
    sys.path.insert(0, MODULE_DIR)
