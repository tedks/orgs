#!/usr/bin/env bash
# Source through the installed skill tree; values are data, never shell code.
_AGENT_SKILLS_CONFIG_LOADER="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/agent_skills_config.py"
agent_skills_get() {
    python3 "$_AGENT_SKILLS_CONFIG_LOADER" get "$1"
}
