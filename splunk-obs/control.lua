--[[
  Splunk Observability Exporter — control.lua

  Every N ticks, read the circuit-network signals connected to every *named*
  Display Panel and append one JSON event per panel to a NDJSON file under
  script-output. See README.md and docs/plans for the full design.

  Sandbox realities this code works within:
    * no network I/O            -> we only write a file
    * no os.time / wall clock   -> no timestamp/epoch; a per-load counter names
                                   the session file; Splunk stamps _time at ingest
    * helpers.write_file        -> the one sanctioned output path
]]

local SETTING_INTERVAL = "splunk-obs-sample-interval"
local SETTING_FILENAME = "splunk-obs-filename"

-- Which wire connectors a Display Panel exposes (it is a simple single-point
-- circuit entity, so red/green rather than combinator input/output).
local WIRES = {
  { color = "red",   id = defines.wire_connector_id.circuit_red },
  { color = "green", id = defines.wire_connector_id.circuit_green },
}

--------------------------------------------------------------------------------
-- Event building (JSON via helpers.table_to_json)
--------------------------------------------------------------------------------

-- Build one JSON event for a panel, or nil if none of its wires carry signals.
-- Shape:
--   { surface, exporter, wire = { <color> = {
--       network_id,
--       <item_type> = { <signal_name> = { <quality> = value } }   -- items
--       <item_type> = { <signal_name> = value }                   -- non-items
--   } } }
-- Quality is nested only for item-type signals (the "quality is ignored for
-- non-quality items" rule); type -> name -> [quality] fully namespaces every
-- signal, so no two ever collide.
local function build_event(panel, exporter, surface_name)
  local wires = nil
  for _, w in ipairs(WIRES) do
    local net = panel.get_circuit_network(w.id)
    if net and net.signals and #net.signals > 0 then
      local tree = { network_id = net.network_id }
      for _, entry in ipairs(net.signals) do
        local signal = entry.signal
        local item_type = signal.type or "item" -- item SignalIDs omit type
        local by_type = tree[item_type]
        if not by_type then
          by_type = {}
          tree[item_type] = by_type
        end
        if item_type == "item" then
          local by_name = by_type[signal.name]
          if not by_name then
            by_name = {}
            by_type[signal.name] = by_name
          end
          by_name[signal.quality or "normal"] = entry.count
        else
          by_type[signal.name] = entry.count
        end
      end
      wires = wires or {}
      wires[w.color] = tree
    end
  end
  if not wires then
    return nil
  end
  return { surface = surface_name, exporter = exporter, wire = wires }
end

-- A Display Panel's control behavior holds its configured messages. In 2.0 the
-- array is `messages`; in 2.1 it was renamed to `records`. Resolve whichever the
-- running game exposes (memoized). display_panel_text is NOT usable here: on a
-- wired panel it is the live-rendered text, which conditions blank out.
local MSG_FIELD -- nil = unresolved, false = neither exists, else the field name

local function panel_messages(cb)
  if MSG_FIELD == false then return nil end
  if MSG_FIELD then return cb[MSG_FIELD] end
  for _, field in ipairs({ "messages", "records" }) do
    local ok, value = pcall(function() return cb[field] end)
    if ok then
      MSG_FIELD = field
      return value
    end
  end
  MSG_FIELD = false
  return nil
end

-- The exporter name is the first non-blank message text the user typed into the
-- panel (the panel's text field edits messages[1]). Returns nil to opt the panel
-- out of export when it has no name. Falls back to display_panel_text for the
-- unwired-panel edge case.
local function exporter_name(panel)
  local cb = panel.get_control_behavior()
  if cb then
    local messages = panel_messages(cb)
    if messages then
      for _, message in ipairs(messages) do
        if type(message.text) == "string" and message.text ~= "" then
          return message.text
        end
      end
    end
  end
  local text = panel.display_panel_text
  if type(text) == "string" and text ~= "" then
    return text
  end
  return nil
end

-- A per-load session counter names the output file, giving each game session
-- its own file. It must be bumped exactly once per session, from an event
-- context (storage is read-only in on_load), so we do it lazily on first sample
-- guarded by a plain local that resets when control.lua re-runs on each load.
local session_started = false

local function ensure_session()
  if not session_started then
    storage.session = (storage.session or 0) + 1
    session_started = true
  end
end

-- Resolve the output filename, substituting {session} with the session counter.
local function session_filename()
  local template = settings.global[SETTING_FILENAME].value
  return (template:gsub("{session}", tostring(storage.session or 1)))
end

-- One full sample across all surfaces: one JSON event per named panel that has
-- signals. Writes at most one file append.
local function sample()
  ensure_session()
  local filename = session_filename()
  local out = {}
  local n = 0
  for _, surface in pairs(game.surfaces) do
    local surface_name = surface.name
    local panels = surface.find_entities_filtered{ type = "display-panel" }
    for _, panel in pairs(panels) do
      if panel.valid then
        local name = exporter_name(panel)
        if name then
          local event = build_event(panel, name, surface_name)
          if event then
            n = n + 1
            out[n] = helpers.table_to_json(event)
          end
        end
      end
    end
  end
  if n > 0 then
    out[n + 1] = "" -- force a trailing newline from table.concat
    helpers.write_file(filename, table.concat(out, "\n"), true) -- append = true
  end
  return n
end

--------------------------------------------------------------------------------
-- Scheduling — keep on_nth_tick in sync with the runtime interval setting
--------------------------------------------------------------------------------

local function on_tick_sample()
  sample()
end

-- (Re)register the periodic sampler from the current interval setting. Reads
-- settings.global (allowed in on_load) and only touches event registration, so
-- it is safe to call from on_init / on_load / on_configuration_changed alike —
-- no reliance on stored state that a given lifecycle path might not populate.
local function reschedule()
  script.on_nth_tick(nil) -- clear any previously registered nth-tick handler
  local interval = settings.global[SETTING_INTERVAL].value
  if interval and interval > 0 then
    script.on_nth_tick(interval, on_tick_sample)
  end
end

script.on_init(reschedule)
script.on_load(reschedule)
script.on_configuration_changed(reschedule)

script.on_event(defines.events.on_runtime_mod_setting_changed, function(event)
  if event.setting == SETTING_INTERVAL then
    reschedule()
  end
end)

--------------------------------------------------------------------------------
-- Manual triggers (also used by the automated end-to-end test)
--------------------------------------------------------------------------------

commands.add_command("splunk-obs-sample", "Force an immediate splunk-obs sample.", function(_)
  local n = sample()
  if game and game.player then
    game.player.print("[splunk-obs] wrote " .. n .. " event(s)")
  end
end)

remote.add_interface("splunk_obs", {
  -- Returns the number of JSON event lines written this sample.
  sample_now = function()
    return sample()
  end,
})
