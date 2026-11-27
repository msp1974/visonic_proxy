# Visonic Proxy Add-on

Proxy for Visonic PowerMaster (10 / 30) panels with a PowerLink 3.1 module so
Home Assistant and the Visonic mobile app (PowerManage) can work simultaneously.

## Which port and mode should I use?

| Home Assistant Integration | `websocket.enabled` | Port for HA Integration |
|---|---|---|
| **Visonic Alarm Panel** (`davesmeghead/visonic`) | `false` (Off) | **`5002`** (Socket TCP) |
| **Visonic Powerlink** (`msp1974/visonic_powerlink`) | `true` (On) | **`8082`** (WebSocket) |

> **Important:** Ports **`5001`** and **`8443`** are exclusively for the
> physical Visonic alarm panel (PowerLink 3.1). Do not enter `5001` or `8443` in
> your Home Assistant integration configuration.

## Quick setup for `davesmeghead/visonic` (Socket mode)

1. In the **Configuration** tab, turn **off** `websocket.enabled` (`false`).
2. Save and restart the add-on.
3. In the `Visonic` integration in Home Assistant, choose **Ethernet**, enter
   your Home Assistant IP address, and set port **`5002`**.

## Quick setup for `msp1974/visonic_powerlink` (WebSocket mode)

1. In the **Configuration** tab, turn **on** `websocket.enabled` (`true`).
2. Optionally enable `websocket.ssl` and set a strong `websocket.auth_key`.
3. Save and restart the add-on, then connect the integration to port **`8082`**.
