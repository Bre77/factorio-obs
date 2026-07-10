#!/usr/bin/env python3
"""
splunk-obs bridge — optional sidecar that tails the mod's NDJSON output and
ships it somewhere. Standard library only (no pip installs).

The Factorio mod can only write a file (its Lua sandbox has no network access),
so this process is what turns that file into HEC events or OTLP metrics. If your
Splunk forwarder can just monitor the file directly (see ../splunk/), you don't
need this at all — it's for shipping to a remote HEC endpoint or an OTEL
collector.

Each NDJSON line is Splunk multi-metric shaped, e.g.:
  {"surface":"nauvis","exporter":"iron smelting","wire":"green","network_id":17,
   "metric_name:iron-plate":4200,"metric_name:copper-plate":100}

Dimensions are every non "metric_name:" key; measurements are the rest.

Modes:
  stdout  parse and pretty-print (dry run / validation)
  hec     POST Splunk HEC metric events to <url>/services/collector
  otlp    POST OTLP/HTTP JSON metrics (gauges) to <endpoint>/v1/metrics

Usage:
  bridge.py --file <path> --mode stdout
  bridge.py --file <path> --mode hec  --hec-url https://splunk:8088 --token <HEC_TOKEN> [--index factorio_metrics]
  bridge.py --file <path> --mode otlp --otlp-endpoint http://collector:4318 [--service factorio]
Common:
  --once            process what's there and exit (default: follow/tail)
  --poll 1.0        seconds between polls when following
  --from-start      start at the beginning of the file (default: resume/end)
  --insecure        skip TLS cert verification (HEC self-signed lab certs)
"""
import argparse
import json
import os
import ssl
import sys
import time
import urllib.request

METRIC_PREFIX = "metric_name:"


def split_record(rec):
    """Return (dimensions dict, measures dict) from one parsed NDJSON object."""
    dims, measures = {}, {}
    for k, v in rec.items():
        if k.startswith(METRIC_PREFIX):
            measures[k[len(METRIC_PREFIX):]] = v
        else:
            dims[k] = v
    return dims, measures


# ---------------------------------------------------------------- shippers ---

def ship_stdout(records, args, now):
    for rec in records:
        dims, measures = split_record(rec)
        print(json.dumps({"dimensions": dims, "measures": measures}))
    return len(records)


def _post(url, data, headers, insecure):
    ctx = ssl._create_unverified_context() if insecure else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        return resp.status, resp.read().decode(errors="replace")


def ship_hec(records, args, now):
    # Splunk HEC multi-metric event: fields carries dimensions + metric_name:* keys.
    events = []
    for rec in records:
        fields = dict(rec)
        if args.index:
            # index is an event property, not a field
            pass
        event = {"time": now, "event": "metric", "fields": fields}
        if args.index:
            event["index"] = args.index
        if args.source:
            event["source"] = args.source
        if args.sourcetype:
            event["sourcetype"] = args.sourcetype
        events.append(json.dumps(event))
    body = "\n".join(events).encode()
    url = args.hec_url.rstrip("/") + "/services/collector"
    headers = {"Authorization": "Splunk " + args.token, "Content-Type": "application/json"}
    status, text = _post(url, body, headers, args.insecure)
    if status not in (200, 201):
        raise RuntimeError(f"HEC returned {status}: {text}")
    return len(records)


def ship_otlp(records, args, now):
    # Convert each measurement into an OTLP Gauge with one int data point.
    # Dimensions become data-point attributes. OTLP/HTTP accepts JSON encoding.
    nano = now_ns(now)
    metrics_by_name = {}
    for rec in records:
        dims, measures = split_record(rec)
        attrs = [
            {"key": k, "value": otlp_attr_value(v)}
            for k, v in dims.items()
        ]
        for name, value in measures.items():
            dp = {
                "timeUnixNano": str(nano),
                "asInt": str(int(value)),
                "attributes": attrs,
            }
            metrics_by_name.setdefault(name, []).append(dp)
    metrics = [
        {"name": "factorio.signal." + name, "unit": "1", "gauge": {"dataPoints": dps}}
        for name, dps in metrics_by_name.items()
    ]
    payload = {
        "resourceMetrics": [{
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": args.service}},
            ]},
            "scopeMetrics": [{
                "scope": {"name": "splunk-obs-bridge"},
                "metrics": metrics,
            }],
        }]
    }
    url = args.otlp_endpoint.rstrip("/") + "/v1/metrics"
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    status, text = _post(url, body, headers, args.insecure)
    if status not in (200, 201, 202):
        raise RuntimeError(f"OTLP returned {status}: {text}")
    return sum(len(v) for v in metrics_by_name.values())


def otlp_attr_value(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def now_ns(now):
    return int(now * 1_000_000_000)


SHIPPERS = {"stdout": ship_stdout, "hec": ship_hec, "otlp": ship_otlp}


# ----------------------------------------------------------------- tailing ---

def parse_lines(lines):
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError as e:
            sys.stderr.write(f"skip malformed line: {e}: {ln[:120]}\n")
    return out


def pos_path(file):
    return file + ".pos"


def read_pos(file):
    try:
        with open(pos_path(file)) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def write_pos(file, pos):
    tmp = pos_path(file) + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(str(pos))
    os.replace(tmp, pos_path(file))


def run(args):
    ship = SHIPPERS[args.mode]
    # Initial offset: resume from .pos, else start-of-file or end depending on flag.
    offset = read_pos(args.file)
    if offset is None:
        offset = 0 if args.from_start else _size(args.file)

    total = 0
    while True:
        size = _size(args.file)
        if size < offset:  # file rotated/truncated
            offset = 0
        if size > offset:
            with open(args.file, "rb") as fh:  # binary: byte offsets stay exact
                fh.seek(offset)
                chunk = fh.read()
            nl = chunk.rfind(b"\n")  # only consume through the last complete line
            if nl != -1:
                consumed = chunk[: nl + 1]
                text = consumed.decode("utf-8", "replace")
                records = parse_lines(text.splitlines())
                if records:
                    shipped = ship(records, args, time.time())
                    total += shipped
                    sys.stderr.write(
                        f"[{args.mode}] shipped {shipped} (total {total})\n"
                    )
                offset += len(consumed)
                write_pos(args.file, offset)
        if args.once:
            return
        time.sleep(args.poll)


def _size(file):
    try:
        return os.path.getsize(file)
    except OSError:
        return 0


def main():
    p = argparse.ArgumentParser(description="Tail splunk-obs NDJSON and ship it.")
    p.add_argument("--file", required=True, help="path to the mod's NDJSON output")
    p.add_argument("--mode", choices=list(SHIPPERS), default="stdout")
    p.add_argument("--once", action="store_true", help="process and exit (no follow)")
    p.add_argument("--from-start", action="store_true", help="start at file beginning")
    p.add_argument("--poll", type=float, default=1.0, help="seconds between polls")
    p.add_argument("--insecure", action="store_true", help="skip TLS verification")
    # HEC
    p.add_argument("--hec-url", help="e.g. https://splunk:8088")
    p.add_argument("--token", help="HEC token")
    p.add_argument("--index", help="target metrics index")
    p.add_argument("--source", default="factorio:splunk-obs")
    p.add_argument("--sourcetype", default="factorio:metric")
    # OTLP
    p.add_argument("--otlp-endpoint", help="OTLP/HTTP base, e.g. http://collector:4318")
    p.add_argument("--service", default="factorio", help="service.name resource attr")
    args = p.parse_args()

    if args.mode == "hec" and not (args.hec_url and args.token):
        p.error("--mode hec requires --hec-url and --token")
    if args.mode == "otlp" and not args.otlp_endpoint:
        p.error("--mode otlp requires --otlp-endpoint")

    try:
        run(args)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
