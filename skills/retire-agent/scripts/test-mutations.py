#!/usr/bin/env python3
"""Demonstrate that safety tests detect removed guards, without editing source."""
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
source = (HERE / 'retire.py').read_text()
builder_source = (HERE / 'build-index.py').read_text()
helper_source = (HERE.parents[1] / '_shared/offduty-push.sh').read_text()
# Cross-host duplicate-session protection now lives in the retry-time index
# builder and is exercised by test-offduty-push.py; the local lock is additive.
mutations = [
    ('missing shared reader blocks before offer', 'if not helper.is_file():', 'if False:', 'test_missing_shared_binding_blocks_before_offer'),
    ('pinned peer lookup PID', "pin = ProcessPin(actor['pid'], actor['start'], actor['boot'])", "pin = ProcessPin(os.getpid(), actor['start'], actor['boot'])", 'test_codex_offer_supplies_verified_id_and_resources'),
    ('ambiguous offer evidence verification', 'self.observe_ambiguous_offer()  # Recheck even a cached DONE before publication.', 'pass  # Drop ambiguous offer evidence verification.', 'test_ambiguous_offer_evidence_gate_runs_on_resume'),
    ('ambiguous offer never resends', 'if not ambiguous_offer:\n                        self.send(\'offer\', self.offer_payload(event, shard))', 'if True:\n                        self.send(\'offer\', self.offer_payload(event, shard))', 'test_ambiguous_offer_observed_done_resumes_without_replay'),
    ('ambiguous offer positive Enter', "or type(attempt.get('enters')) is not int or attempt['enters'] < 1", 'or False', 'test_ambiguous_offer_positive_input_and_shard_gates'),
    ('ambiguous offer pinned payload', "or attempt.get('payload') != str(expected)", 'or False', 'test_ambiguous_offer_positive_input_and_shard_gates'),
    ('ambiguous offer pinned digest', 'if len(actual) != size or hashlib.sha256(actual).hexdigest() != digest:', 'if False:', 'test_ambiguous_offer_rejects_changed_missing_or_symlink_payload'),
    ('ambiguous offer no live binding dependency', 'size, digest = attempt.get(\'payload_bytes\'), attempt.get(\'payload_sha256\')', 'self.native_binding()\n        size, digest = attempt.get(\'payload_bytes\'), attempt.get(\'payload_sha256\')', 'test_ambiguous_offer_uses_original_bytes_after_binding_disappears'),
    ('previous offer digest upgrade', 'if legacy:\n            original = self.offer_payload', 'if False:\n            original = self.offer_payload', 'test_previous_version_ambiguous_offer_is_verified_and_upgraded'),
    ('ambiguous cached DONE reobservation', "if ambiguous_offer or self.state.get('disposition') != 'DONE':", "if self.state.get('disposition') != 'DONE':", 'test_ambiguous_offer_rechecks_cached_done_after_bad_shard'),
    ('ambiguous caller decline reobservation', "if self.observe() != 'DECLINED':", 'if False:', 'test_ambiguous_offer_caller_decline_requires_current_marker'),
    ('narrowed event namespace', "r'[0-9a-f]{32}\\.json'", "r'[0-9a-f]{33}\\.json'", 'test_malformed_state_and_history_preserved'),
    ('history event filename identity', "if existing.stem != previous['id']:", 'if False:', 'test_historical_event_filename_id_mismatch_preserved'),
    ('native Codex UI footer', "and len(tail) == 1", 'and False', 'test_codex_ui_footer_allows_marker_completion'),
    ('Codex bullet footer variant', 's [·•] )?', 's · )?', 'test_codex_ui_bullet_footer_allows_marker_completion'),
    ('Codex footer harness attribution', "codex_footer = (agent == 'codex'", "codex_footer = (True", 'test_claude_cannot_use_codex_ui_footer'),
    ('Codex reply bullet footer witness', "and self.codex_final_marker('RETIRE-' + native_marker[1] + '-' + event)", 'and True', 'test_codex_footer_shaped_later_reply_stays_pending'),
    ('Codex declined bullet footer', "self.codex_final_marker('RETIRE-' + native_marker[1] + '-' + event)", "self.codex_final_marker('RETIRE-DONE-' + event)", 'test_codex_declined_reply_row_with_bullet_footer'),
    ('Codex cached witness before publication', "                if self.state.get('native_marker_witness'):", '                if False:', 'test_codex_cached_footer_witness_rechecked_before_publication'),
    ('Codex witness before exit', "            if self.state.get('native_marker_witness'):\n                disposition = self.state.get('disposition')", "            if False:\n                disposition = self.state.get('disposition')", 'test_codex_footer_witness_rechecked_before_exit'),
    ('desktop support server recognized', "if os.readlink(f'/proc/{pid}/exe') == executable:", 'if False:', 'test_desktop_codex_app_server_classifier_is_exact'),
    ('desktop support command exact', "and argv[1:] == [b'app-server', b'--listen', b'stdio://', b'']", 'and True', 'test_desktop_codex_app_server_classifier_is_exact'),
    ('desktop support binary exact', "and re.fullmatch(r'/nix/store/[0-9a-z]{32}-codex-desktop-[^/]+/lib/chatgpt/resources/codex', executable)", 'and True', 'test_desktop_codex_app_server_classifier_is_exact'),
    ('desktop support executable verified', "if os.readlink(f'/proc/{pid}/exe') == executable:", 'if True:', 'test_desktop_codex_app_server_classifier_is_exact'),
    ('desktop executable lookup fail closed', 'pass  # Unverified executable remains a possible harness actor.', 'return None  # Treat lookup failure as auxiliary.', 'test_desktop_codex_app_server_classifier_is_exact'),
    ('auxiliary parent keeps child reachability', "agent = 'codex-support'  # Keep the parent edge; only exclude from actor count.", 'return None  # Lose auxiliary parent before walking descendants.', 'test_auxiliary_parent_does_not_hide_nested_cli_actor'),
    ('mcp parent keeps child reachability', "agent = 'codex-support'  # Keep the parent edge for descendant CLI detection.", 'return None  # Lose MCP parent before walking descendants.', 'test_auxiliary_parent_does_not_hide_nested_cli_actor'),
    ('foreign private state namespace', "                           if re.fullmatch(r'[0-9a-f]{32}\\.json', path.name)", '', 'test_foreign_private_json_does_not_block_new_retirement'),
    ('long handoff observation', 'not 0 < args.wait <= 1800', 'not 0 < args.wait <= 600', 'test_twenty_minute_wait_is_accepted'),
    ('remote host', "'https://github.com/' + match[1]", 'match[1]', 'test_gh_privacy_pins_remote_host'),
    ('independent exit requires notice request', "raise Stop('handoff verified; original ended before exit request, fresh notice unavailable')", 'pass', 'test_independent_exit_after_handoff_remains_pending'),
    ('literal Claude exit', "control = ['--literal-exit'] if self.state['identity']['process']['agent'] == 'claude' else ['--typed-command']", "control = [] if self.state['identity']['process']['agent'] == 'claude' else ['--typed-command']", 'test_claude_literal_exit_real_terminal'),
    ('Codex typed exit composer guard', "else ['--typed-command']", 'else []', 'test_codex_stable_ordinary_draft_defers_typed_exit'),
    ('same-session exit notice', "re.escape(command) + r'(?i:' + re.escape(session_id) + r')[ \\t]*$'", "re.escape(command) + r'[0-9a-f-]+'", 'test_wrong_session_exit_notice_is_pending'),
    ('uppercase native exit UUID', "if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', session_id):", "if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', session_id):", 'test_uppercase_claude_pointer_matches_native_notice'),
    ('case-insensitive native notice UUID', "r'(?i:' + re.escape(session_id) + r')[ \\t]*$'", "r'(?:' + re.escape(session_id) + r')[ \\t]*$'", 'test_uppercase_claude_pointer_matches_native_notice'),
    ('exit notice required', 'self.ended() and self.fresh_exit_notice(session_id)', 'self.ended()', 'test_missing_exit_notice_is_pending'),
    ('Codex footer single row', 'and len(tail) == 1', 'and True', 'test_codex_ui_footer_never_hides_additional_prose'),
    ('Codex footer full row', 'and codex_footer_row.fullmatch(tail[0].rstrip())', 'and codex_footer_row.search(tail[0].rstrip())', 'test_codex_ui_footer_same_row_prose_is_pending'),
    ('exit requires attempted input', "or (attempt.get('status') == 'ambiguous' and attempt.get('input_attempted') is True)", "or (attempt.get('status') == 'deferred')", 'test_deferred_positive_enter_is_not_exit_request'),
    ('fresh exit notice baseline', "self.exit_notice_count(session_id) > baseline['before']", "self.exit_notice_count(session_id) >= baseline['before']", 'test_exit_notice_requires_native_banner_and_fresh_requested_input'),
    ('native exit notice banner', r"prefix + r'[ \t]*'", r"r'[ \t]*'", 'test_exit_notice_requires_native_banner_and_fresh_requested_input'),
    ('exit request positive Enter', "if not requested or type(attempt.get('enters')) is not int or attempt['enters'] < 1:", "if not requested or type(attempt.get('enters')) is not int:", 'test_exit_notice_requires_native_banner_and_fresh_requested_input'),
    ('exit original process pair', 'self.ended() and self.fresh_exit_notice(session_id)', 'self.fresh_exit_notice(session_id)', 'test_same_session_notice_cannot_retire_live_actor'),
    ('Codex footer UI padding', 'codex_footer_row.fullmatch(tail[0].rstrip())', 'codex_footer_row.fullmatch(tail[0])', 'test_codex_ui_footer_trailing_padding_is_allowed'),
    ('cached retired publication', "if self.state.get('status') == 'retired' and not self.exit_verified:", 'if False:', 'test_retired_resume_lost_pane_preserves_historical_receipt'),
    ('cached retired audit', "'exit_confirmed': self.exit_verified", "'exit_confirmed': self.state.get('status') == 'retired'", 'test_forged_retired_status_cannot_upgrade_pending_receipt'),
    ('native binding before exit baseline', "            self.verify_native_session(session_id)\n            if self.state.get('native_marker_witness'):", "            pass\n            if self.state.get('native_marker_witness'):", 'test_wrong_native_session_shard_never_requests_exit'),
    ('native binding before sender input', "            self.verify_native_session(preserved.get('session_id', 'unknown'))", '            pass', 'test_send_rechecks_binding_after_notice_baseline'),
    ('native UUID match', "if proof['session_id'] != session_id:", 'if False:', 'test_changed_binding_retry_never_requests_exit'),
    ('offered session remains authoritative', ["if self.state.get('native_session_id') and session_id != self.state['native_session_id']:", "if self.state.get('native_session_id') and preserved.get('session_id') != self.state['native_session_id']:"], ['if False:', 'if False:'], 'test_switched_native_session_cannot_replace_offered_id'),
    ('offer binding recheck', "        if phase == 'offer':\n            self.verify_native_session(self.state.get('native_session_id'))", "        if phase == 'offer':\n            pass", 'test_offer_rechecks_binding_before_sender_input'),
    ('offer session ID supplied', "binding = (f' The controller verified native session ID {session_id} for this pinned process. '", "binding = (f' Native session ID unavailable for this pinned process. '", 'test_codex_offer_supplies_verified_id_and_resources'),
    ('joined wrapped native exit notice', "['capture-pane', '-p', '-J', '-S', '-'", "['capture-pane', '-p', '-S', '-'", 'test_narrow_pane_joined_native_exit_notice'),
    ('native Claude UI footer', 'and 1 <= len(tail) <= 4', 'and False', 'test_claude_native_ui_footer_allows_marker_completion'),
    ('Claude footer harness attribution', "claude_footer = (agent == 'claude'", 'claude_footer = (True', 'test_codex_cannot_use_claude_ui_footer'),
    ('Claude wrapped status reassembly', 'for fragment in tail[2:4]:', 'for fragment in []:', 'test_claude_reply_row_with_wrapped_native_status'),
    ('Claude wrap boundary space', "for separator in ('', ' ')", "for separator in ('',)", 'test_claude_reply_row_with_space_at_wrap'),
    ('Claude single duration row', 'and 1 <= len(tail) <= 4', 'and 2 <= len(tail) <= 4', 'test_claude_real_reply_row_with_valid_shard'),
    ('Claude footer full row', "and re.fullmatch(r'✻ ", "and re.search(r'✻ ", 'test_claude_ui_footer_same_row_prose_is_pending'),
    ('Claude token row full suffix', "any(re.fullmatch(r' +[0-9]+ tokens', status) for status in claude_statuses)", 'True', 'test_claude_ui_footer_partial_tokens_is_pending'),
    ('loaded object', 'if not isinstance(record, dict):', 'if False:', 'test_malformed_state_and_history_preserved'),
    ('receipt before exit', ["self.publish_locked(['receipts/' + receipt.name], index=True)", "record = receipt_record(self.git('show', remote_head + ':' + self.state['handoff_receipt']))"], ['pass  # Withhold verified receipt publication until after exit.', "record = receipt_record((self.records / self.state['handoff_receipt']).read_text())"], 'test_retire_exit_to_shell_and_path_only_commit'),
    ('shard object', 'if not isinstance(data, dict):', 'if False:', 'test_nonobject_shard_is_controlled_failure'),
    ('private origin', "if run([checker, url]).returncode:", 'if False:', 'test_private_and_missing_remotes_before_send'),
    ('process identity', "if self.identity() != self.state['identity']:", 'if False:', 'test_changed_identity_and_malformed_state'),
    ('exit gate', 'while not (self.ended() and self.fresh_exit_notice(session_id)):', 'while False:', 'test_no_successor_before_exit'),
    ('safe shard', ["if path.is_symlink() or not path.is_file() or path.resolve() != self.path.parent / (self.state['id'] + '.shard'):", 'descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)'], ['if False:', 'descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)'], 'test_symlink_shard_blocks_exit'),
    ('DONE provenance', [r"r'^[●•] '", r"r'[●•] RETIRE-(DONE|DECLINED)-'"], [r"r'^(?:[●•] )?RETIRE-'", r"r'(?:[●•] )?RETIRE-(DONE|DECLINED)-'"], 'test_wrapped_user_done_does_not_complete'),
    ('validated snapshot', 'atomic_bytes(canonical, content)', 'atomic_bytes(canonical, shard.read_bytes())', 'test_validated_snapshot_ignores_later_symlink_swap'),
    ('lingering core', "for core in original.get('cores', []):", 'for core in []:', 'test_wrapper_exit_waits_for_lingering_core'),
    ('pinned socket', "self.tmux = ['tmux', '-S', state['socket']]", 'pass  # Caller environment selects the wrong server.', 'test_resume_uses_pinned_socket'),
    ('server failure', 'except PaneAbsent:', 'except Stop:', 'test_socket_failure_is_not_pane_disappearance'),
    ('composer exclusion', "rows = self.screen.read_response_rows(self.args.pane, self.state['socket'])", "rows = checked(self.tmux + ['capture-pane', '-p', '-t', self.args.pane]).splitlines()", 'test_claude_composer_done_does_not_complete'),
    ('last polling interval', 'disposition = self.observe()  # Include the final polling interval.', 'pass', 'test_last_poll_interval_is_observed'),
    ('recorded DONE', "if ambiguous_offer or self.state.get('disposition') != 'DONE':", 'if True:', 'test_saved_done_survives_cleared_screen'),
    ('initial remote receipt', "self.publish(['receipts/' + receipt.name])  # Local presence is not a remote receipt.", 'pass', 'test_failed_initial_push_is_verified_before_resumed_offer'),
    ('immutable successor brief', "preserved = self.git('show', self.state['shard_hash'], raw=True)", "preserved = (self.records / self.state['shard']).read_text()", 'test_handoff_brief_reads_verified_blob'),
    ('nonblocking shard snapshot', 'descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)', 'descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)', 'test_pending_fifo_swap_never_blocks'),
    ('receipt handoff status', "if record.get('status') not in ('handoff-verified', 'pending-exit', 'retired'):", 'if False:', 'test_remote_requested_receipt_cannot_authorize_successor'),
    ('owned atomic temporary', "descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '-', suffix='.tmp', dir=path.parent)", "descriptor, name = os.open(path.with_suffix('.tmp'), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), str(path.with_suffix('.tmp'))", 'test_foreign_adjacent_temp_preserved'),
    ('locked resume reread', 'self.load_resume()  # Another controller may have advanced state before this lock.', 'pass  # Trust stale pre-lock state.', 'test_resume_rereads_state_after_event_lock'),
    ('completion suffix', 'if tail and not (codex_footer or claude_footer):', 'if False:', 'test_codex_marker_suffix_is_not_completion'),
    ('pending evidence authority', "if self.state.get('handoff_receipt') and not getattr(self, 'evidence_verified', False):", 'if False:', 'test_remote_requested_receipt_cannot_authorize_successor'),
    ('padded completion marker', 'rows[position].rstrip()', 'rows[position]', 'test_padded_final_marker_completes'),
    ('receipt missing path', ['if evidence.returncode:', "if evidence.stdout.strip() != self.state['shard_hash']:"], ['if False:', 'if False:'], 'test_remote_bad_commit_receipt_never_self_heals'),
    ('receipt wrong blob', "if evidence.stdout.strip() != self.state['shard_hash']:", 'if False:', 'test_wrong_blob_receipt_never_self_heals'),
    ('index symlink', "if index.is_symlink() or (index.exists() and not index.is_file()):", 'if False:', 'test_index_symlink_preserves_outside_file'),
    ('index receipt identity', "if record['event'] != data['event']:", 'if False:', 'test_corrupt_other_receipt_preserves_generated_index'),
    ('corrupt index receipt', "raise ValueError('malformed retirement receipt') from error", 'continue', 'test_corrupt_other_receipt_preserves_generated_index'),
    ('remote base ownership', 'worktree add --quiet --detach "$worktree" "$fetched_ref"', 'worktree add --quiet --detach "$worktree" HEAD', 'test_unowned_local_commit_does_not_block_or_get_pushed'),
]
builder_mutations = {'index symlink', 'index receipt identity', 'corrupt index receipt'}
helper_mutations = {'remote base ownership'}
survivors = []
for label, before, after, test in mutations:
    if len(sys.argv) > 1 and label not in sys.argv[1:]:
        continue
    replacements = list(zip(before, after)) if isinstance(before, list) else [(before, after)]
    mutated = builder_source if label in builder_mutations else helper_source if label in helper_mutations else source
    for before, after in replacements:
        assert before in mutated, label
        mutated = mutated.replace(before, after, 2 if label == 'commit ownership' else 1)
    with tempfile.TemporaryDirectory(prefix='retire-mutation-') as directory:
        directory = Path(directory)
        directory = directory / 'skills/retire-agent/scripts'
        directory.mkdir(parents=True)
        shutil.copytree(HERE.parents[1] / '_shared', directory.parents[1] / '_shared')
        (directory / 'retire.py').write_text(mutated if label not in builder_mutations | helper_mutations else source)
        (directory / 'build-index.py').write_text(mutated if label in builder_mutations else builder_source)
        if label in helper_mutations:
            helper = directory.parents[1] / '_shared/offduty-push.sh'
            helper.write_text(mutated)
            helper.chmod(0o755)
        entry = directory / 'retire.sh'
        entry.write_bytes((HERE / 'retire.sh').read_bytes())
        entry.chmod(0o700)
        env = dict(os.environ, RETIRE_TEST_SCRIPT=str(entry))
        result = subprocess.run([sys.executable, str(HERE / 'test-retire.py'), 'Tests.' + test], env=env,
                                text=True, capture_output=True, timeout=30)
        if result.returncode == 0:
            survivors.append(label)
            print('SURVIVED: ' + label, flush=True)
            continue
        if 'INVALID-INSTRUMENTATION:' in result.stderr:
            raise SystemExit('Invalid mutation instrumentation: ' + label + '\n' + result.stderr)
        if 'FAILED' not in result.stderr:
            raise SystemExit('Invalid mutation test failure: ' + label + '\n' + result.stderr)
        print('KILLED: ' + label, flush=True)
if survivors:
    raise SystemExit('Surviving mutations: ' + ', '.join(survivors))
