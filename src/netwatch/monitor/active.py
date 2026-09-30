"""Pick Ethernet or Wi-Fi, whichever link is actually up."""

from __future__ import annotations

from netwatch.monitor.link import LinkSnapshot


def kind_of(iface: str, ethernet: tuple[str, ...], wifi: tuple[str, ...]) -> str:
    if iface in wifi:
        return "wifi"
    if iface in ethernet:
        return "ethernet"
    if iface.startswith(("wl", "wlan", "wifi")):
        return "wifi"
    return "ethernet"


def link_is_up(link: LinkSnapshot, kind: str) -> bool:
    if kind == "wifi":
        return bool(link.wifi_ssid) or link.carrier == 1
    return link.carrier == 1


def select_links(
    links: list[LinkSnapshot],
    *,
    mode: str,
    ethernet: tuple[str, ...],
    wifi: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (ifaces to probe, ifaces that count for online/offline).

    auto probes Ethernet when that cable is up, otherwise Wi-Fi when it is
    associated. A down interface is not probed. When neither link is up, every
    configured interface still counts so a total outage can restart the router.
    """
    grouped: dict[str, list[LinkSnapshot]] = {"ethernet": [], "wifi": []}
    for link in links:
        grouped[kind_of(link.iface, ethernet, wifi)].append(link)
    everyone = tuple(link.iface for link in links)

    if mode == "auto":
        ethernet_up = tuple(link.iface for link in grouped["ethernet"] if link_is_up(link, "ethernet"))
        wifi_up = tuple(link.iface for link in grouped["wifi"] if link_is_up(link, "wifi"))
        active = ethernet_up + wifi_up
        if active:
            return active, active
        return (), everyone

    pool = grouped[mode]
    active = tuple(link.iface for link in pool if link_is_up(link, mode))
    if active:
        return active, active
    return (), tuple(link.iface for link in pool) or everyone


def standby_reason(iface: str, mode: str, ethernet: tuple[str, ...], wifi: tuple[str, ...]) -> str:
    if mode == "ethernet":
        return "link mode is ethernet"
    if mode == "wifi":
        return "link mode is wifi"
    return "not connected"
