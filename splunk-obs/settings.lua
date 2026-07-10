data:extend({
  {
    type = "int-setting",
    name = "splunk-obs-sample-interval",
    setting_type = "runtime-global",
    default_value = 60, -- 60 ticks = 1 second at 60 UPS
    minimum_value = 1,
    maximum_value = 216000, -- 1 hour, sanity bound
    order = "a",
  },
  {
    type = "string-setting",
    name = "splunk-obs-filename",
    setting_type = "runtime-global",
    default_value = "splunk-obs/factorio-metrics.ndjson",
    allow_blank = false,
    order = "b",
  },
})
