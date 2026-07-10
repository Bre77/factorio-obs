# Splunk ingestion

The mod writes JSON events to Factorio's `script-output/splunk-obs/`, one file
per game session (`factorio-1.ndjson`, `factorio-2.ndjson`, …). This is the
first-class, no-extra-process path: point Splunk at the files.

## 1. Create an events index

In Splunk Web: **Settings → Indexes → New Index**, type **Events**, name
`factorio` (or reuse an existing index and change `index=` in `inputs.conf`).

## 2. Install the sourcetype and input

Copy `props.conf` and `inputs.conf` into `$SPLUNK_HOME/etc/system/local/` (or
your own app's `local/`), **edit the monitor path in `inputs.conf`** to match
your OS, and restart Splunk / the forwarder.

- If Splunk runs on the same machine as the game, that's all you need.
- If not, run a **Universal Forwarder** on the game machine with these same two
  files, forwarding to your indexer.

## 3. Search

Each event is a nested tree. Use dotted paths / `spath`:

```spl
index=factorio
| spath path=wire.green.item.iron-plate.normal output=iron
| timechart span=1m avg(iron) by exporter
```

```spl
index=factorio exporter="power"
| spath path=wire.red.virtual.signal-A output=v
| timechart max(v)
```

Top-level fields: `surface`, `exporter`. Then `wire.<red|green>.network_id` and
`wire.<red|green>.<item_type>.<name>[.<quality>]` — quality is nested only for
`item` signals; fluids/virtuals sit directly under their name.

## Alternative: push instead of monitor

To push to a remote Splunk HEC endpoint, use `../bridge/bridge.py --mode hec`
(sends each line as a HEC event). See the top-level README.
