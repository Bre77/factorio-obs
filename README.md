# factorio-obs

Send Factorio **circuit-network readings to Splunk as metrics** — via a Splunk
file monitor, Splunk HEC, or as OTLP to an OTEL collector.

```
 Factorio (Lua mod)                script-output/                shipping
 ─────────────────────            ────────────────              ─────────────────────────
 Display Panel (named)            splunk-obs/                   (A) Splunk monitor://   ← first-class
   ├ red / green wires    ──►     factorio-metrics.ndjson  ──►      tails the file → metrics index
   └ signals read each 1s         (append-only NDJSON,          (B) bridge.py --mode hec
                                    multi-metric JSON)               tail → Splunk HEC
                                                                 (C) bridge.py --mode otlp
                                                                     tail → OTLP/OTEL collector
```

## The one thing to understand

Factorio mods **cannot do network I/O** — the Lua sandbox has no sockets, no
HTTP, no `os`/`io`. They also have **no wall clock**. The only output a mod has
is `helpers.write_file`. So this project is deliberately two halves:

1. **The mod** (`splunk-obs/`) reads circuit signals and writes a file.
2. **A shipper** moves that file's contents to Splunk/OTEL. The file itself is
   Splunk-metrics-native, so the simplest shipper is just a Splunk file monitor
   — no extra process at all.

## Layout

| Path | What |
|---|---|
| `splunk-obs/` | The Factorio mod. See its README for in-game usage. |
| `splunk/` | `inputs.conf` / `props.conf` for the **file-monitor** path (first-class). |
| `bridge/bridge.py` | Optional stdlib-only sidecar: tails the NDJSON → **HEC** or **OTLP**. |
| `docs/plans/` | Design doc. |

## Quick start (file monitor — recommended)

1. Install the mod: symlink or copy `splunk-obs/` into your Factorio `mods/`
   folder (the folder name must stay `splunk-obs`), and enable it.
2. In-game: build a Display Panel, wire signals into it, and type a name in its
   text field.
3. Point Splunk at the output — see [`splunk/README.md`](splunk/README.md).

## Quick start (bridge → HEC or OTEL)

The mod still writes the file; the bridge ships it. No dependencies beyond
Python 3.

```bash
# dry-run: see what it parses
python3 bridge/bridge.py \
  --file "$HOME/Library/Application Support/factorio/script-output/splunk-obs/factorio-metrics.ndjson" \
  --mode stdout

# Splunk HEC
python3 bridge/bridge.py --file <ndjson> --mode hec \
  --hec-url https://splunk:8088 --token <HEC_TOKEN> --index factorio_metrics

# OTLP / "in-game OTEL collector"
python3 bridge/bridge.py --file <ndjson> --mode otlp \
  --otlp-endpoint http://collector:4318 --service factorio
```

It tails the file (resuming via a `.pos` sidecar), batches complete lines, and
ships them. `--once` processes and exits; `--from-start` reads existing content.

## Output format

One JSON line per `(surface, exporter, wire, network_id)`, Splunk multi-metric:

```json
{"surface":"nauvis","exporter":"iron smelting","wire":"green","network_id":17,"metric_name:iron-plate":4200,"metric_name:copper-plate":100}
```

Dimensions: `surface`, `exporter`, `wire`, `network_id`. Measurements:
`metric_name:<signal>` (quality above normal appended as `:<quality>`).

## Status

Verified end-to-end against **Factorio 2.0.77 + Space Age** on a headless server:
the mod loads clean, reads a wired+named Display Panel, and both the automatic
1-second scheduler and the manual trigger produce correct multi-metric NDJSON.
The bridge's stdout/HEC/OTLP payloads are validated. Forward-compatible with 2.1
(handles the `messages`→`records` API rename).

## License

MIT — see [LICENSE](LICENSE).
