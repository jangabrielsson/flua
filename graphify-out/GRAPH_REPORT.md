# Graph Report - api  (2026-11-03)

## Corpus Check
- Corpus is ~14,320 words - fits in a single context window. You may not need a graph.

## Summary
- 298 nodes · 988 edges · 9 communities (7 shown, 2 thin omitted)
- Extraction: 71% EXTRACTED · 29% INFERRED · 0% AMBIGUOUS · INFERRED: 286 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7

## God Nodes (most connected - your core abstractions)
1. `SimState` - 145 edges
2. `ApiRequest` - 111 edges
3. `public()` - 67 edges
4. `remote_get()` - 35 edges
5. `Api` - 18 edges
6. `forward_to_proxy()` - 16 edges
7. `_now()` - 10 edges
8. `variable_post()` - 10 edges
9. `_now()` - 10 edges
10. `devices_list()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `partition_arm()` --uses--> `ApiRequest`  [INFERRED]
  routes/alarms.py → request.py
- `partition_disarm()` --uses--> `ApiRequest`  [INFERRED]
  routes/alarms.py → request.py
- `partition_get()` --uses--> `ApiRequest`  [INFERRED]
  routes/alarms.py → request.py
- `partitions_arm_all()` --uses--> `ApiRequest`  [INFERRED]
  routes/alarms.py → request.py
- `partitions_breached()` --uses--> `ApiRequest`  [INFERRED]
  routes/alarms.py → request.py

## Import Cycles
- None detected.

## Communities (9 total, 2 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.00
Nodes (53): ApiRequest, remote_get(), alarm_devices_list(), custom_event_get(), custom_events_list(), debug_messages_delete(), debug_messages_list(), debug_messages_tags() (+45 more)

### Community 1 - "Community 1"
Cohesion: 0.00
Nodes (3): _device_skeleton(), _lua_equal(), SimState

### Community 2 - "Community 2"
Cohesion: 0.00
Nodes (24): forward_to_proxy(), child_device_create(), child_device_remove(), embedded_ui_list(), _flatten_values(), walk(), _merge_view_state(), _now() (+16 more)

### Community 3 - "Community 3"
Cohesion: 0.00
Nodes (20): action_device(), _apply_default_action(), _default_action_value(), _device1_merged(), device_create(), device_delete(), device_get(), device_property_get() (+12 more)

### Community 4 - "Community 4"
Cohesion: 0.00
Nodes (5): compile_pattern(), _compile_routes(), route_match(), _trace_body(), _type_error()

### Community 6 - "Community 6"
Cohesion: 0.00
Nodes (10): _custom_event(), custom_event_delete(), custom_event_post(), custom_event_post_body(), custom_event_publish(), custom_event_put(), scene_execute(), scene_get() (+2 more)

### Community 7 - "Community 7"
Cohesion: 0.00
Nodes (7): partition_arm(), partition_disarm(), partition_get(), partitions_arm_all(), partitions_breached(), partitions_disarm_all(), partitions_list()

## Knowledge Gaps
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.