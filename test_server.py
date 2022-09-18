# Test suite of restrictive-git-proxy, a Git SSH proxy
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

import os

import pytest

import server


DEFAULT_CONFIG = """
{
    "client1": [
        "git@example.org:user1/repo1",
        "git@example.org:user1/repo2",
        "git@example.org:user2/repo3",
        "git@example.org:user3/*"
    ],
    "client2": [
        "git@*.example.org:user4/repo4",
        "git@*.example.com:user4/*"
    ]
}
"""


@pytest.fixture(autouse=True)
def mock_execl(mocker):
    execl = mocker.patch("os.execl")

    # Avoid accidentally calling exec(), it would hang tests.
    execl.side_effect = AssertionError

    yield execl


@pytest.fixture
def config_path(tmp_path):
    return tmp_path / "config.json"


@pytest.fixture
def config(mocker, config_path):
    def set_config(content):
        with config_path.open("wt" if isinstance(content, str) else "wb") as fd:
            fd.write(content)

    set_config(DEFAULT_CONFIG)

    return set_config


@pytest.fixture
def argv(mocker, config_path):
    def set_argv(value):
        assert all(isinstance(item, str) for item in value)
        mocker.patch("sys.argv", value)

    set_argv(("executable", str(config_path), "client1"))

    return set_argv


@pytest.fixture
def env(mocker):
    def set_env(key, value):
        mocker.patch.dict(os.environ, [(key, value)])

    return set_env


@pytest.mark.parametrize(
    "value",
    [
        (),
        ("executable",),
        ("executable", "config.json"),
        ("executable", "config.json", "client_name", "extra"),
    ],
)
def test_argv_error(argv, value):
    argv(value)
    with pytest.raises(server.ConfigError, match="^Syntax:"):
        server.main()


def test_nonexistent_config(argv, config_path):
    with pytest.raises(server.ConfigError, match="No such file or directory"):
        server.main()


def test_unreadable_config(argv, config_path, config):
    config_path.chmod(0o000)

    with pytest.raises(server.ConfigError, match="Unreadable configuration"):
        server.main()


def test_nonutf8_config(argv, config):
    config(b"caf\xe9")

    with pytest.raises(server.ConfigError, match="Invalid configuration"):
        server.main()


def test_unparseable_config(argv, config):
    config(b"{]")

    with pytest.raises(server.ConfigError, match="Invalid configuration"):
        server.main()


def test_invalid_config(argv, config):
    config("[]")
    with pytest.raises(server.ConfigError, match="Config must be a JSON object"):
        server.main()

    config("{42: []}")
    with pytest.raises(server.ConfigError, match="Invalid configuration"):
        server.main()

    config('{"foo bar": []}')
    with pytest.raises(server.ConfigError, match="Invalid client name"):
        server.main()

    config('{"foo": {}}')
    with pytest.raises(server.ConfigError, match="is not a JSON array"):
        server.main()

    config('{"foo": [{}]}')
    with pytest.raises(server.ConfigError, match="not an array of strings"):
        server.main()


@pytest.mark.parametrize(
    "value",
    [
        '{"foo": ["host:path"]}',
        '{"foo": ["user1@user2@host:path"]}',
        '{"foo": ["user@host:path1 path2"]}',  # maybe technically valid? but dodgy
        '{"foo": ["user@host:path1\\tpath2"]}',  # ditto
    ],
)
def test_invalid_config_allowlist(argv, config, value):
    config(value)

    with pytest.raises(server.ConfigError, match="Invalid allow list item"):
        server.main()


def test_unknown_client(argv, config_path, config):
    argv(("executable", str(config_path), "unknown_client"))

    with pytest.raises(server.ConfigError, match="Unknown client name"):
        server.main()


def test_missing_env_var(argv, config):
    with pytest.raises(server.ConfigError, match="this is not a shell. Use a git"):
        server.main()


@pytest.mark.parametrize(
    "value",
    [
        "foo",
        "foo git@example.org:user1/repo1",
        "foo git-receive-pack",
        "foo git@example.org:user1/repo1 git-receive-pack",
    ],
)
def test_invalid_command(argv, config, env, value):
    env("SSH_ORIGINAL_COMMAND", value)

    with pytest.raises(server.ClientError, match="Invalid git command: foo"):
        server.main()


@pytest.mark.parametrize(
    "value",
    [
        "git-receive-pack",
        "git-receive-pack ",
        "git-receive-pack foo git@example.org:user1/repo1",
        "git-receive-pack 'foo' 'git@example.org:user1/repo1'",
        "git-receive-pack git@example.org:user1/repo1 foo",
        "git-receive-pack 'git@example.org:user1/repo1' 'foo'",
        "git-receive-pack git@example.org:user1 repo1",
        "git-receive-pack 'git@example.org:user1' 'repo1'",
    ],
)
def test_invalid_arg_count(argv, config, env, value):
    env("SSH_ORIGINAL_COMMAND", value)

    with pytest.raises(server.ClientError, match="Expected exactly one argument"):
        server.main()


@pytest.mark.parametrize(
    "arg",
    [
        r"git@example.org:user1'repo1",
        r"'git@example.org:user1'repo1'",
        r"'git@example.org:user1\'repo1'",
    ],
)
@pytest.mark.parametrize(
    "cmd", ["git-receive-pack", "git-upload-archive", "git-upload-pack"]
)
def test_untokenizable_arg(argv, config, env, cmd, arg):
    env("SSH_ORIGINAL_COMMAND", f"{cmd} {arg}")

    with pytest.raises(server.ClientError, match="Failed to tokenize"):
        server.main()


@pytest.mark.parametrize(
    "arg",
    [
        "'git@example.org'",
        "'user1/repo1'",
        "'example.org:user1/repo1'",
        "'git@git@example.org:user1/repo1'",
        "'git@example.org:/user1/repo1'",  # technically valid, but dodgy
        "'git@example.org:user1/../user2/repo1'",  # ditto
        "'git@example.org:../:user1/repo1'",  # ditto
        "'git@example.org:user1 repo1'",  # ditto
        '''"git@example.org:user1'repo1"''',  # ditto
    ],
)
@pytest.mark.parametrize(
    "cmd", ["git-receive-pack", "git-upload-archive", "git-upload-pack"]
)
def test_invalid_arg_format(argv, config, env, cmd, arg):
    env("SSH_ORIGINAL_COMMAND", f"{cmd} {arg}")

    with pytest.raises(server.ClientError, match=f"Expected {cmd} parameter to be"):
        server.main()


@pytest.mark.parametrize(
    "arg",
    [
        "'git@example.org:user1/unknownrepo'",
        '"git@example.org:user1/unknownrepo"',
        "'git@example.org:user2/repo1'",
        "'git@foo.example.org:user4/repo4'",  # only allowed for the other client
    ],
)
@pytest.mark.parametrize(
    "cmd", ["git-receive-pack", "git-upload-archive", "git-upload-pack"]
)
def test_not_allowed(argv, config, env, cmd, arg):
    env("SSH_ORIGINAL_COMMAND", f"{cmd} {arg}")

    with pytest.raises(
        server.ClientError,
        match="Access to git@.* is not allowed",
    ):
        server.main()


def test_successful_simple(argv, config, env, mock_execl):
    # Duplicate of test_successful(), but with simpler test logic, just to be sure
    # the f-strings are not messed up in the same way in the test as in the real code
    mock_execl.side_effect = None

    env("SSH_ORIGINAL_COMMAND", "git-receive-pack 'git@example.org:user1/repo1'")

    server.main()

    mock_execl.assert_called_once_with(
        "/usr/bin/ssh",
        "/usr/bin/ssh",
        "git@example.org",
        "git-receive-pack user1/repo1",
    )


@pytest.mark.parametrize(
    "arg,expected_path",
    [
        ("git@example.org:user1/repo1", "user1/repo1"),
        ("'git@example.org:user1/repo1'", "user1/repo1"),
        ('"git@example.org:user1/repo2"', "user1/repo2"),
        ('"git@example.org:user2/repo3"', "user2/repo3"),
        ('"git@example.org:user3/unknownrepo"', "user3/unknownrepo"),
    ],
)
@pytest.mark.parametrize(
    "cmd", ["git-receive-pack", "git-upload-archive", "git-upload-pack"]
)
def test_successful(argv, config, env, mock_execl, cmd, arg, expected_path):
    mock_execl.side_effect = None

    env("SSH_ORIGINAL_COMMAND", f"{cmd} {arg}")

    server.main()

    mock_execl.assert_called_once_with(
        "/usr/bin/ssh", "/usr/bin/ssh", "git@example.org", f"{cmd} {expected_path}"
    )
