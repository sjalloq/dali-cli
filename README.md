# DALI CLI

CLI for the Lunatone DALI IoT controller: inspect devices, run scans, control zones, and manage automations (triggers, sequences, schedules, circadians).

## Install (editable)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Quick start
```bash
# Poll devices and show a table (pass --url once or store it in config)
dali --url http://10.0.0.239 devices poll

# JSON output
dali devices poll --json > devices.json
```

## Common commands

- Devices
  - `dali devices poll [--json]`
  - `dali devices show <id> [--json]`
  - `dali devices types [--json]`

- Scan & Link
  - `dali scan start [--new-installation] [--no-addressing] [--use-lines N ...]`
  - `dali scan status [--json]` | `dali scan cancel` | `dali scan wait [--interval S] [--timeout S] [--json]`
  - `dali link enable|disable`
  - `dali all-off [--fade S] [--line N]` — broadcast OFF across all devices (optionally a single line)

- Zones
  - `dali zones list` | `dali zones info <id> [--json]`
  - `dali zones scenes [--json]` | `dali zones recall <zone> <scene> [--fade S]`
  - `dali zones enumerate <zone> [--delay S] [--start N] [--end N] [--restore]`
  - `dali zones members <id> [--json]`
  - `dali zones on|off <id> [--fade S]`

- Sensors
  - `dali sensors list [--json]`

## Automations

Targets flags (repeatable): `--device N`, `--zone N`, `--group N`, `--broadcast`.

- Triggers
  - `dali automations triggers [--json]`
  - `dali automations trigger <id> [--json]`
  - `dali automations trigger-start|trigger-stop|trigger-delete <id>`
  - `dali automations trigger-create [--name ..] [--enabled/--no-enabled] [sources...] [targets...]`
    - Sources: `--src-device N`, `--src-group N`, `--src-d16gear L:A`, `--src-d16group L:A`
  - `dali automations trigger-update <id> [--name ..] [--enabled/--no-enabled] [sources...] [targets...]`

- Sequences
  - `dali automations sequences [--json]`
  - `dali automations sequence <id> [--json]`
  - `dali automations sequence-start|sequence-stop <id>`
  - `dali automations sequence-create [--name ..] [--loop] [--repeat N] [--enabled/--no-enabled]` and either:
    - `--steps-json file` (full steps), or
    - one of `--on|--off|--scene N` plus targets and optional `--delay S`
  - `dali automations sequence-update <id> [...]` (same step options as create)
  - `dali automations sequence-delete <id>`

- Schedules
  - `dali automations schedules [--json]`
  - `dali automations schedule <id> [--json]`
  - `dali automations schedule-start|schedule-stop|schedule-delete <id>`
  - Helpers:
    - `dali automations schedule-add-dusk [--offset-min N] [targets...]` (ON at sunset offset)
    - `dali automations schedule-add-off (--time HH:MM | --before-sunrise N | --after-sunrise N) [targets...]` (OFF)
  - Recall modes per API: `timeOfDay`, `beforeSunrise`, `afterSunrise`, `beforeSunset`, `afterSunset`.

- Circadians
  - `dali automations circadians [--json]`
  - `dali automations circadian <id> [--json]`
  - `dali automations circadian-start|circadian-stop|circadian-delete <id>`
  - `dali automations circadian-create [--name ..] [--enabled/--no-enabled] [targets...] --longest-json file --shortest-json file`
  - `dali automations circadian-update <id> [--name ..] [--enabled/--no-enabled] [targets...] [--longest-json file] [--shortest-json file]`

- Status Queries
  - `dali automations status-queries list [--json]`
  - `dali automations status-queries bounds [--json]`
  - `dali automations status-queries get <line> [--json]`
  - `dali automations status-queries set <line> [--delay N] [--status/--no-status] [--actual-level/--no-actual-level]`
  - `dali automations status-queries delete <line>`

## Docs

Sphinx docs include an OpenAPI-rendered reference and a CLI guide.

```bash
pip install -r docs/requirements.txt
make -C docs html
# open docs/build/html/index.html
```

## Persistent config

You can store the controller URL in a config file so you don’t need to pass `--url` every time. There is no default URL.

```bash
# Save the controller URL
dali config controller set-url http://10.0.0.239

# Show the resolved URL and where it came from (arg|config)
dali config controller get-url

# Precedence used by the CLI when creating a client:
#   --url arg > config (~/.config/dali-cli/config.toml)
# If neither is provided, the CLI will exit with an error prompting you to set the URL.
```
