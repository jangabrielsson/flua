"""Declarative route table for the simulated HC3 REST API.

One file per category of the hc3-rest-api skill (devices, plugins, scenes,
alarms, system), so the code maps 1:1 to the API docs. Each entry is
(HTTP method, path pattern, handler); ``{name}`` segments become
``ApiRequest.path_params`` entries. Order matters where patterns overlap
(e.g. /alarms/v1/partitions/breached before .../{id}). Unknown paths
return 404 like the HC3.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..request import ApiRequest
from ..state import SimState
from .alarms import (
    partition_arm,
    partition_disarm,
    partition_get,
    partitions_arm_all,
    partitions_breached,
    partitions_disarm_all,
    partitions_list,
)
from .devices import (
    action_device,
    device_delete,
    device_get,
    device_property_get,
    device_update,
    devices_list,
    group_action,
)
from .plugins import (
    child_device_create,
    child_device_remove,
    embedded_ui_list,
    plugin_get,
    plugin_restart,
    plugin_update_interfaces,
    plugin_update_property,
    plugin_update_view,
    plugins_list,
    ui_event_call,
    variable_delete,
    variable_get,
    variable_post,
    variable_put,
    variables_clear,
    variables_list,
)
from .scenes import (
    custom_event_post,
    custom_event_post_body,
    scene_execute,
    scene_get,
    scene_kill,
    scenes_list,
)
from .system import (
    alarm_devices_list,
    custom_event_get,
    custom_events_list,
    debug_messages_list,
    diagnostics_get,
    energy_devices_list,
    global_delete,
    global_get,
    global_put,
    globals_create,
    globals_list,
    home_get,
    icons_list,
    ios_devices_list,
    location_get,
    location_put,
    notification_center_list,
    panel_climate_get,
    panels_climate,
    panels_family,
    panels_favorite_colors,
    panels_humidity,
    panels_location,
    panels_notifications,
    panels_sprinklers,
    profile_activate,
    profile_get,
    profiles_list,
    proxy_get,
    refresh_states,
    room_get,
    rooms_list,
    section_get,
    sections_list,
    settings_info,
    users_list,
    weather_get,
)

Handler = Callable[[SimState, ApiRequest], tuple[Any, int]]

ROUTES: list[tuple[str, str, Handler]] = [
    # -- devices -------------------------------------------------------------
    ("GET", "/devices", devices_list),
    ("GET", "/devices/{id}", device_get),
    ("PUT", "/devices/{id}", device_update),
    ("DELETE", "/devices/{id}", device_delete),
    ("GET", "/devices/{id}/properties/{name}", device_property_get),
    ("POST", "/devices/{id}/action/{action}", action_device),
    ("POST", "/devices/groupAction/{action}", group_action),
    # -- plugins ---------------------------------------------------------------
    ("GET", "/plugins", plugins_list),
    ("GET", "/flua/embeddedUI", embedded_ui_list),  # flua-specific viewer channel
    ("GET", "/plugins/callUIEvent", ui_event_call),  # before /plugins/{id}: patterns overlap
    ("POST", "/plugins/callUIEvent", ui_event_call),  # proxy devices POST their UI events
    ("GET", "/plugins/{id}", plugin_get),
    ("GET", "/plugins/{id}/variables", variables_list),
    ("GET", "/plugins/{id}/variables/{key}", variable_get),
    ("PUT", "/plugins/{id}/variables/{key}", variable_put),
    ("POST", "/plugins/{id}/variables", variable_post),
    ("DELETE", "/plugins/{id}/variables/{key}", variable_delete),
    ("DELETE", "/plugins/{id}/variables", variables_clear),
    ("POST", "/plugins/createChildDevice", child_device_create),
    ("DELETE", "/plugins/removeChildDevice/{id}", child_device_remove),
    ("POST", "/plugins/updateProperty", plugin_update_property),
    ("POST", "/plugins/updateView", plugin_update_view),
    ("POST", "/plugins/interfaces", plugin_update_interfaces),
    ("POST", "/plugins/restart", plugin_restart),
    # -- scenes & custom events -------------------------------------------------
    ("GET", "/scenes", scenes_list),
    ("GET", "/scenes/{id}", scene_get),
    ("POST", "/scenes/{id}/execute", scene_execute),
    ("POST", "/scenes/{id}/kill", scene_kill),
    ("POST", "/customEvents", custom_event_post_body),
    ("POST", "/customEvents/{name}", custom_event_post),
    # -- alarms (breached before {id}: overlapping patterns) ---------------------
    ("GET", "/alarms/v1/partitions", partitions_list),
    ("GET", "/alarms/v1/partitions/breached", partitions_breached),
    ("GET", "/alarms/v1/partitions/{id}", partition_get),
    ("POST", "/alarms/v1/partitions/actions/arm", partitions_arm_all),
    ("DELETE", "/alarms/v1/partitions/actions/disarm", partitions_disarm_all),
    ("POST", "/alarms/v1/partitions/{id}/actions/arm", partition_arm),
    ("DELETE", "/alarms/v1/partitions/{id}/actions/disarm", partition_disarm),
    # -- system ------------------------------------------------------------------
    ("GET", "/globalVariables", globals_list),
    ("POST", "/globalVariables", globals_create),
    ("GET", "/globalVariables/{name}", global_get),
    ("PUT", "/globalVariables/{name}", global_put),
    ("DELETE", "/globalVariables/{name}", global_delete),
    ("GET", "/settings/location", location_get),
    ("PUT", "/settings/location", location_put),
    ("GET", "/settings/info", settings_info),
    ("GET", "/refreshStates", refresh_states),
    ("GET", "/profiles", profiles_list),
    ("POST", "/profiles/activeProfile/{id}", profile_activate),
    ("GET", "/rooms", rooms_list),
    ("GET", "/rooms/{id}", room_get),
    ("GET", "/sections", sections_list),
    ("GET", "/sections/{id}", section_get),
    ("GET", "/customEvents", custom_events_list),
    ("GET", "/customEvents/{name}", custom_event_get),
    ("GET", "/iosDevices", ios_devices_list),
    ("GET", "/home", home_get),
    ("GET", "/debugMessages", debug_messages_list),
    ("GET", "/weather", weather_get),
    ("GET", "/alarms/v1/devices", alarm_devices_list),
    ("GET", "/notificationCenter", notification_center_list),
    ("GET", "/profiles/{id}", profile_get),
    ("GET", "/icons", icons_list),
    ("GET", "/users", users_list),
    ("GET", "/energy/devices", energy_devices_list),
    ("GET", "/panels/location", panels_location),
    ("GET", "/panels/climate", panels_climate),
    ("GET", "/panels/climate/{id}", panel_climate_get),
    ("GET", "/panels/notifications", panels_notifications),
    ("GET", "/panels/family", panels_family),
    ("GET", "/panels/sprinklers", panels_sprinklers),
    ("GET", "/panels/humidity", panels_humidity),
    ("GET", "/panels/favoriteColors", panels_favorite_colors),
    ("GET", "/panels/favoriteColors/v2", panels_favorite_colors),
    ("GET", "/diagnostics", diagnostics_get),
    ("GET", "/proxy", proxy_get),
]
