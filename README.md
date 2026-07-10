# factorio-obs

Send Factorio **circuit-network readings to Splunk as JSON events** — via a
Splunk file monitor, or pushed to Splunk HEC.

```
 Factorio (Lua mod)                script-output/                shipping
 ─────────────────────            ────────────────              ─────────────────────────
 Display Panel (named)            splunk-obs/                   (A) Splunk monitor://   ← first-class
   ├ red / green wires    ──►     factorio-1.ndjson        ──►      tails the files → events index
   └ signals read each 1s         factorio-2.ndjson             (B) bridge.py --mode hec
                                   (one JSON event / panel,          tail → Splunk HEC (events)
                                    new file per session)
```

## The one thing to understand

Factorio mods **cannot do network I/O** — the Lua sandbox has no sockets, no
HTTP, no `os`/`io`. They also have **no wall clock** (so no timestamps and no
real epoch — a per-session counter names the files instead). The only output a
mod has is `helpers.write_file`. So this project is deliberately two halves:

1. **The mod** (`splunk-obs/`) reads circuit signals and writes JSON events.
2. **A shipper** moves those events to Splunk. The simplest is just a Splunk file
   monitor — no extra process at all.

## Layout

| Path | What |
|---|---|
| `splunk-obs/` | The Factorio mod. See its README for in-game usage. |
| `splunk/` | `inputs.conf` / `props.conf` for the **file-monitor** path (first-class). |
| `bridge/bridge.py` | Optional stdlib-only sidecar: tails the NDJSON → **HEC** (events). |
| `docs/plans/` | Design doc. |

## Quick start (file monitor — recommended)

1. Install the mod: symlink or copy `splunk-obs/` into your Factorio `mods/`
   folder (the folder name must stay `splunk-obs`), and enable it.
2. In-game: build a Display Panel, wire signals into it, and type a name in its
   text field.
3. Point Splunk at the output — see [`splunk/README.md`](splunk/README.md).

## Quick start (bridge → HEC)

The mod still writes the file; the bridge ships it. No dependencies beyond
Python 3.

```bash
# dry-run: see what it parses
python3 bridge/bridge.py \
  --file "$HOME/Library/Application Support/factorio/script-output/splunk-obs/factorio-1.ndjson" \
  --mode stdout

# Splunk HEC (events)
python3 bridge/bridge.py --file <ndjson> --mode hec \
  --hec-url https://splunk:8088 --token <HEC_TOKEN> --index factorio
```

It tails the file (resuming via a `.pos` sidecar), batches complete lines, and
ships them. `--once` processes and exits; `--from-start` reads existing content.

## Output format

One JSON event per named panel per sample. Signals are a nested tree
`wire.<color>.<item_type>.<item_name>[.<quality>] = value`:

```json
{"surface":"nauvis","exporter":"iron smelting","wire":{"green":{"network_id":17,"item":{"iron-plate":{"normal":4200,"legendary":40}},"fluid":{"water":5000}}}}
```

Top level: `surface`, `exporter`. Each `wire.<color>` has its own `network_id`
(red and green are distinct networks). Item signals nest by quality; non-item
signals (fluids, virtuals) sit directly under their name.

## Status

Verified end-to-end against **Factorio 2.0.77 + Space Age** on a headless server:
the mod loads clean, reads a wired+named Display Panel (items with quality nested,
a fluid via a storage tank), and both the automatic 1-second scheduler and the
manual trigger produce the correct nested JSON event. Per-session file naming was
confirmed across a save+reload (`factorio-1` → `factorio-2`). The bridge's
stdout/HEC output is validated. Forward-compatible with 2.1 (handles the
`messages`→`records` API rename).

## License

MIT — see [LICENSE](LICENSE).
