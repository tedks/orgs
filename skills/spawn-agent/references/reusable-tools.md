# Reusable orchestration tools

Preserve the useful capability, not a copy of every incident-specific script.

| Capability | Canonical home | Reuse status |
| --- | --- | --- |
| Guarded control-message transport | Dotfiles `spawn-agent/scripts/tmux-message.sh` | Blocking receipt confirmation, input stability checks, private deferred payloads, and one bounded Enter-only recovery; no automatic repaste. |
| Shared tmux read/write interface | Dotfiles `spawn-agent/scripts/tmux-message.sh` (`tmux-message`) | Sends actual text and confirms receipt from tmux; reads a stable pane directly, without agent registry, transcript or daemon prerequisites. |
| Interactive fork, guided compaction, tmux task delivery | Dotfiles `spawn-agent/scripts/agent-spawn.sh` | First-class existing fork flags plus executable/model options; no per-machine wrapper needed once adopted. |
| Quiet JSONL completion and compaction watcher | Dotfiles `spawn-agent/scripts/codex-jsonl-watch.py` | Already reusable: rollout or session ID, unique marker, cursor, timeout. Watches complete records, not tmux history. |
| Post-spawn IDE registration | Swarm IDE `tools/session-registration` | Existing opt-in tool. Caller supplies the known session/worktree/pane; not a dependency or automatic side effect of this launcher. |
| Completion notifications and ten-minute checkpoints | Swarm IDE `tools/supervisor` | Being packaged by the supervisor workstream. Keep its scheduling/configuration there; compose it with this launcher's rollout/cursor outputs. |
| Preview launcher | Swarm IDE development tooling | Useful extraction candidate: repository, display, port, profile and environment should be parameters. Existing machine-specific preview scripts are not yet a portable interface. |

Tmux provides the interactive session. A caller may use a user service manager
for independent preview/watcher lifetime and logs, but systemd is not a
requirement of this skill. Do not replace active supervisors or globally deploy
launcher changes in the middle of a work wave; adopt them deliberately.
