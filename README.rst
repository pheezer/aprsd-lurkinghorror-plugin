Infocom's Lurking Horror over APRS
==================================

|PyPI| |Status| |Python Version| |License|

|Read the Docs| |Tests| |Codecov|

|pre-commit|

.. |PyPI| image:: https://img.shields.io/pypi/v/aprsd-lurkinghorror-plugin.svg
   :target: https://pypi.org/project/aprsd-lurkinghorror-plugin/
   :alt: PyPI
.. |Status| image:: https://img.shields.io/pypi/status/aprsd-lurkinghorror-plugin.svg
   :target: https://pypi.org/project/aprsd-lurkinghorror-plugin/
   :alt: Status
.. |Python Version| image:: https://img.shields.io/pypi/pyversions/aprsd-lurkinghorror-plugin
   :target: https://pypi.org/project/aprsd-lurkinghorror-plugin
   :alt: Python Version
.. |License| image:: https://img.shields.io/pypi/l/aprsd-lurkinghorror-plugin
   :target: https://opensource.org/licenses/GNU GPL v3.0
   :alt: License
.. |Read the Docs| image:: https://img.shields.io/readthedocs/aprsd-lurkinghorror-plugin/latest.svg?label=Read%20the%20Docs
   :target: https://aprsd-lurkinghorror-plugin.readthedocs.io/
   :alt: Read the documentation at https://aprsd-lurkinghorror-plugin.readthedocs.io/
.. |Tests| image:: https://github.com/pheezer/aprsd-lurkinghorror-plugin/workflows/Tests/badge.svg
   :target: https://github.com/pheezer/aprsd-lurkinghorror-plugin/actions?workflow=Tests
   :alt: Tests
.. |Codecov| image:: https://codecov.io/gh/pheezer/aprsd-lurkinghorror-plugin/branch/main/graph/badge.svg
   :target: https://codecov.io/gh/pheezer/aprsd-lurkinghorror-plugin
   :alt: Codecov
.. |pre-commit| image:: https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white
   :target: https://github.com/pre-commit/pre-commit
   :alt: pre-commit


Features
--------

* Play an Infocom-style Z-machine text adventure (Zork, The Lurking Horror,
  etc.) over APRS radio messages.
* Each APRS callsign gets its own independent, persistent game. State is saved
  after every turn and survives an APRSD restart.
* A pure-Python Z-machine interpreter (vendored from ravdin/zmachine_, MIT) is
  bundled -- there is **no external interpreter binary to install**.
* Long room descriptions are split into multiple <=67 character APRS messages,
  capped so the plugin never floods the channel.
* Idle games are expired automatically after a configurable timeout.


Requirements
------------

* Python 3.11+
* aprsd_ 3.4.4+
* A Z-machine story file (``.z3``/``.z5``/``.dat``) that you supply yourself
  (see **The story file** below). Z-machine versions 3-5 are supported.


Installation
------------

You can install *Infocom's Lurking Horror over APRS* via pip_ from PyPI_:

.. code:: console

   $ pip install aprsd-lurkinghorror-plugin


The story file
--------------

This plugin is a generic Z-machine player; it does **not** ship a game. Infocom
story files are copyrighted and are not redistributable, so you must supply your
own legally-obtained copy and point the plugin at it with the ``story_file``
setting below. The plugin disables itself if the file is missing.


Configuration
-------------

Enable the plugin by adding its full class path to ``enabled_plugins`` in your
APRSD config, then configure the ``[lurking_horror]`` group:

.. code:: ini

   [DEFAULT]
   enabled_plugins = aprsd_lurkinghorror_plugin.aprsd_lurkinghorror_plugin.LurkingHorrorPlugin

   [lurking_horror]
   # Absolute path to your Z-machine story file (required).
   story_file = /home/pi/games/lurkinghorror.z3
   # Prefix players must type before every game command (default: #).
   command_prefix = #
   # Max APRS messages (<=67 chars each) per turn (default: 4).
   max_reply_messages = 4
   # Seconds allowed for one turn before giving up (default: 10).
   turn_timeout = 10
   # Expire a player's game after this many idle seconds; 0 = never (default: 86400).
   session_idle_timeout = 86400


Usage
-----

Players send APRS messages to your station's callsign, prefixing every game
command with ``command_prefix`` (``#`` by default)::

   #                -> start a new game (or, if one exists, show the current room)
   # go north       -> send "go north" to the game
   # take all       -> send "take all" to the game
   # look           -> re-describe the current room
   # restart        -> abandon the current game and start over
   # help           -> short usage reminder

The prefix exists so ordinary words like "take" or "west" never collide with
other APRSD command plugins.


Contributing
------------

Contributions are very welcome.
To learn more, see the `Contributor Guide`_.


License
-------

Distributed under the terms of the `GNU GPL v3.0 license`_,
*Infocom's Lurking Horror over APRS* is free and open source software.


Issues
------

If you encounter any problems,
please `file an issue`_ along with a detailed description.


Credits
-------

This project was generated from `@hemna`_'s `APRSD Plugin Python Cookiecutter`_ template.

The bundled Z-machine interpreter is a vendored copy of ravdin/zmachine_ (MIT),
in ``aprsd_lurkinghorror_plugin/_vendor/zmachine/``. Its license is preserved at
``aprsd_lurkinghorror_plugin/_vendor/ZMACHINE_LICENSE``.

.. _@hemna: https://github.com/hemna
.. _aprsd: https://github.com/craigerl/aprsd
.. _ravdin/zmachine: https://github.com/ravdin/zmachine
.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _GNU GPL v3.0 license: https://opensource.org/licenses/GNU GPL v3.0
.. _PyPI: https://pypi.org/
.. _APRSD Plugin Python Cookiecutter: https://github.com/hemna/cookiecutter-aprsd-plugin
.. _file an issue: https://github.com/pheezer/aprsd-lurkinghorror-plugin/issues
.. _pip: https://pip.pypa.io/
.. github-only
.. _Contributor Guide: CONTRIBUTING.rst
.. _Usage: https://aprsd-lurkinghorror-plugin.readthedocs.io/en/latest/usage.html
