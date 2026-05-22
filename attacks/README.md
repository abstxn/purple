# Atomic Red Team

This directory is intended to hold the [Atomic Red Team](https://github.com/redcanaryco/atomic-red-team) repository as a Git submodule.

## Initialise

```bash
git submodule add https://github.com/redcanaryco/atomic-red-team attacks/atomics
git submodule update --init --recursive
```

After initialising, the red agent will index YAML tests under `atomics/atomics/`.
