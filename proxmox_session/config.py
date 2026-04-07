"""
Config loader — reads vdiclient.ini (backward-compatible with PVE-VDIClient format).
Supports both file-based and HTTP-fetched configs.
"""

import json
import os
import sys
from configparser import ConfigParser
from dataclasses import dataclass, field
from typing import Optional

import requests


@dataclass
class HostConfig:
    hostpool: list[dict]         # [{"host": str, "port": int}, ...]
    backend: str = "pve"
    user: str = ""
    token_name: Optional[str] = None
    token_value: Optional[str] = None
    totp: bool = False
    verify_ssl: bool = True
    pwresetcmd: Optional[str] = None
    auto_vmid: Optional[int] = None
    knock_seq: list[dict] = field(default_factory=list)


@dataclass
class AppConfig:
    title: str = "VDI Login"
    theme: str = "system"
    icon: Optional[str] = None
    logo: Optional[str] = None
    kiosk: bool = False
    viewer_kiosk: bool = True
    fullscreen: bool = True
    inidebug: bool = False
    guest_type: str = "both"
    show_reset: bool = False
    show_hibernate: bool = False
    width: Optional[int] = None
    height: Optional[int] = None
    hosts: dict[str, HostConfig] = field(default_factory=dict)
    current_hostset: str = "DEFAULT"
    spiceproxy_conv: dict[str, str] = field(default_factory=dict)
    addl_params: Optional[dict[str, str]] = None


def _parse_host_section(config: ConfigParser, section: str) -> HostConfig:
    hc = HostConfig(hostpool=[])
    try:
        hostjson = json.loads(config[section]["hostpool"])
    except (KeyError, json.JSONDecodeError) as e:
        raise ValueError(f"Could not parse hostpool in [{section}]: {e}") from e
    for host, port in hostjson.items():
        hc.hostpool.append({"host": host, "port": int(port)})
    if "auth_backend" in config[section]:
        hc.backend = config[section]["auth_backend"]
    if "user" in config[section]:
        hc.user = config[section]["user"]
    if "token_name" in config[section]:
        hc.token_name = config[section]["token_name"]
    if "token_value" in config[section]:
        hc.token_value = config[section]["token_value"]
    if "auth_totp" in config[section]:
        hc.totp = config[section].getboolean("auth_totp", fallback=False)
    if "tls_verify" in config[section]:
        hc.verify_ssl = config[section].getboolean("tls_verify", fallback=True)
    if "pwresetcmd" in config[section]:
        hc.pwresetcmd = config[section]["pwresetcmd"]
    if "auto_vmid" in config[section]:
        hc.auto_vmid = config[section].getint("auto_vmid")
    if "knock_seq" in config[section]:
        try:
            hc.knock_seq = json.loads(config[section]["knock_seq"])
        except json.JSONDecodeError:
            pass
    return hc


def _default_config_paths() -> list[str]:
    if sys.platform == "win32":
        appdata = os.getenv("APPDATA", "")
        programfiles = os.getenv("PROGRAMFILES", "C:\\Program Files")
        programfiles_x86 = os.getenv("PROGRAMFILES(X86)", "C:\\Program Files (x86)")
        return [
            os.path.join(appdata, "VDIClient", "vdiclient.ini"),
            os.path.join(programfiles, "VDIClient", "vdiclient.ini"),
            os.path.join(programfiles_x86, "VDIClient", "vdiclient.ini"),
        ]
    # Linux / macOS
    return [
        os.path.expanduser("~/.config/VDIClient/vdiclient.ini"),
        "/etc/vdiclient/vdiclient.ini",
        "/usr/local/etc/vdiclient/vdiclient.ini",
    ]


def load_config(
    config_location: Optional[str] = None,
    config_type: str = "file",
    config_username: Optional[str] = None,
    config_password: Optional[str] = None,
    ssl_verify: bool = True,
) -> AppConfig:
    """
    Load and parse the VDI client config. Raises ValueError on error.
    Returns a populated AppConfig.
    """
    raw = ConfigParser(delimiters="=")

    if config_type == "file":
        if config_location:
            if not os.path.isfile(config_location):
                raise ValueError(f"Config file not found: {config_location}")
        else:
            for path in _default_config_paths():
                if os.path.exists(path):
                    config_location = path
                    break
            if not config_location:
                raise ValueError(
                    "No config file found. Create one at ~/.config/VDIClient/vdiclient.ini"
                )
        raw.read(config_location)

    elif config_type == "http":
        if not config_location:
            raise ValueError("--config_type http requires --config_location URL")
        try:
            auth: Optional[tuple[str, str]] = (
                (config_username, config_password or "") if config_username else None
            )
            r = requests.get(config_location, auth=auth, verify=ssl_verify, timeout=10)
            r.raise_for_status()
            raw.read_string(r.text)
        except requests.RequestException as e:
            raise ValueError(f"Failed to fetch config from URL: {e}") from e

    else:
        raise ValueError(f"Unknown config_type: {config_type!r}")

    if "General" not in raw:
        raise ValueError("Config missing required [General] section")

    cfg = AppConfig()
    g = raw["General"]

    if "title" in g:
        cfg.title = g["title"]
    if "theme" in g:
        cfg.theme = g["theme"]
    if "icon" in g and os.path.exists(g["icon"]):
        cfg.icon = g["icon"]
    if "logo" in g and os.path.exists(g["logo"]):
        cfg.logo = g["logo"]
    if "kiosk" in g:
        cfg.kiosk = g.getboolean("kiosk", fallback=False)
    if "viewer_kiosk" in g:
        cfg.viewer_kiosk = g.getboolean("viewer_kiosk", fallback=True)
    if "fullscreen" in g:
        cfg.fullscreen = g.getboolean("fullscreen", fallback=True)
    if "inidebug" in g:
        cfg.inidebug = g.getboolean("inidebug", fallback=False)
    if "guest_type" in g:
        cfg.guest_type = g["guest_type"]
    if "show_reset" in g:
        cfg.show_reset = g.getboolean("show_reset", fallback=False)
    if "window_width" in g:
        cfg.width = g.getint("window_width")
    if "window_height" in g:
        cfg.height = g.getint("window_height")

    # Legacy single-cluster format: [Authentication] + [Hosts]
    if "Authentication" in raw:
        hc = HostConfig(hostpool=[])
        if "Hosts" not in raw:
            raise ValueError("Config has [Authentication] but no [Hosts] section")
        for key in raw["Hosts"]:
            hc.hostpool.append({"host": key, "port": int(raw["Hosts"][key])})
        auth_sec = raw["Authentication"]
        if "auth_backend" in auth_sec:
            hc.backend = auth_sec["auth_backend"]
        if "user" in auth_sec:
            hc.user = auth_sec["user"]
        if "token_name" in auth_sec:
            hc.token_name = auth_sec["token_name"]
        if "token_value" in auth_sec:
            hc.token_value = auth_sec["token_value"]
        if "auth_totp" in auth_sec:
            hc.totp = auth_sec.getboolean("auth_totp", fallback=False)
        if "tls_verify" in auth_sec:
            hc.verify_ssl = auth_sec.getboolean("tls_verify", fallback=True)
        if "pwresetcmd" in auth_sec:
            hc.pwresetcmd = auth_sec["pwresetcmd"]
        if "auto_vmid" in auth_sec:
            hc.auto_vmid = auth_sec.getint("auto_vmid")
        cfg.hosts["DEFAULT"] = hc
        cfg.current_hostset = "DEFAULT"
    else:
        # New-style: [Hosts.<name>] sections
        first = True
        for section in raw.sections():
            if section.startswith("Hosts."):
                _, group = section.split(".", 1)
                cfg.hosts[group] = _parse_host_section(raw, section)
                if first:
                    cfg.current_hostset = group
                    first = False

    if not cfg.hosts:
        raise ValueError("No host sections found in config (expected [Hosts.<name>])")

    if "SpiceProxyRedirect" in raw:
        for key in raw["SpiceProxyRedirect"]:
            cfg.spiceproxy_conv[key] = raw["SpiceProxyRedirect"][key]

    if "AdditionalParameters" in raw:
        cfg.addl_params = {}
        for key in raw["AdditionalParameters"]:
            cfg.addl_params[key] = raw["AdditionalParameters"][key]

    return cfg
