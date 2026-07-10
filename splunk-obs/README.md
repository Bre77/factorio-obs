# Splunk Observability Exporter (`splunk-obs`)

A Factorio 2.0/2.1 (Space Age) mod that exports **circuit-network signals as
metrics**. It reads the signals wired into any **named Display Panel** and writes
them as [Splunk multi-metric](https://docs.splunk.com/Documentation/Splunk/latest/Metrics/GetMetricsInOther)
NDJSON into `script-output/`, where Splunk (or the included bridge) can pick them
up.

## Why it works this way

Factorio mods run in a locked-down Lua sandbox: **no network access and no wall
clock**. A mod cannot talk to Splunk HEC or an OTEL collector directly — the only
sanctioned output is `helpers.write_file`. So this mod produces a file, and
shipping it to Splunk/OTEL is done outside the game (a Splunk file monitor, or
the `bridge/` sidecar). See the repo root README for the full picture.

## Usage in-game

1. Build a **Display Panel** (Space Age).
2. Wire the circuit network(s) you care about into it (red and/or green).
3. **Type a name into the panel's text field** — this becomes the `exporter`
   dimension (e.g. `iron smelting`, `mall`, `power`). A blank panel is ignored,
   so naming a panel is how you opt it in.
4. That's it. Every second (configurable) the mod appends the panel's signals to
   `script-output/splunk-obs/factorio-metrics.ndjson`.

Place as many named panels as you like, across any surface (planets and space
platforms). Each panel's red and green networks are reported separately.

## Output format

One line per `(surface, exporter, wire, network_id)`:

```json
{"surface":"nauvis","exporter":"iron smelting","wire":"green","network_id":17,"metric_name:iron-plate":4200,"metric_name:copper-plate":100,"metric_name:iron-plate:legendary":40}
```

- **Dimensions:** `surface`, `exporter`, `wire` (`red`/`green`), `network_id`.
- **Measurements:** `metric_name:<signal>` — the signal name, with a `:<quality>`
  suffix for anything above normal quality.

## Settings (Mod settings → Map)

| Setting | Default | Meaning |
|---|---|---|
| Sample interval (ticks) | `60` | 60 ticks = 1 second at normal speed. |
| Output file | `splunk-obs/factorio-metrics.ndjson` | Relative to `script-output/`. |

## Manual trigger

- Console: `/splunk-obs-sample`
- Script/remote: `remote.call("splunk_obs", "sample_now")` → returns lines written.

## Notes & limits

- **Timestamps:** the mod emits no time field (no wall clock in the sandbox);
  Splunk stamps `_time` at ingest (real-time within ~1s for a live game). The
  bridge's HEC mode stamps time itself.
- **Multiplayer:** `write_file` writes on every connected machine; monitor the
  host's copy. Designed for single-player / a local host.
- **Naming under the hood:** on a wired panel the live `display_panel_text` is
  blanked by display conditions, so the name is read from the panel's configured
  message (`messages`/`records`) — which is exactly what its text field edits.
- **File growth:** the NDJSON file is append-only. A Splunk forwarder tails it
  fine; rotate/truncate it yourself if you want to reclaim disk.
