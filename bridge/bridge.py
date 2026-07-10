#!/usr/bin/env python3
"""
splunk-obs bridge — optional sidecar that tails the mod's NDJSON output and
ships it somewhere. Standard library only (no pip installs).

The Factorio mod can only write a file (its Lua sandbox has no network access),
so this process is what pushes those events to a remote Splunk HEC endpoint. If
your Splunk forwarder can monitor the file directly (see ../splunk/), you don't
need this at all.

Each NDJSON line is one JSON event, e.g.:
  {"surface":"nauvis","exporter":"iron smelting",
   "wire":{"green":{"network_id":17,
     "item":{"iron-plate":{"normal":4200,"uncommon":7}},
     "fluid":{"water":5000}}}}

Modes:
  stdout  parse and pretty-print (dry run / validation)
  hec     POST each event to Splunk HEC /services/collector (event endpoint)

Usage:
  bridge.py --file <path> --mode stdout
  bridge.py --file <path> --mode hec --hec-url https://splunk:8088 --token <HEC_TOKEN> [--index factorio]
Common:
  --once            process what's there and exit (default: follow/tail)
  --poll 1.0        seconds between polls when following
  --from-start      start at the beginning of the file (default: resume/end)
  --insecure        skip TLS cert verification (HEC self-signed lab certs)

Note: the mod emits no timestamp (no wall clock in its sandbox). In HEC mode the
bridge stamps time.time() as it reads; a file monitor lets Splunk stamp at ingest.
"""
import argparse
import json
import os
import ssl
import sys
import time
import urllib.request


# ---------------------------------------------------------------- shippers ---

def ship_stdout(events, args, now):
    for ev in events:
        print(json.dumps(ev))
    return len(events)


def _post(url, data, headers, insecure):
    ctx = ssl._create_unverified_context() if insecure else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        return resp.status, resp.read().decode(errors="replace")


def ship_hec(events, args, now):
    # HEC event endpoint: one {"time","event",...} envelope per line, batched.
    envelopes = []
    for ev in events:
        env = {"time": now, "event": ev, "sourcetype": args.sourcetype}
        if args.index:
            env["index"] = args.index
        if args.source:
            env["source"] = args.source
        envelopes.append(json.dumps(env))
    body = "\n".join(envelopes).encode()
    url = args.hec_url.rstrip("/") + "/services/collector"
    headers = {"Authorization": "Splunk " + args.token, "Content-Type": "application/json"}
    status, text = _post(url, body, headers, args.insecure)
    if status not in (200, 201):
        raise RuntimeError(f"HEC returned {status}: {text}")
    return len(events)


SHIPPERS = {"stdout": ship_stdout, "hec": ship_hec}


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
    offset = read_pos(args.file)
    if offset is None:
        offset = 0 if args.from_start else _size(args.file)

    total = 0
    while True:
        size = _size(args.file)
        if size < offset:  # file rotated/truncated (e.g. a new session file)
            offset = 0
        if size > offset:
            with open(args.file, "rb") as fh:  # binary: byte offsets stay exact
                fh.seek(offset)
                chunk = fh.read()
            nl = chunk.rfind(b"\n")  # only consume through the last complete line
            if nl != -1:
                consumed = chunk[: nl + 1]
                events = parse_lines(consumed.decode("utf-8", "replace").splitlines())
                if events:
                    shipped = ship(events, args, time.time())
                    total += shipped
                    sys.stderr.write(f"[{args.mode}] shipped {shipped} (total {total})\n")
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
    p = argparse.ArgumentParser(description="Tail splunk-obs NDJSON events and ship them.")
    p.add_argument("--file", required=True, help="path to the mod's NDJSON output")
    p.add_argument("--mode", choices=list(SHIPPERS), default="stdout")
    p.add_argument("--once", action="store_true", help="process and exit (no follow)")
    p.add_argument("--from-start", action="store_true", help="start at file beginning")
    p.add_argument("--poll", type=float, default=1.0, help="seconds between polls")
    p.add_argument("--insecure", action="store_true", help="skip TLS verification")
    # HEC
    p.add_argument("--hec-url", help="e.g. https://splunk:8088")
    p.add_argument("--token", help="HEC token")
    p.add_argument("--index", help="target index")
    p.add_argument("--source", default="factorio:splunk-obs")
    p.add_argument("--sourcetype", default="factorio:event")
    args = p.parse_args()

    if args.mode == "hec" and not (args.hec_url and args.token):
        p.error("--mode hec requires --hec-url and --token")

    try:
        run(args)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
