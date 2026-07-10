#!/usr/bin/env python3
"""End-to-end test: build a wired, named display panel, force a sample, verify NDJSON."""
import json, os, time
from rcon import Rcon

OUT = os.path.expanduser(
    "~/Library/Application Support/factorio/script-output/splunk-obs/factorio-metrics.ndjson"
)
NAME = 'iron "smelting"'  # includes a quote to exercise JSON escaping

r = Rcon("127.0.0.1", 27599, "testpw")

build = r.lua(f"""
local s=game.surfaces.nauvis
local f=game.forces.player
for _,e in pairs(s.find_entities_filtered{{area={{{{15,15}},{{35,35}}}},type={{'constant-combinator','display-panel'}}}}) do e.destroy() end
local cc=s.create_entity{{name='constant-combinator',position={{20,20}},force=f}}
local dp=s.create_entity{{name='display-panel',position={{23,20}},force=f}}
if not (cc and dp) then rcon.print('BUILD_FAIL'); return end
local b=cc.get_or_create_control_behavior()
if b.sections_count==0 then b.add_section() end
local sec=b.get_section(1)
sec.set_slot(1,{{value={{type='item',name='iron-plate',quality='normal',comparator='='}},min=4200}})
sec.set_slot(2,{{value={{type='item',name='copper-plate',quality='normal',comparator='='}},min=100}})
sec.set_slot(3,{{value={{type='item',name='iron-plate',quality='uncommon',comparator='='}},min=7}})
cc.get_wire_connector(defines.wire_connector_id.circuit_green,true).connect_to(dp.get_wire_connector(defines.wire_connector_id.circuit_green,true))
-- name the exporter by putting text in the panel's first message (== its text field)
local cb=dp.get_or_create_control_behavior()
cb.messages={{{{text=[[{NAME}]], icon={{type='item',name='iron-plate'}}}}}}
rcon.print('BUILD_OK msg1='..tostring(cb.messages[1].text))
""")
print("build:", build)

time.sleep(2.0)  # let the network propagate

n = r.lua("rcon.print(remote.call('splunk_obs','sample_now'))")
print("lines written:", n)

time.sleep(0.3)
print("\n=== NDJSON file ===")
with open(OUT) as fh:
    content = fh.read()
print(repr(content))

print("\n=== parsed & asserted ===")
lines = [l for l in content.splitlines() if l.strip()]
assert lines, "no lines written!"
obj = json.loads(lines[-1])
print(json.dumps(obj, indent=2))
assert obj["exporter"] == NAME, f"exporter/escaping wrong: {obj['exporter']!r}"
assert obj["surface"] == "nauvis"
assert obj["wire"] == "green"
assert isinstance(obj["network_id"], int)
assert obj["metric_name:iron-plate"] == 4200
assert obj["metric_name:copper-plate"] == 100
assert obj["metric_name:iron-plate:uncommon"] == 7
assert "item_type" not in obj and "quality" not in obj, "dropped dims leaked"
# every line must be valid JSON (multi-metric shape)
for ln in lines:
    json.loads(ln)
print("\nALL ASSERTIONS PASSED ✅")
