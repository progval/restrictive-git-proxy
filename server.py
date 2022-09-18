#!/usr/bin/env -S python3 -I
# Using option -I https://docs.python.org/3/using/cmdline.html#cmdoption-I
# in case 'AcceptEnv' is misconfigured.

# restrictive-git-proxy, a Git SSH proxy that allows compartmentalizing clients
# Copyright (C) 2022  Valentin Lorentz
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License version 3,
# as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import fnmatch
import json
import os
import re
import shlex
import sys
from typing import Dict, List, NoReturn, Tuple


SSH_PATH = "/usr/bin/ssh"
"""
Path to the SSH binary to execute.

This is a hardcoded path to the binary, to prevent execution of arbitrary executables
in case AcceptEnv is misconfigured.
Edit the value above if you want to use a different path.
"""


class ConfigError(Exception):
    """
    Exception raised on any configuration issue.
    """


class ClientError(Exception):
    """
    Exception raised on any misbehavior from a client (either a misconfiguration
    or malicious)
    """


def check_config(config: Dict[str, List[str]]) -> None:
    if not isinstance(config, dict):
        raise ConfigError("Config must be a JSON object.")

    client_name_re = re.compile(r"^\S+$")
    allow_list_item_re = re.compile(r"^[^\s@:]+@[^\s@:]+:\S+$")

    # Iterate on (key, value) in the JSON object
    for (client_name, client_allow_list) in config.items():

        # Check client names just to be safe.
        if not client_name_re.match(client_name):
            raise ConfigError(f"Invalid client name: {client_name!r}")

        if not isinstance(client_allow_list, list):
            raise ConfigError(f"Config value for {client_name} is not a JSON array.")

        if any(not isinstance(item, str) for item in client_allow_list):
            raise ConfigError(
                f"Config value for {client_name} is not an array of strings"
            )

        for item in client_allow_list:
            if not allow_list_item_re.match(item):
                raise ConfigError(f"Invalid allow list item {item!r} of {client_name}")


def get_requested_remote() -> Tuple[str, str, str]:
    """parses $SSH_ORIGINAL_COMMAND from the environment to get:
    the command, hostname and path of the remote the client requested access to."""
    try:
        ssh_original_command = os.environ["SSH_ORIGINAL_COMMAND"]
    except KeyError:
        raise ConfigError(
            "Authentication to restrictive-git-proxy successful; "
            "but this is not a shell. Use a git client to connect."
        )

    try:
        (command, *args) = shlex.split(ssh_original_command)
    except ValueError:
        raise ClientError(f"Failed to tokenize command: {ssh_original_command!r}")

    if command not in ("git-receive-pack", "git-upload-archive", "git-upload-pack"):
        raise ClientError(f"Invalid git command: {command}")

    try:
        (requested_host_and_path,) = args
    except ValueError:
        raise ClientError(f"Expected exactly one argument, got: {args!r}")

    # Split on first ':'
    m = re.match(
        r"^(?P<host>[^\s@:]+@[^\s@:]+):(?P<path>[^'\s]+)$", requested_host_and_path
    )
    if m is None:
        raise ClientError(
            f"Expected {command} parameter to be '<user>@<host>:<path>', got: "
            f"{requested_host_and_path!r}"
        )
    requested_host = m.group("host")
    requested_path = m.group("path")

    # Eliminate common vectors of path traversal vulnerabilities.
    # Technically these are valid and there may good reasons to allow them,
    # but I cannot think of any.
    # Do not rely on this for security though.
    if ".." in requested_path or requested_path.startswith("/"):
        raise ClientError(
            f"Expected {command} parameter to be <user>@<host>:<path>, got: "
            f"{requested_host_and_path!r}"
        )

    return (command, requested_host, requested_path)


def assert_client_allowed(
    allow_list: List[str], requested_host: str, requested_path: str
) -> None:
    """Checks that the client-provided host and path are in the allow list.
    Raises ClientError if not.
    """

    for allowed_item in allow_list:
        # Split on first ':'
        (allowed_host, allowed_path) = allowed_item.split(":", 1)

        if not fnmatch.fnmatchcase(requested_host, allowed_host):
            continue

        if not fnmatch.fnmatchcase(requested_path, allowed_path):
            continue

        # client is allowed
        return

    raise ClientError(f"Access to {requested_host}:{requested_path} is not allowed")


def connect_client_to_remote(
    requested_command: str, requested_host: str, requested_path: str
) -> NoReturn:
    """execs a ssh client to the remoted requested by the client."""
    # No need to quote requested_path, because get_requested_remote ensures it does
    # not contain any single quote
    os.execl(
        SSH_PATH,
        SSH_PATH,
        requested_host,
        f"{requested_command} {shlex.quote(requested_path)}",
    )


def main() -> NoReturn:
    # Parses the command-line to get config path and client name
    try:
        (_executable, config_path, client_name) = sys.argv
    except ValueError:
        raise ConfigError("Syntax: server.py <config.json> <client-name>")

    # Open and parse configuration
    try:
        with open(config_path) as fd:
            config = json.load(fd)
    except ValueError as e:
        raise ConfigError(f"Invalid configuration: {e}")
    except FileNotFoundError as e:
        raise ConfigError(f"Non-existent configuration: {e}")
    except OSError as e:
        raise ConfigError(f"Unreadable configuration: {e}")

    # Check configuration
    check_config(config)

    # Get the list of <host>:<path> the client is allowed access to
    try:
        client_allow_list = config[client_name]
    except KeyError as e:
        raise ConfigError(f"Unknown client name: {e.args[0]}")

    # Get what the client is requesting access to
    (requested_command, requested_host, requested_path) = get_requested_remote()

    # Check the client is allowed to access the <host>:<path> it requested access to
    assert_client_allowed(client_allow_list, requested_host, requested_path)

    # exec a ssh command to actually connect the client to the remote
    connect_client_to_remote(requested_command, requested_host, requested_path)


if __name__ == "__main__":
    try:
        main()
    except ConfigError as e:
        print(e.args[0], file=sys.stderr)
        exit(1)
    except ClientError as e:
        # TODO: this should be logged somewhere
        print(e.args[0], file=sys.stderr)
        exit(2)
