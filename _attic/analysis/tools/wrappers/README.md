# Wrappers

Use this directory for thin wrappers around external tools when needed.

Current design:

- local and vendored binaries are preferred first
- wrappers should remain small and inspectable
- any wrapper should record the real tool path and full command line in session manifests
