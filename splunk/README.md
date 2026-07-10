# Splunk ingestion

The mod writes Splunk multi-metric NDJSON to Factorio's `script-output/splunk-obs/`.
This is the **first-class, no-extra-process** path: point Splunk at the file.

## 1. Create a metrics index

```
# indexes.conf
[factorio_metrics]
datatype = metric
homePath   = $SPLUNK_DB/factorio_metrics/db
coldPath   = $SPLUNK_DB/factorio_metrics/colddb
thawedPath = $SPLUNK_DB/factorio_metrics/thaweddb
```

Or in Splunk Web: **Settings → Indexes → New Index**, Index Data Type = **Metrics**,
name `factorio_metrics`.

## 2. Install the sourcetype and input

Copy `props.conf` and `inputs.conf` into `$SPLUNK_HOME/etc/system/local/` (or
your own app's `local/`), **edit the monitor path in `inputs.conf`** to match
your OS, and restart Splunk / the forwarder.

- If Splunk runs on the same machine as the game, that's all you need.
- If not, run a **Universal Forwarder** on the game machine with these same two
  files, forwarding to your indexer.

## 3. Verify

```spl
| mcatalog values(metric_name) WHERE index=factorio_metrics
```

```spl
| mstats avg(_value) WHERE index=factorio_metrics AND metric_name="iron-plate"
    BY exporter, surface span=10s
```

Dimensions available for filtering / `BY`: `exporter`, `surface`, `wire`,
`network_id`. Metric names are the signal names, with a `:<quality>` suffix for
anything above normal (e.g. `iron-plate:legendary`).

## Alternative: don't use a file monitor

If you'd rather push to a remote HEC endpoint or an OTEL collector, skip all of
the above and use `../bridge/bridge.py` — see the top-level README.
