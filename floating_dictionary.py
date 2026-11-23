#!/usr/bin/env python3
"""Compatibility entry point for existing launchers and integrations."""
import importlib
import sys

module = importlib.import_module('ukijiten')
if __name__ == '__main__':
    sys.exit(module.main())
else:
    sys.modules[__name__] = module
