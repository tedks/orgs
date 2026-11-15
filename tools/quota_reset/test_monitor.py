#!/usr/bin/env python3
"""Consequential boundaries for the quota reset consumer."""

import json
import importlib.util
import io
import multiprocessing
import os
import tempfile
import unittest
import sys
from threading import BrokenBarrierError
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.quota_reset import monitor

UTC = timezone.utc
T0 = datetime(2026, 11, 15, 1, 0, tzinfo=UTC)


def reading(used, observed, reset, *, minutes=300, scope="local-a", epoch="epoch-a", source="synthetic fixture"):
    return {
        "used_percent": used,
        "observed": observed.isoformat(),
        "resets_at": reset.isoformat(),
        "window_minutes": minutes,
        "source": source,
        "account_scope": scope,
        "account_epoch": epoch,
    }


def concurrent_tick(meters, state_path, log_path, now, barrier):
    original_load = monitor.load_state

    def synchronized_load(path):
        state = original_load(path)
        try:
            barrier.wait(timeout=1)
        except BrokenBarrierError:
            pass  # with a lock, the second process cannot load until this returns
        return state

    def sender(event):
        with open(log_path, "a", encoding="utf-8") as stream:
            stream.write(event["id"] + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return monitor.ACCEPTED
    monitor.load_state = synchronized_load
    try:
        monitor.process(meters, state_path, sender, now)
    finally:
        monitor.load_state = original_load


class MonitorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state.json"
        self.sent = []

    def run_tick(self, meters, now, sender=None):
        if sender is None:
            sender = lambda event: self.sent.append(event) or monitor.ACCEPTED
        return monitor.process(meters, self.state, sender, now)

    def test_observed_replenishment_once_across_repeats_and_restart(self):
        old_reset = T0 + timedelta(minutes=10)
        new_reset = old_reset + timedelta(hours=5)
        high = {"anthropic.five_hour": reading(95, T0, old_reset)}
        low = {"anthropic.five_hour": reading(4, T0 + timedelta(minutes=15), new_reset)}
        self.run_tick(high, T0 + timedelta(minutes=1))
        self.assertEqual(self.sent, [])  # first observation establishes baseline
        self.run_tick(low, T0 + timedelta(minutes=16))
        self.run_tick(low, T0 + timedelta(minutes=17))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["window_minutes"], 300)
        self.assertEqual(self.run_tick(low, T0 + timedelta(minutes=18))["accepted"], 0)
        self.assertEqual(len(self.sent), 1)

    def test_stale_offline_timestamp_only_and_out_of_order(self):
        old_reset = T0 + timedelta(minutes=10)
        self.run_tick({"anthropic.five_hour": reading(95, T0, old_reset)}, T0 + timedelta(minutes=1))
        # A later scan of the same saved record, even after its reset deadline, says nothing.
        self.run_tick({"anthropic.five_hour": reading(95, T0, old_reset)}, T0 + timedelta(hours=6))
        self.run_tick({}, T0 + timedelta(hours=6))
        # Fresh observations with no fall in usage, or no new reset epoch, say nothing.
        self.run_tick({"anthropic.five_hour": reading(95, T0 + timedelta(minutes=15), old_reset + timedelta(hours=5))}, T0 + timedelta(minutes=16))
        self.run_tick({"anthropic.five_hour": reading(5, T0 + timedelta(minutes=16), old_reset + timedelta(hours=5))}, T0 + timedelta(minutes=17))
        self.run_tick({"anthropic.five_hour": reading(1, T0 - timedelta(minutes=1), old_reset + timedelta(hours=5))}, T0 + timedelta(minutes=18))
        self.assertEqual(self.sent, [])

    def test_independent_windows_and_account_epoch_change(self):
        five = T0 + timedelta(minutes=10)
        weekly = T0 + timedelta(minutes=12)
        high = {
            "anthropic.five_hour": reading(95, T0, five),
            "anthropic.seven_day": reading(80, T0, weekly, minutes=10080),
        }
        low5 = {"anthropic.five_hour": reading(3, T0 + timedelta(minutes=15), five + timedelta(hours=5))}
        low7 = {"anthropic.seven_day": reading(2, T0 + timedelta(minutes=17), weekly + timedelta(days=7), minutes=10080)}
        self.run_tick(high, T0 + timedelta(minutes=1))
        self.run_tick(low5, T0 + timedelta(minutes=16))
        self.run_tick(low7, T0 + timedelta(minutes=18))
        self.assertEqual({e["window_minutes"] for e in self.sent}, {300, 10080})
        changed = {"anthropic.five_hour": reading(99, T0 + timedelta(minutes=19), five + timedelta(hours=10), epoch="epoch-b")}
        self.run_tick(changed, T0 + timedelta(minutes=20))
        self.assertEqual(len(self.sent), 2)
        saved = json.loads(self.state.read_text())
        self.assertEqual(len(saved["events"]), 2)

    def test_small_positive_replenishment_after_crossed_deadline(self):
        reset = T0 + timedelta(minutes=10)
        self.run_tick({"anthropic.five_hour": reading(4, T0, reset)}, T0 + timedelta(minutes=1))
        self.run_tick({"anthropic.five_hour": reading(0, T0 + timedelta(minutes=15), reset + timedelta(hours=5))}, T0 + timedelta(minutes=16))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["previous_used_percent"], 4)
        self.assertIn("replenishment observed since", self.sent[0]["message"])
        self.assertIn(self.sent[0]["previous_observed"], self.sent[0]["message"])
        self.assertIn(self.sent[0]["observed"], self.sent[0]["message"])
        self.assertEqual(self.sent[0]["remaining_percent"], 100)

    def test_long_gap_with_fresh_post_observation_reports_since_last_reading(self):
        reset = T0 + timedelta(minutes=10)
        self.run_tick({"anthropic.five_hour": reading(95, T0, reset)}, T0 + timedelta(minutes=1))
        low = {"anthropic.five_hour": reading(3, T0 + timedelta(hours=12), reset + timedelta(hours=15))}
        self.run_tick(low, T0 + timedelta(hours=12, minutes=1))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["previous_observed"], T0.isoformat())
        self.assertNotIn("now", self.sent[0]["message"])

    def test_long_gap_stale_or_unbound_post_does_not_alert(self):
        reset = T0 + timedelta(minutes=10)
        self.run_tick({"anthropic.five_hour": reading(95, T0, reset)}, T0 + timedelta(minutes=1))
        low = reading(3, T0 + timedelta(hours=12), reset + timedelta(hours=15))
        self.run_tick({"anthropic.five_hour": low}, T0 + timedelta(hours=13))
        self.assertEqual(self.sent, [])
        low["account_epoch"] = None
        result = self.run_tick({"anthropic.five_hour": low}, T0 + timedelta(hours=12, minutes=1))
        self.assertEqual(result["rejected"]["anthropic.five_hour"], "missing_identity")
        self.assertEqual(self.sent, [])

    def test_no_observed_decrease_does_not_alert(self):
        reset = T0 + timedelta(minutes=10)
        self.run_tick({"anthropic.five_hour": reading(0, T0, reset)}, T0 + timedelta(minutes=1))
        self.run_tick({"anthropic.five_hour": reading(0, T0 + timedelta(minutes=15), reset + timedelta(hours=5))}, T0 + timedelta(minutes=16))
        self.assertEqual(self.sent, [])

    def test_missing_identity_bad_window_and_future_or_stale_reading_fail_closed(self):
        reset = T0 + timedelta(minutes=10)
        bad = reading(90, T0, reset, epoch=None)
        result = self.run_tick({"anthropic.five_hour": bad}, T0 + timedelta(minutes=1))
        self.assertEqual(result["rejected"]["anthropic.five_hour"], "missing_identity")
        result = self.run_tick({"anthropic.five_hour": reading(90, T0, reset, minutes=10080)}, T0 + timedelta(minutes=1))
        self.assertEqual(result["rejected"]["anthropic.five_hour"], "unsupported_window")
        self.run_tick({"anthropic.five_hour": reading(10 ** 1000, T0, reset)}, T0 + timedelta(minutes=1))
        self.run_tick({"anthropic.five_hour": reading(90, T0, reset)}, T0 + timedelta(hours=1))
        self.run_tick({"anthropic.five_hour": reading(90, T0 + timedelta(minutes=5), reset)}, T0)
        self.assertFalse(self.state.exists())

    def test_crash_before_and_after_possible_send_never_replays_ambiguous_intent(self):
        reset = T0 + timedelta(minutes=10)
        self.run_tick({"openai.secondary": reading(90, T0, reset)}, T0 + timedelta(minutes=1))
        low = {"openai.secondary": reading(1, T0 + timedelta(minutes=15), reset + timedelta(hours=5))}

        def crash_before_send(_):
            raise RuntimeError("crash before external effect")

        with self.assertRaises(RuntimeError):
            self.run_tick(low, T0 + timedelta(minutes=16), crash_before_send)
        self.run_tick(low, T0 + timedelta(minutes=17))
        self.assertEqual(self.sent, [])
        saved = json.loads(self.state.read_text())
        self.assertEqual(next(iter(saved["events"].values()))["delivery"], "in_flight")

        # The same persisted state is also what a crash after an external acceptance leaves.
        self.state.unlink()
        self.run_tick({"openai.secondary": reading(90, T0, reset)}, T0 + timedelta(minutes=1))

        def crash_after_send(event):
            self.sent.append(event)
            raise RuntimeError("crash after external effect")

        with self.assertRaises(RuntimeError):
            self.run_tick(low, T0 + timedelta(minutes=16), crash_after_send)
        self.run_tick(low, T0 + timedelta(minutes=17))
        self.assertEqual(len(self.sent), 1)

    def test_delivery_failure_is_unknown_and_not_retried(self):
        reset = T0 + timedelta(minutes=10)
        self.run_tick({"openai": reading(90, T0, reset, minutes=10080)}, T0 + timedelta(minutes=1))
        low = {"openai": reading(2, T0 + timedelta(minutes=15), reset + timedelta(days=7), minutes=10080)}
        self.run_tick(low, T0 + timedelta(minutes=16), lambda _: monitor.UNKNOWN)
        self.run_tick(low, T0 + timedelta(minutes=17))
        self.assertEqual(self.sent, [])
        saved = json.loads(self.state.read_text())
        self.assertEqual(next(iter(saved["events"].values()))["delivery"], "unknown")

    def test_persisted_event_id_prevents_duplicate_after_replayed_baseline(self):
        reset = T0 + timedelta(minutes=10)
        high = {"openai.secondary": reading(90, T0, reset)}
        low = {"openai.secondary": reading(1, T0 + timedelta(minutes=15), reset + timedelta(hours=5))}
        self.run_tick(high, T0 + timedelta(minutes=1))
        before = json.loads(self.state.read_text())
        self.run_tick(low, T0 + timedelta(minutes=16))
        after = json.loads(self.state.read_text())
        after["series"] = before["series"]  # simulate recovered older baseline
        self.state.write_text(json.dumps(after))
        self.run_tick(low, T0 + timedelta(minutes=17))
        self.assertEqual(len(self.sent), 1)

    def test_new_reset_time_before_old_deadline_is_not_evidence(self):
        reset = T0 + timedelta(hours=1)
        self.run_tick({"openai.secondary": reading(95, T0, reset)}, T0 + timedelta(minutes=1))
        early = reading(2, T0 + timedelta(minutes=10), reset + timedelta(hours=5))
        self.run_tick({"openai.secondary": early}, T0 + timedelta(minutes=11))
        self.assertEqual(self.sent, [])

    def test_source_change_and_large_observation_gap_establish_new_baselines(self):
        reset = T0 + timedelta(minutes=10)
        high = {"anthropic.five_hour": reading(95, T0, reset)}
        self.run_tick(high, T0 + timedelta(minutes=1))
        changed = {"anthropic.five_hour": reading(2, T0 + timedelta(minutes=15), reset + timedelta(hours=5), source="new parser")}
        self.run_tick(changed, T0 + timedelta(minutes=16))
        self.assertEqual(self.sent, [])
        returned = {"anthropic.five_hour": reading(1, T0 + timedelta(minutes=20), reset + timedelta(hours=10))}
        self.run_tick(returned, T0 + timedelta(minutes=21))
        self.assertEqual(self.sent, [])  # never reuse source A's earlier high baseline
        much_later = {"anthropic.five_hour": reading(1, T0 + timedelta(hours=7), reset + timedelta(hours=10))}
        self.run_tick(much_later, T0 + timedelta(hours=7, minutes=1))
        self.assertEqual(self.sent, [])

    def test_return_to_old_account_epoch_is_a_new_baseline(self):
        reset = T0 + timedelta(minutes=10)
        self.run_tick({"openai.secondary": reading(90, T0, reset)}, T0 + timedelta(minutes=1))
        self.run_tick({"openai.secondary": reading(5, T0 + timedelta(minutes=15), reset + timedelta(hours=5), epoch="epoch-b")}, T0 + timedelta(minutes=16))
        self.run_tick({"openai.secondary": reading(4, T0 + timedelta(minutes=20), reset + timedelta(hours=10))}, T0 + timedelta(minutes=21))
        self.assertEqual(self.sent, [])

    def test_equal_timestamp_new_identity_can_be_pre_reset_baseline(self):
        reset = T0 + timedelta(minutes=10)
        self.run_tick({"openai.secondary": reading(80, T0, reset, source="A")}, T0 + timedelta(minutes=1))
        self.run_tick({"openai.secondary": reading(75, T0, reset, source="B")}, T0 + timedelta(minutes=1))
        self.run_tick({"openai.secondary": reading(1, T0 + timedelta(minutes=15), reset + timedelta(hours=5), source="B")}, T0 + timedelta(minutes=16))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["source"], "B")

    def test_source_cannot_create_second_event_id_for_one_reset(self):
        reset = T0 + timedelta(minutes=10)
        a = monitor.valid_reading("anthropic.five_hour", reading(1, T0 + timedelta(minutes=15), reset + timedelta(hours=5), source="A"), T0 + timedelta(minutes=16))
        b = monitor.valid_reading("anthropic.five_hour", reading(1, T0 + timedelta(minutes=15), reset + timedelta(hours=5), source="B"), T0 + timedelta(minutes=16))
        self.assertEqual(monitor.event_key(a), monitor.event_key(b))

    def test_concurrent_invocations_send_one_event(self):
        reset = T0 + timedelta(minutes=10)
        high = {"openai.secondary": reading(90, T0, reset)}
        low = {"openai.secondary": reading(1, T0 + timedelta(minutes=15), reset + timedelta(hours=5))}
        self.run_tick(high, T0 + timedelta(minutes=1))
        log = Path(self.temp.name) / "notifications.log"
        barrier = multiprocessing.Barrier(2)
        processes = [multiprocessing.Process(target=concurrent_tick,
                     args=(low, self.state, log, T0 + timedelta(minutes=16), barrier)) for _ in range(2)]
        for child in processes:
            child.start()
        for child in processes:
            child.join(5)
            self.assertEqual(child.exitcode, 0)
        self.assertEqual(len(log.read_text().splitlines()), 1)


def mutation_check():
    """Check that the suite kills regressions in freshness, reset and intent guards."""
    global monitor
    source = Path(monitor.__file__).read_text(encoding="utf-8")
    mutants = {
        "freshness": ("or now - observed > FRESH_FOR or reset <= observed", "or False or reset <= observed"),
        "reset crossing": ("prior_reset <= observed and reset > prior_reset", "reset > prior_reset"),
        "drop": ("previous[\"used_percent\"] > item[\"used_percent\"]", "True"),
        "durable intent": ("save_state(state_path, state)  # durable intent precedes the call", "pass  # removed durable intent"),
        "event dedup": ("if eid in state[\"events\"]:", "if False:"),
        "source transition": ("previous[\"identity\"] != identity", "False"),
        "window duration": ("type(window) is not int or window != minutes", "type(window) is not int"),
        "sender lock": ("fcntl.flock(lock, fcntl.LOCK_EX)", "pass  # removed sender lock"),
    }
    for label, (before, after) in mutants.items():
        if source.count(before) != 1:
            raise AssertionError(f"mutation anchor moved: {label}")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monitor.py"
            path.write_text(source.replace(before, after), encoding="utf-8")
            spec = importlib.util.spec_from_file_location("quota_reset_mutant", path)
            mutated = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mutated)
            original = monitor
            monitor = mutated
            try:
                suite = unittest.defaultTestLoader.loadTestsFromTestCase(MonitorTest)
                result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
                if result.wasSuccessful():
                    raise AssertionError(f"surviving guard mutation: {label}")
            finally:
                monitor = original
        print(f"killed: {label}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--mutation-check"]:
        mutation_check()
    else:
        unittest.main()
