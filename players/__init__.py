"""Copied from hanabi and stackoverflow.com/questions/67631.  This imports all
players in this directory that are subclassed from Player, this way you can say
`from players import *` or `from players import RandomPlayer`."""

from classes import Player
import importlib
import inspect
import pkgutil
import sys

for finder, name, is_pkg in pkgutil.walk_packages(__path__):
    try: # only fail later if desired players can't be loaded *cough* numpy
        spec = finder.find_spec(name)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # needed for exec_module to work
        spec.loader.exec_module(module)
    except ImportError as err:
        print("Failed to import " + name + " due to error: " + str(err))
        continue

    for name, value in inspect.getmembers(module):
        if name.startswith('__'):
            continue

        if not inspect.isclass(value):
            continue

        # Only add it to exports if Player subclass
        if Player in value.__subclasses__():
            sys.modules[name] = importlib.import_module(name)
