--[[
  Splunk Observability Exporter — control.lua

  Every N ticks, read the circuit-network signals connected to every *named*
  Display Panel and append them to a NDJSON file under script-output, in Splunk
  multi-metric format. See README.md and docs/plans for the full design.

  Sandbox realities this code works within:
    * no network I/O            -> we only write a file
    * no os.time / wall clock   -> no timestamp emitted; Splunk stamps at ingest
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
-- JSON serialization (hand-rolled: the exporter name is untrusted free text)
--------------------------------------------------------------------------------

local ESCAPES = {
  ['"'] = '\\"',
  ['\\'] = '\\\\',
  ['\b'] = '\\b',
  ['\f'] = '\\f',
  ['\n'] = '\\n',
  ['\r'] = '\\r',
  ['\t'] = '\\t',
}

-- Escape a string for embedding in JSON. Control chars (%c covers 0x00-0x1F and
-- 0x7F), quotes and backslashes are escaped; bytes >= 0x80 pass through so valid
-- UTF-8 stays valid UTF-8 (and thus valid JSON).
local function json_escape(s)
  return (s:gsub('[%c"\\]', function(c)
    return ESCAPES[c] or string.format('\\u%04x', string.byte(c))
  end))
end

-- The metric name for a signal: just its name, with the quality appended as a
-- suffix for anything above normal (e.g. "iron-plate", "iron-plate:legendary").
-- Signal type (item/fluid/virtual) is not encoded: cross-type name collisions
-- don't occur in practice, so keeping keys bare is cleaner.
local function metric_key(signal)
  local quality = signal.quality
  if quality and quality ~= "normal" then
    return signal.name .. ":" .. quality
  end
  return signal.name
end

-- Build one Splunk multi-metric JSON line: all signals on one wire/network of
-- one exporter, as metric_name:<key> measurements. Dimensions: surface,
-- exporter, wire, network_id. measures is an ordered array of { key, value }.
local function build_line(surface, exporter, wire, network_id, measures)
  local p = {
    '{"surface":"', json_escape(surface),
    '","exporter":"', json_escape(exporter),
    '","wire":"', wire,
    '","network_id":', string.format("%d", network_id),
  }
  local i = #p
  for _, m in ipairs(measures) do
    i = i + 1; p[i] = ',"metric_name:'
    i = i + 1; p[i] = json_escape(m.key)
    i = i + 1; p[i] = '":'
    i = i + 1; p[i] = string.format("%d", m.value)
  end
  i = i + 1; p[i] = '}'
  return table.concat(p)
end

--------------------------------------------------------------------------------
-- Sampling
--------------------------------------------------------------------------------

-- Read one panel's red+green networks and emit one multi-metric line per wire
-- that carries signals. Appends built lines to out[] and returns the new count.
local function collect_panel(panel, exporter, surface_name, out, n)
  for _, w in ipairs(WIRES) do
    local net = panel.get_circuit_network(w.id)
    if net and net.signals and #net.signals > 0 then
      local measures = {}
      for _, sig in ipairs(net.signals) do
        measures[#measures + 1] = { key = metric_key(sig.signal), value = sig.count }
      end
      n = n + 1
      out[n] = build_line(surface_name, exporter, w.color, net.network_id, measures)
    end
  end
  return n
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

-- One full sample across all surfaces. Writes at most one file append.
local function sample()
  local filename = settings.global[SETTING_FILENAME].value
  local out = {}
  local n = 0
  for _, surface in pairs(game.surfaces) do
    local surface_name = surface.name
    local panels = surface.find_entities_filtered{ type = "display-panel" }
    for _, panel in pairs(panels) do
      if panel.valid then
        local name = exporter_name(panel)
        if name then
          n = collect_panel(panel, name, surface_name, out, n)
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

commands.add_command("splunk-obs-sample", "Force an immediate Splunk metrics sample.", function(_)
  local n = sample()
  if game and game.player then
    game.player.print("[splunk-obs] wrote " .. n .. " metric line(s)")
  end
end)

remote.add_interface("splunk_obs", {
  -- Returns the number of NDJSON lines written this sample.
  sample_now = function()
    return sample()
  end,
})
