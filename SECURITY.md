# Security and privacy

JSpace indexes private research material, so privacy regressions are security issues.

Please report vulnerabilities through GitHub's private vulnerability reporting or a private security advisory. Do not attach real conversation logs, experiment outputs, PDFs, SQLite databases, access tokens, or machine-specific paths; use a minimal synthetic reproduction instead.

The default server binds to `127.0.0.1`. Changing `--host` can expose the workbench to other devices, and the built-in server does not provide authentication or TLS. Keep the default binding unless the surrounding network and access controls are understood.

The `.data/` directory is disposable local state and must remain untracked. Deleting it removes the local index and workbench notes, not the original conversations, experiment files, or PDFs.
