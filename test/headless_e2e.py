#!/usr/bin/env python3
"""End-to-end test: build a wired, named display panel (items of two qualities via
a constant combinator + a fluid via a storage tank), force a sample, and verify
the JSON event's nested wire.<color>.<item_type>.<name>[.<quality>] tree."""
import glob, json, os, time
from rcon import Rcon

OUTDIR = os.path.expanduser(
    "~/Library/Application Support/factorio/script-output/splunk-obs"
)
NAME = 'iron "smelting"'  # embedded quote exercises JSON escaping

r = Rcon("127.0.0.1", 27599, "testpw")

build = r.lua(f"""
local s=game.surfaces.nauvis
local f=game.forces.player
local tiles={{}}
for x=18,30 do for y=18,22 do tiles[#tiles+1]={{name='refined-concrete',position={{x,y}}}} end end
s.set_tiles(tiles)  -- guarantee land under the build area (random map may be water/cliffs)
for _,e in pairs(s.find_entities_filtered{{area={{{{10,10}},{{40,40}}}},type={{'constant-combinator','display-panel','storage-tank'}}}}) do e.destroy() end
local cc=s.create_entity{{name='constant-combinator',position={{20,20}},force=f}}
local dp=s.create_entity{{name='display-panel',position={{23,20}},force=f}}
local tank=s.create_entity{{name='storage-tank',position={{27,20}},force=f}}
if not (cc and dp and tank) then rcon.print('BUILD_FAIL'); return end
tank.insert_fluid{{name='water', amount=5000}}
local b=cc.get_or_create_control_behavior()
if b.sections_count==0 then b.add_section() end
local sec=b.get_section(1)
sec.set_slot(1,{{value={{type='item',name='iron-plate',quality='normal'}},min=4200}})
sec.set_slot(2,{{value={{type='item',name='iron-plate',quality='uncommon'}},min=7}})
local g=defines.wire_connector_id.circuit_green
cc.get_wire_connector(g,true).connect_to(dp.get_wire_connector(g,true))
tank.get_wire_connector(g,true).connect_to(dp.get_wire_connector(g,true))
dp.get_or_create_control_behavior().messages={{{{text=[[{NAME}]], icon={{type='item',name='iron-plate'}}}}}}
rcon.print('BUILD_OK')
""")
print("build:", build)

for _ in range(15):  # step ticks so the network exists (empty server barely ticks)
    r.cmd("/silent-command 1")
time.sleep(0.5)
n = r.lua("rcon.print(remote.call('splunk_obs','sample_now'))")
print("events written:", n)
print("session:", r.lua("rcon.print(storage.session)"))

time.sleep(0.3)
files = sorted(os.path.basename(f) for f in glob.glob(os.path.join(OUTDIR, "*.ndjson")))
print("files:", files)
assert "factorio-1.ndjson" in files, "expected session file factorio-1.ndjson"

with open(os.path.join(OUTDIR, "factorio-1.ndjson")) as fh:
    lines = [l for l in fh.read().splitlines() if l.strip()]
obj = json.loads(lines[-1])
print("\n=== event ===")
print(json.dumps(obj, indent=2))

assert obj["surface"] == "nauvis"
assert obj["exporter"] == NAME, f"escaping wrong: {obj['exporter']!r}"
green = obj["wire"]["green"]
assert isinstance(green["network_id"], int)                 # per-wire network_id
assert green["item"]["iron-plate"] == {"normal": 4200, "uncommon": 7}  # item: quality nested
assert green["fluid"]["water"] == 5000                      # non-item: value direct, no quality
assert "red" not in obj["wire"]                             # nothing on red
for ln in lines:
    json.loads(ln)  # every line valid JSON
print("\nALL ASSERTIONS PASSED ✅")
