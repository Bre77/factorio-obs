# Factorio → Splunk circuit-network metrics exporter — Design

Date: 2026-07-10
Status: Approved, building

## Goal

Export Factorio circuit-network signal readings as metrics into Splunk. Primary,
first-class path is a file the Splunk forwarder tails; HEC and OTEL are optional
extras handled by a small sidecar. Target game: Factorio 2.0.77 + Space Age
(forward-compatible with 2.1).

## The hard constraint that shapes everything

Factorio mods run in a locked-down Lua sandbox for multiplayer determinism and
security:

- **No network I/O.** No sockets, no HTTP, no `io`/`os` libraries. A mod cannot
  talk to Splunk HEC or an OTEL collector directly. This is not "hard" — it is
  blocked by design.
- **No wall clock.** No `os.time`. The mod only knows `game.tick`. It cannot
  stamp real epoch time.
- **The one escape hatch** is `helpers.write_file(name, data, append)`, which
  appends to `script-output/<name>` under the Factorio user data directory.

Therefore the architecture is necessarily two pieces: the mod produces a file;
something outside the game ships it. The user's "fallback" file approach is in
fact the mandatory core, and HEC/OTEL become a shipping-mode choice downstream.

## Architecture

```
Factorio (mod, Lua)                     script-output/          bridge / forwarder
─────────────────────                   ──────────────          ──────────────────
Display Panel (named)                   splunk-obs/             (A) Splunk monitor://
  ├ red wire  ─┐                        factorio-metrics          tails file → metrics index
  └ green wire ┤ signals                  .ndjson         ──►   (B) bridge.py --mode hec
               ▼                        (append-only,             tail → Splunk HEC
  every N ticks: read signals,          NDJSON multi-metric)  (C) bridge.py --mode otlp
  group, write one JSON line/group                                tail → OTLP/OTEL collector
```

### Collector = the vanilla Display Panel (no new entity)

Rather than ship a custom entity, the mod reuses Space Age's **Display Panel**:

- It connects to the circuit network (`circuit_red` / `circuit_green`
  connectors), so all signals on the wire(s) are readable.
- The player names it by typing into its text field; that name is the metric's
  `exporter` dimension.
- **Opt-in by naming:** a panel with a non-blank name is exported; a blank panel
  is ignored, so players can use display panels normally without accidentally
  exporting them.

**Where the name actually lives (important discovery during build):**
`LuaEntity.display_panel_text` is the *live rendered* text, which display
conditions blank out on a wired panel — testing confirmed it reads `""` the
moment a wire is attached. The durable name is instead the panel's first
configured **message** — which is exactly what the in-game text field edits. So
the mod reads message text, not `display_panel_text`. The array was renamed
across versions: **2.0 = `control_behavior.messages` / `get_message`**, **2.1 =
`records` / `get_record`**. The mod probes for whichever exists (memoized) so it
survives the 2.0→2.1 upgrade. `display_panel_text` is kept only as a fallback for
the (signal-less, therefore useless) unwired case.

Verified API (2.0 / 2.1):
- `entity.get_control_behavior()` → `LuaDisplayPanelControlBehavior`; its
  `messages`/`records` array holds `DisplayPanelMessageDefinition {text, icon,
  condition}`.
- `entity.get_circuit_network(defines.wire_connector_id.circuit_red|circuit_green)`
  → `LuaCircuitNetwork` or nil.
- `LuaCircuitNetwork.signals` → `array[Signal]` where `Signal = {signal=SignalID, count=int}`,
  `SignalID = {type=string?, name=string, quality=string?}`.
- `LuaCircuitNetwork.network_id` → uint.

## Output format — Splunk multi-metric NDJSON

Leaning hard into multi-metric: **one JSON line per `(surface, exporter, wire,
network_id)`**, with every signal on that wire collapsed into the same line as a
`metric_name:<signal>` measurement:

```json
{"surface":"nauvis","exporter":"iron smelting","wire":"green","network_id":17,"metric_name:iron-plate":4200,"metric_name:copper-plate":100,"metric_name:iron-plate:legendary":40}
```

Dimensions (kept deliberately low-cardinality):
- `surface` — planet or space platform name.
- `exporter` — the panel's name (user free-text, JSON-escaped).
- `wire` — `red` or `green`.
- `network_id` — circuit network id (disambiguates same-named exporters).

Measurements: `metric_name:<signal>`. **Quality is folded into the metric name**
as a suffix (`iron-plate:legendary`); normal quality is bare (`iron-plate`).
**Signal type is not encoded** — cross-type name collisions don't occur in
practice, so keys stay clean. (Type as a prefix + quality as a suffix was
considered and dropped as over-engineering for the target use.)

**No timestamp field.** Every non-`metric_name:` field is a Splunk metric
*dimension*; a per-tick timestamp would have unbounded cardinality and wreck the
metrics index. Splunk assigns `_time` at ingest (real time within ~1s for a live
game); the HEC/OTLP bridge stamps `time.time()` itself.

## The mod

- `info.json` — name `splunk-obs`, `factorio_version` "2.0", depends on base.
- `settings.lua` — runtime-global settings:
  - `splunk-obs-sample-interval` (int, default **60 ticks = 1 s**, min 1).
  - `splunk-obs-filename` (string, default `splunk-obs/factorio-metrics.ndjson`).
- `control.lua`:
  - Registers `on_nth_tick(interval)`; re-registers on setting change / config
    change; re-registers in `on_load` from `storage.interval` (determinism).
  - Each sample: for every surface, `find_entities_filtered{type="display-panel"}`,
    read text, read red+green networks, group, append lines via
    `helpers.write_file(filename, data, append=true)`.
  - JSON is built by a hand-written serializer with proper string escaping
    (exporter text is untrusted free-text). Integer counts only.
  - Remote interface `splunk_obs.sample_now()` and console command
    `/splunk-obs-sample` to force an immediate sample (also used by tests).
- `locale/en/splunk-obs.cfg` — setting titles/descriptions.

Performance: default 1 s cadence; display panels are rare, so the periodic
`find_entities_filtered` scan is cheap. A change-driven registry is noted as a
future optimization.

Multiplayer note: `write_file` with default `for_player` writes on every
machine; only the monitored host's copy matters. Target is single-player / local
host. Documented, not solved, in v1.

## The bridge (optional bonus) — `bridge/bridge.py`

Python 3, **standard library only**. Tails the NDJSON file (with a persisted
byte-offset `.pos` so restarts resume), batches lines, and ships them:

- `--mode stdout` — parse + pretty-print (dry-run / validation).
- `--mode hec` — wrap each flat line into a Splunk HEC metric event
  `{"time":…, "event":"metric", "fields":{…}}` and POST to
  `/services/collector` with `Authorization: Splunk <token>`.
- `--mode otlp` — convert each `metric_name:<name>` into an OTLP Gauge data
  point (dimensions → attributes) and POST OTLP/HTTP **JSON** to
  `<endpoint>/v1/metrics`. JSON encoding avoids a protobuf dependency.

## Splunk file-monitor config — `splunk/`

- `inputs.conf` — `monitor://…/script-output/splunk-obs/*.ndjson`, metrics index.
- `props.conf` — sourcetype `factorio:metric`, `INDEXED_EXTRACTIONS=json`,
  `category=Metrics`, `TIMESTAMP` set to current (index) time.

## Testing

1. **Headless load test** — `factorio --start-server` on a freshly created map
   with the mod enabled; assert the log shows the mod loaded with no Lua errors.
2. **End-to-end via RCON** — a stdlib Python RCON client sends `/silent-command`
   Lua to place a constant combinator + display panel, wire them, set a name and
   signals, then `remote.call('splunk_obs','sample_now')`; assert the NDJSON file
   contains the expected multi-metric line(s) with correct escaping/grouping.

## Build outcome & discoveries

Verified end-to-end on a headless Factorio 2.0.77 + Space Age server, driven over
RCON (constant combinator → wired, named Display Panel → force/auto sample →
assert NDJSON).

- **Naming:** `display_panel_text` blanks out on a wired panel; the name had to
  come from the control behavior's `messages[1].text` (2.0) / `records[1].text`
  (2.1) instead. Resolved above.
- **Scheduler bug (fixed):** the first design stored the interval in
  `storage.interval` and re-read it in `on_load`. `--create` never populated it,
  so `on_load` rescheduled with `nil` and the automatic sampler never ran. Fixed
  by reading `settings.global` directly in `reschedule()` (allowed in `on_load`)
  and dropping the `storage` dependency entirely.
- **Auto-cadence confirmed:** with interval 60, stepping the sim past ticks 60
  and 120 produced exactly 2 auto-written lines — correct 1 s cadence.
- **Headless quirk (test-only):** a server with no players connected barely
  advances ticks, so wall-clock waits don't exercise `on_nth_tick`; the test
  steps ticks via a burst of RCON commands.

## Out of scope (YAGNI for v1)

- Custom entity / graphics.
- Change-driven entity registry (periodic scan is fine at this scale).
- File rotation inside the mod (Splunk/forwarder manages read position; bridge
  can be pointed at a logrotate'd file).
- Server-only write restriction in multiplayer.
```
