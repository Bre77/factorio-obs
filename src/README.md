# Circuit Logger for Splunk (`circuit-logger`)

A Factorio 2.0/2.1 (Space Age) mod that exports **circuit-network signals as JSON
events**. It reads the signals wired into any **named Display Panel** and writes
one NDJSON event per panel into `script-output/`, where a Splunk file monitor can
pick them up.

## Why it works this way

Factorio mods run in a locked-down Lua sandbox: **no network access and no wall
clock**. A mod cannot talk to Splunk HEC directly — the only sanctioned output is
`helpers.write_file`. So this mod produces a file, and shipping it to Splunk is
done outside the game with a Splunk file monitor. See the repo root README for
the full picture.

## Usage in-game

1. Build a **Display Panel** (Space Age).
2. Wire the circuit network(s) you care about into it (red and/or green).
3. **Type a name into the panel's text field** — this becomes the `exporter`
   dimension (e.g. `iron smelting`, `mall`, `power`). A blank panel is ignored,
   so naming a panel is how you opt it in.
4. That's it. Every second (configurable) the mod appends one event per panel to
   the current session's file, e.g. `script-output/circuit-logger/factorio-1.ndjson`.

Place as many named panels as you like, across any surface (planets and space
platforms). Each panel emits one event containing all of its wires.

## Output format

One JSON event per named panel per sample. Signals are a nested tree
`wire.<color>.<item_type>.<item_name>[.<quality>] = value`:

```json
{"surface":"nauvis","exporter":"iron smelting","wire":{"green":{"network_id":17,"item":{"iron-plate":{"normal":4200,"legendary":40},"copper-plate":{"normal":100}},"fluid":{"water":5000}}}}
```

- Top level: `surface`, `exporter`.
- `wire.<red|green>.network_id` — red and green are always different networks.
- `wire.<red|green>.<item_type>.<name>` — the value; for **item** signals it is
  nested one level deeper by **quality** (`{"normal":…,"legendary":…}`). Quality
  is omitted for non-item signals (fluids, virtuals), which sit directly under
  their name.

## Files: one per session

Each game session writes its own file. The output filename is a template with a
`{session}` placeholder, replaced by a per-load counter (there is no wall clock
in the sandbox, so no real epoch is possible — the counter is the stable
alternative). Remove `{session}` from the setting to use a single rolling file.

## Settings (Mod settings → Map)

| Setting | Default | Meaning |
|---|---|---|
| Sample interval (ticks) | `60` | 60 ticks = 1 second at normal speed. |
| Output file | `circuit-logger/factorio-{session}.ndjson` | Relative to `script-output/`; `{session}` → per-load counter. |

## Manual trigger

- Console: `/circuit-logger-sample`
- Script/remote: `remote.call("circuit_logger", "sample_now")` → returns lines written.

## Notes & limits

- **Timestamps:** the mod emits no time field (no wall clock in the sandbox);
  Splunk stamps `_time` at ingest (real-time within ~1s for a live game).
- **Multiplayer:** `write_file` writes on every connected machine; monitor the
  host's copy. Designed for single-player / a local host.
- **Naming under the hood:** on a wired panel the live `display_panel_text` is
  blanked by display conditions, so the name is read from the panel's configured
  message (`messages`/`records`) — which is exactly what its text field edits.
- **File growth:** each session file is append-only. A Splunk forwarder tails it
  fine; delete old session files yourself to reclaim disk.
