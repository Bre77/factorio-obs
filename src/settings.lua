data:extend({
  {
    type = "int-setting",
    name = "circuit-logger-sample-interval",
    setting_type = "runtime-global",
    default_value = 60, -- 60 ticks = 1 second at 60 UPS
    minimum_value = 1,
    maximum_value = 216000, -- 1 hour, sanity bound
    order = "a",
  },
  {
    type = "string-setting",
    name = "circuit-logger-filename",
    setting_type = "runtime-global",
    -- {session} is replaced by a per-load counter, so each game session writes
    -- its own file. Remove {session} to keep a single rolling file instead.
    default_value = "circuit-logger/factorio-{session}.ndjson",
    allow_blank = false,
    order = "b",
  },
})
