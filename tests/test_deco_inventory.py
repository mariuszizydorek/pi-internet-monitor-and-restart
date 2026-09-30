import base64
import json

from netwatch.monitor.deco import sign_username, snapshot_from_payload


def test_blank_username_signs_as_admin():
    assert sign_username("") == "admin"
    assert sign_username("  ") == "admin"
    assert sign_username("owner") == "owner"


def test_snapshot_keeps_status_and_drops_passwords():
    ssid = base64.b64encode(b"32rr").decode()
    client_name = base64.b64encode(b"laptop").decode()
    payload = {
        "internet": {
            "link_status": "plugged",
            "ipv4": {"inet_status": "online", "dial_status": "connected"},
        },
        "wan": {
            "wan": {
                "dial_type": "pppoe",
                "user_info": {"username": "do-not-store"},
                "ip_info": {
                    "ip": "45.10.100.55",
                    "mask": "255.255.255.255",
                    "gateway": "45.10.101.234",
                    "dns1": "188.215.74.252",
                    "dns2": "0.0.0.0",
                },
            },
            "lan": {"ip_info": {"ip": "192.168.68.1", "mask": "255.255.252.0"}},
        },
        "wlan": {
            "band2_4": {
                "host": {
                    "ssid": ssid,
                    "enable": True,
                    "channel": 5,
                    "mode": "11ng",
                    "password": "do-not-store",
                },
                "guest": {"enable": False, "password": "do-not-store"},
            },
            "mlo": {"host": {"enable": False, "password": "do-not-store"}},
            "iot": {"host": {"enable": False, "password": "do-not-store"}},
        },
        "devices": {
            "device_list": [
                {
                    "mac": "aa",
                    "nickname": "Office",
                    "custom_nickname": "not-base64",
                    "role": "master",
                    "device_model": "BE25",
                    "software_ver": "1.1",
                    "device_ip": "192.168.68.1",
                    "inet_status": "online",
                    "group_status": "connected",
                }
            ]
        },
        "clients": {
            "client_list": [
                {
                    "mac": "bb",
                    "name": client_name,
                    "ip": "192.168.68.67",
                    "online": True,
                    "wire_type": "wired",
                    "connection_type": "wired",
                    "up_speed": 10,
                    "down_speed": 20,
                    "client_type": "pc",
                },
                {
                    "mac": "cc",
                    "name": "phone",
                    "ip": "192.168.68.80",
                    "online": True,
                    "wire_type": "wireless",
                    "connection_type": "band5_1",
                    "up_speed": 1,
                    "down_speed": 2,
                    "client_type": "phone",
                },
            ]
        },
        "performance": {"cpu_usage": 0.06, "mem_usage": 0.58},
    }

    snapshot = snapshot_from_payload(payload)

    assert snapshot.deco_api_ok == 1
    assert snapshot.wan_status == "online"
    assert snapshot.connect_type == "pppoe"
    assert snapshot.wan_ip == "45.10.100.55"
    assert snapshot.lan_ip == "192.168.68.1"
    assert snapshot.client_count == 2
    assert snapshot.nodes[0].name == "Office"
    assert snapshot.nodes[0].model == "BE25"
    assert snapshot.clients[0].name == "laptop"
    assert snapshot.clients[0].connection == "wired"
    assert snapshot.clients[1].connection == "5G"
    detail = json.loads(snapshot.detail_json)
    assert detail["wifi"][0]["ssid"] == "32rr"
    assert detail["wifi"][0]["channel"] == 5
    assert "password" not in snapshot.detail_json
    assert "do-not-store" not in snapshot.detail_json
