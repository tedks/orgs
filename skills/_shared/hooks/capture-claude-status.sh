#!/usr/bin/env bash
# Capture the last observed Claude status payload for harness-control.
input=$(cat)

# A private, last-observed snapshot for harness-control. Keep this independent
# of rendering: malformed input or a full/read-only state directory must not
# stop the visible statusline. Same-directory rename publishes complete JSON.
# Only copy documented fields, never prompt data. The private transcript path
# lets lifecycle observers locate compaction events; public status omits it.
(
  umask 077
  session_id=$(printf '%s' "$input" | jq -ers '
    select(length == 1) | .[0] | select(type == "object") |
    .session_id | select(type == "string" and length == 36)') || exit 0
  [[ "$session_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] || exit 0
  state_dir="$HOME/.claude/session-state"
  mkdir -p "$state_dir" && chmod 700 "$state_dir" || exit 0
  status_tmp=$(mktemp "$state_dir/.status.XXXXXXXXXX") || exit 0
  trap 'rm -f -- "$status_tmp"' EXIT
  trap 'exit 0' HUP INT TERM
  printf '%s' "$input" | jq --argjson observed_at "$(date +%s)" '
    {schema_version: 1, observed_at: $observed_at, session_id,
     transcript_path: (.transcript_path | if type == "string" then . else null end),
     cwd: (.workspace.current_dir // .cwd),
     model: {id: .model.id, display_name: .model.display_name},
     context_window: {context_window_size: .context_window.context_window_size,
                     used_percentage: .context_window.used_percentage,
                     remaining_percentage: .context_window.remaining_percentage},
     rate_limits: ((.rate_limits // {}) |
       with_entries(select(.key == "five_hour" or .key == "seven_day" or .key == "spend_limit")) |
       map_values({used_percentage: .used_percentage, resets_at: .resets_at}))}
  ' > "$status_tmp" && mv -fT -- "$status_tmp" "$state_dir/$session_id.status.json"
) 2>/dev/null || :
