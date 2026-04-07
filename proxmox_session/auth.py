"""
Proxmox authentication — connects to the cluster and returns a ProxmoxAPI instance.
Tries each host in the pool in random order for basic load balancing / failover.
"""

import random
from dataclasses import dataclass
from typing import Optional

import proxmoxer
import requests

from .config import HostConfig


@dataclass
class AuthResult:
    success: bool
    proxmox: Optional[proxmoxer.ProxmoxAPI] = None
    connected: bool = False
    error: Optional[Exception] = None


def authenticate(
    host_config: HostConfig,
    username: str,
    password: Optional[str] = None,
    totp: Optional[str] = None,
) -> AuthResult:
    """
    Attempt to authenticate against all hosts in the pool (random order).

    - Token auth:    username + token_name + token_value from host_config
    - Password auth: username + password (+ optional totp)
    Returns an AuthResult with success=True and a proxmox handle on success.
    """
    pool = host_config.hostpool.copy()
    random.shuffle(pool)

    last_error: Optional[Exception] = None

    for entry in pool:
        host = entry["host"]
        port = entry.get("port", 8006)
        user_at_backend = f"{username}@{host_config.backend}"

        try:
            if host_config.token_name and host_config.token_value:
                px = proxmoxer.ProxmoxAPI(
                    host,
                    user=user_at_backend,
                    token_name=host_config.token_name,
                    token_value=host_config.token_value,
                    verify_ssl=host_config.verify_ssl,
                    port=port,
                )
            elif totp:
                px = proxmoxer.ProxmoxAPI(
                    host,
                    user=user_at_backend,
                    password=password,
                    otp=totp,
                    verify_ssl=host_config.verify_ssl,
                    port=port,
                )
            else:
                px = proxmoxer.ProxmoxAPI(
                    host,
                    user=user_at_backend,
                    password=password,
                    verify_ssl=host_config.verify_ssl,
                    port=port,
                )

            # Trigger a lightweight API call to confirm the connection is live
            px.version.get()
            return AuthResult(success=True, proxmox=px, connected=True)

        except proxmoxer.backends.https.AuthenticationError as e:
            # Credentials rejected — host was reachable
            return AuthResult(success=False, connected=True, error=e)

        except (
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ConnectionError,
        ) as e:
            last_error = e
            # Try next host

    return AuthResult(success=False, connected=False, error=last_error)
