# Headless end-to-end test

Drives a real headless Factorio server over RCON to prove the mod produces
correct NDJSON. This is how the mod was verified against 2.0.77 + Space Age.

- `rcon.py` — tiny stdlib Source-RCON client (handles Factorio's auth handshake;
  `.lua()` sends a multi-line silent-command with newlines preserved).
- `headless_e2e.py` — builds a constant combinator wired into a named Display
  Panel, forces a sample, and asserts the resulting multi-metric line
  (dimensions, quality suffix, JSON escaping of the exporter name).

## Run it

```bash
FBIN="/path/to/factorio"          # the game binary
FACT="$HOME/Library/Application Support/factorio"

# 1. install the mod (symlink the folder; name must stay 'splunk-obs') and enable it
ln -sfn "$PWD/splunk-obs" "$FACT/mods/splunk-obs"
#   add {"name":"splunk-obs","enabled":true} to $FACT/mods/mod-list.json

# 2. create a map and start a headless server with RCON
"$FBIN" --create /tmp/test.zip
"$FBIN" --start-server /tmp/test.zip --rcon-port 27599 --rcon-password testpw &

# 3. run the test
python3 test/headless_e2e.py
```

Note: an empty headless server barely advances ticks, so the automatic
`on_nth_tick` cadence is exercised by stepping ticks via a burst of RCON commands
rather than by waiting real time (see the design doc's "Build outcome").
