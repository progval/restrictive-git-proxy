# restrictive-git-proxy

A Git SSH proxy that allows each clients access to a different set of repositories


## Motivation

To contain the effects of malicious code in one of my projects (or my project's dependencies), I compartmentalize my projects, using some sort of isolation technology, like:

* separate UNIX users
* containers
* jails
* virtual machines
* separate physical computers

This works well to prevent one malicious project ('s dependency) from touching other data on my computers.

Each of these project environments has its own SSH key, which can push only to the project's forge.

However, most of these projects are on GitHub, which means each of these projects' environment can push to all my projects on GitHub.

GitHub provides a way to allow repository-specific keys, which they call [deploy keys](https://docs.github.com/en/developers/overview/managing-deploy-keys).
But this is quite limited: the same key cannot be allowed to access more than one repository. (This has been a known problem for [a while](https://stackoverflow.com/q/40515569/539465).)

So, when I want one of my SSH keys to access a larger subset of my repositories, I use this `restrictive-git-proxy`


## Principle of operation

`restrictive-git-proxy` runs on a proxy machine. Git clients connect to it via SSH, and it connects to a Git server (eg. GitHub).

`restrictive-git-proxy` has its own SSH key which is configured as an account key on the Git server; but it identifies client keys, and only grants them access to the Git server when they match the configuration.


```
+---------------------+
|  dev-chess@machine1 | --.
+---------------------+    \
                            \
+---------------------+      °-> +-----------------------+          +--------+
|   dev-go@machine1   | -------> | restrictive-git-proxy | -------> | GitHub |
+---------------------+      .-> +-----------------------+          +--------+
                            /
+---------------------+    /
| dev-hearts@machine2 | --°
+---------------------+
```


## Configuration

For each client machine, add this line to [`.ssh/authorized_keys`](https://manpages.debian.org/bullseye/openssh-server/authorized_keys.5.en.html#AUTHORIZED_KEYS_FILE_FORMAT):

```
command="/path/to/restrictive-git-proxy/server.py /path/to/my/config.json <client-name>",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty,no-user-rc,restrict <public key>
```

And make sure you replace:

* the two paths with the right values
* `<client-name>` with a unique name for the client
* `<public-key>` with the client's public SSH key (usually starting with `ssh-ed25519` or `ssh-rsa`)

The `config.json` file should be a JSON dictionary, with `<client-name>` as key and a list of allowed remotes as values. For example, assuming clients named `dev-chess@machine1` and `dev-go@machine1`:

```json
{
    "dev-chess@machine1": [
        "git@github.com:myself/chess-website",
        "git@github.com:myself/chess-ai"
    ],
    "dev-go@machine1": [
        "git@github.com:myself/go-website",
        "git@github.com:myself/go-ai"
    ]
}
```

Wildcards (`*` and `?`) are also allowed in values. (If you want full-blown regular expressions, replace `fnmatch.fnmatchcase` with `re.match` in the code, but beware of the extra complexity.)

In order to avoid abuse:

* the wildcards cannot match the `:` character between hostname and path
* matching is case-sensitive
* you should avoid using wildcards before the `:` character (but it is allowed)
* if the configuration allows wildcard, you should make sure the remote prevents path traversal (ie. rejects `../` in paths and leading `/`)

Then the Git client must be configured to use this remote: `git-proxy@localhost:git@github.com:myself/chess-website` instead of `git@github.com:myself/chess-website` (assuming `restrictive-git-proxy` is running as a local user named `git-proxy`).

Finally, the SSH executable is assumed to be `/usr/bin/ssh`. Edit it in the code if this is not true for you.

## Disclaimer

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY. See the LICENSE for more details.

In particular, its safety and security were not audited by a professional.

<!-- warning copied from https://github.com/diafygi/acme-tiny/#readme -->
**PLEASE READ THE SOURCE CODE AFTER DOWNLOADING! YOU MUST TRUST IT WITH YOUR PRIVATE ACCOUNT KEY!**


## Contributing

The code of `server.py` is kept simple so users can easily check it themselves, even with no advanced understanding of Python.
Therefore, major new features may be rejected (open a ticket so we can discuss it, though).

If you can think of exploit scenarios not covered by `test_server.py`, please add them or submit a ticket; even if they don't work (against the current implementation). Thanks!
