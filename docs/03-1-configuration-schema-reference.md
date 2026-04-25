# 3.1 Configuration Schema Reference

> **All configuration is optional.** IterViz works zero-config. This page documents the parameters that can be tuned once YAML/dict configuration lands in **Phase 2a**.

Every parameter below is **optional** and has a sensible default. You only need to set a parameter if you want to override its default.

---

## 3.1.1 `server.*`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `server.host` | string | `"127.0.0.1"` | Bind host for the auto-spawned server. |
| `server.port` | integer | `8765` | Port to bind. |
| `server.open_browser` | boolean | `true` | Whether to open the dashboard in the user's default browser on startup. |
| `server.url` *(client-side)* | string | *(unset → auto-spawn)* | If set, connect to a remote IterViz server instead of auto-spawning one. |

---

## 3.1.2 `ui.*`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `ui.refresh_interval_ms` | integer | `200` | Repaint cadence for live charts. |
| `ui.layout` | enum | `"auto-grid"` | Either `"auto-grid"` or `"explicit"`. |
| `ui.charts` | list | `[]` | Only consulted when `layout="explicit"`. See 3.1.5. |

---

## 3.1.3 `runs.*`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `runs.window_size` | integer | `1000` | Per-metric ring-buffer length. |

---

## 3.1.4 `logging.*`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `logging.verbose` | boolean | `false` | Promote debug logs from `~/.iterviz/logs/` to stderr. |
| `logging.log_dir` | string | `"~/.iterviz/logs/"` | Where verbose / debug logs are written. |

---

## 3.1.5 `ui.charts[*]` (explicit layout)

| Parameter | Type | Default | Description |
|---|---|---|---|
| `metric` | string | *required* | Metric name to chart. |
| `type` | enum | *(auto-detected)* | One of `"line"`, `"histogram"`, `"scatter"`. |
| `transforms` | list of string | `[]` | Transforms to apply (Phase 2a). E.g. `"moving_average:5"`, `"lttb:1000"`, `"normalize"`. |
| `title` | string | `metric` | Display title in the dashboard. |

---

## 3.1.6 Auto-detection behavior

When no `ui.charts` list is provided (the default), IterViz infers chart types from incoming payloads:

| First-seen value type | Chart type |
|---|---|
| `int` / `float` | `line` |
| `list[number]` | `histogram` |
| `dict[str, number]` | multi-series `line` |
| anything else | dropped with a warning |

These rules also apply to any metric whose name is **not** listed in an explicit `ui.charts` config — explicit charts override auto-detection only for the listed metrics.

---

## 3.1.7 Worked example

A user who is happy with all defaults provides **no configuration at all**. A user who wants longer history and an explicit chart layout for `loss`:

```yaml
runs:
  window_size: 5000
ui:
  layout: explicit
  charts:
    - metric: loss
      type: line
      transforms: [moving_average:10]
```

Everything else (including any metric the user logs that isn't named `loss`) continues to auto-detect.
