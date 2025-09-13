CLI Reference
=============

The ``dali`` command-line tool provides a friendly way to inspect and control
your DALI IoT controller. Below are the key commands and examples.

Basics
------
- Base URL: set with ``--url`` or persist via ``dali config controller set-url`` (no default).
- Timeout: set with ``--timeout`` (seconds).
- Use ``--json`` flags where supported to print raw JSON.

Devices
-------
- ``dali devices poll [--json]`` — Poll devices and print reachability, latency, groups, and zones.
- ``dali devices show <id> [--json]`` — Show a device’s JSON payload.
- ``dali devices types [--json]`` — Infer device capabilities from ``daliTypes`` and features.

Scan & Link
-----------
- ``dali scan start [--new-installation] [--no-addressing] [--use-lines N ...]``
- ``dali scan status [--json]`` | ``dali scan cancel`` | ``dali scan wait [--interval S] [--timeout S] [--json]``
- ``dali link enable|disable`` — Toggle linking mode.

Zones
-----
- ``dali zones list`` | ``dali zones info <id> [--json]``
- ``dali zones scenes [--json]`` — Detect present scene numbers in each zone.
- ``dali zones recall <zone> <scene> [--fade S]``
- ``dali zones enumerate <zone> [--delay S] [--start N] [--end N] [--restore]``
- ``dali zones members <id> [--json]``
- ``dali zones on|off <id> [--fade S]``

Sensors
-------
- ``dali sensors list [--json]`` — List available sensors and last values.

Broadcast
---------
- ``dali all-off [--fade S] [--line N]`` — Turn all lights off using broadcast control (optionally restrict to one DALI line).

Automations
-----------
Triggers
^^^^^^^^
- ``dali automations triggers [--json]`` — List trigger actions.
- ``dali automations trigger <id> [--json]`` — Show one trigger action.
- ``dali automations trigger-start <id>`` | ``trigger-stop <id>`` | ``trigger-delete <id>``
- ``dali automations trigger-create [--name ..] [--enabled/--no-enabled] [sources...] [targets...]``
  - Sources: repeat any of ``--src-device N``, ``--src-group N``, ``--src-d16gear L:A``, ``--src-d16group L:A``.
  - Targets: see below.
- ``dali automations trigger-update <id> [--name ..] [--enabled/--no-enabled] [sources...] [targets...]``

Sequences
^^^^^^^^^
- ``dali automations sequences [--json]`` — List sequences.
- ``dali automations sequence <id> [--json]`` — Show one sequence (steps table).
- ``dali automations sequence-start <id>`` | ``sequence-stop <id>``
- ``dali automations sequence-create [--name ..] [--loop] [--repeat N] [--enabled/--no-enabled]``
  - Provide exactly one: ``--steps-json file`` OR one of ``--on|--off|--scene N`` with optional ``--delay S`` and [targets...].
- ``dali automations sequence-update <id> [--name ..] [--loop/--no-loop] [--repeat N] [--enabled/--no-enabled]``
  - Replace steps with ``--steps-json file`` OR one of ``--on|--off|--scene N`` plus [targets...].
- ``dali automations sequence-delete <id>``

Schedules
^^^^^^^^^
- ``dali automations schedules [--json]`` — List schedules.
- ``dali automations schedule <id> [--json]`` — Show one schedule.
- ``dali automations schedule-start <id>`` | ``schedule-stop <id>`` | ``schedule-delete <id>``
- ``dali automations schedule-add-dusk [--offset-min N] [targets...]`` — Turn ON at sunset offset.
  - Targets: repeat ``--device N``, ``--zone N``, ``--group N``.
- ``dali automations schedule-add-off (--time HH:MM | --before-sunrise N | --after-sunrise N) [targets...]`` — Turn OFF at time or sunrise offset.

Circadians
^^^^^^^^^^
- ``dali automations circadians [--json]`` — List circadian automations.
- ``dali automations circadian <id> [--json]`` — Show details for one circadian.
- ``dali automations circadian-start <id>`` | ``circadian-stop <id>`` | ``circadian-delete <id>``
- ``dali automations circadian-create [--name ..] [--enabled/--no-enabled] [targets...] --longest-json file --shortest-json file``
- ``dali automations circadian-update <id> [--name ..] [--enabled/--no-enabled] [targets...] [--longest-json file] [--shortest-json file]``

Status Queries
^^^^^^^^^^^^^^
- ``dali automations status-queries list [--json]`` — List configs by line.
- ``dali automations status-queries bounds [--json]`` — Show min/max allowed delay.
- ``dali automations status-queries get <line> [--json]`` — Get config for one line.
- ``dali automations status-queries set <line> [--delay N] [--status/--no-status] [--actual-level/--no-actual-level]``
- ``dali automations status-queries delete <line>`` — Remove config for a line.

Config
------
- ``dali config location get|set|detect`` — Manage controller location (lat/lon).
- ``dali config time get|set|timezones`` — Manage time settings and timezone.

Targets Helper
--------------
Many automation commands accept repeated target options:
- ``--device N`` — Target a specific device ID.
- ``--zone N`` — Target a virtual zone ID.
- ``--group N`` — Target a DALI group ID.
- ``--broadcast`` — Target all devices.

OpenAPI Alignment
-----------------
The CLI aligns with the controller’s OpenAPI schema (see the API section). In particular:
- Schedule recall modes: ``timeOfDay``, ``beforeSunrise``, ``afterSunrise``, ``beforeSunset``, ``afterSunset``.
- Schedule time uses ``{hour, minute, second}``.
- Targets follow ``DeviceModel``: ``{"type": "device|group|zone|broadcast", "id": N}``.
