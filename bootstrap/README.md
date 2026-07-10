# bootstrap

Standalone setup helper for **Claude Code only**. `install.sh` registers plugin marketplaces,
installs plugins, and applies Claude Code settings (permissions, MCP servers, status line)
from the yaml files in `config/`. It drives the `claude` CLI and writes Claude Code config, so
it does nothing useful on Codex.

Codex has no equivalent one-shot script; use the documented manual steps in the
repo-root [README](../README.md) ("Install on Codex"). Automating those is
deferred until multi-machine setup pain justifies it.
