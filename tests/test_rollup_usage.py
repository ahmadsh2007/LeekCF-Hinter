import json
import unittest
from datetime import date, datetime, timezone

import httpx

from src.workers.usage.rollupUsage import (
    CloudflareUsageSource, DATASET, UsageSourceError, buildQuery, firstCompleteDay, readCredentials, run, toRows, windowDays,
)
from tests.fakeSupabase import FakeSupabase

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

def record(day="2026-10-20 00:00:00", route="hints", status="200", client="leekcf-ratings/3.0.1",
           requests="12", cache_hits="9", total="340.5"):
    return {"day": day, "route": route, "status": status, "client": client,
            "requests": requests, "cache_hits": cache_hits, "total_duration_ms": total}


class QueryTests(unittest.TestCase):
    def test_counts_are_weighted_by_the_sample_interval_and_grouped_per_day_route_status_and_app(self):
        query = buildQuery(7)
        self.assertIn(f"FROM {DATASET}", query)
        self.assertIn("SUM(_sample_interval)", query)          # Analytics Engine may sample; this undoes it
        self.assertIn("SUM(_sample_interval * double2)", query)  # cache hits
        self.assertIn("SUM(_sample_interval * double1)", query)  # response time
        self.assertIn("INTERVAL '1' DAY", query)
        self.assertIn("INTERVAL '7' DAY", query)
        self.assertIn("GROUP BY day, route, status, client", query)
        self.assertTrue(query.rstrip().endswith("FORMAT JSON"))

    def test_the_first_complete_day_skips_the_day_the_window_starts_in_the_middle_of(self):
        # now is 20 Oct 12:00 and the window reaches back 7 days: 13 Oct 12:00 onward, so 13 Oct is cut off
        self.assertEqual(firstCompleteDay(NOW, 7), date(2026, 10, 14))


class WindowTests(unittest.TestCase):
    today = date(2026, 10, 20)

    def test_the_default_window_is_used_when_the_last_export_is_recent_or_there_is_none(self):
        self.assertEqual(windowDays(None, self.today), 7)
        self.assertEqual(windowDays(date(2026, 10, 19), self.today), 7)

    def test_a_long_gap_widens_the_window_so_nothing_is_lost(self):
        # the last saved day was partial when it was saved, so it is read again: 20 Oct back to 1 Oct is 20 days
        self.assertEqual(windowDays(date(2026, 10, 1), self.today), 20)

    def test_the_window_never_goes_past_what_cloudflare_keeps(self):
        self.assertEqual(windowDays(date(2025, 1, 1), self.today), 90)


class RowTests(unittest.TestCase):
    first = date(2026, 10, 14)

    def test_numbers_arrive_as_text_and_leave_as_numbers(self):
        rows = toRows([record()], self.first)
        self.assertEqual(rows, [{"day": "2026-10-20", "route": "hints", "status": 200, "client": "leekcf-ratings/3.0.1",
                                 "requests": 12, "cache_hits": 9, "total_duration_ms": 340.5}])

    def test_days_before_the_first_complete_day_are_left_out_so_a_partial_day_never_overwrites_a_full_one(self):
        rows = toRows([record(day="2026-10-13 00:00:00"), record(day="2026-10-14 00:00:00")], self.first)
        self.assertEqual([r["day"] for r in rows], ["2026-10-14"])

    def test_a_row_that_does_not_look_like_the_query_stops_the_export_instead_of_saving_garbage(self):
        with self.assertRaises(UsageSourceError):
            toRows([{"day": "2026-10-20 00:00:00"}], self.first)
        with self.assertRaises(UsageSourceError):
            toRows([record(requests="many")], self.first)


class SourceTests(unittest.TestCase):
    def source(self, handler):
        return CloudflareUsageSource("ACCOUNT1", "SECRET-TOKEN", http=httpx.Client(transport=httpx.MockTransport(handler)))

    def test_it_posts_the_query_to_the_sql_api_of_the_account_with_the_token(self):
        seen = {}
        def handler(request):
            seen["url"], seen["auth"], seen["body"], seen["method"] = str(request.url), request.headers["authorization"], request.content.decode(), request.method
            return httpx.Response(200, json={"data": [record()], "rows": 1})
        records = self.source(handler).fetch(buildQuery(7))
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["url"], "https://api.cloudflare.com/client/v4/accounts/ACCOUNT1/analytics_engine/sql")
        self.assertEqual(seen["auth"], "Bearer SECRET-TOKEN")
        self.assertEqual(seen["body"], buildQuery(7))
        self.assertEqual(records, [record()])

    def test_a_refusal_is_reported_without_the_token(self):
        source = self.source(lambda request: httpx.Response(403, text="Authentication error"))
        with self.assertRaises(UsageSourceError) as raised:
            source.fetch(buildQuery(7))
        self.assertIn("403", str(raised.exception))
        self.assertNotIn("SECRET-TOKEN", str(raised.exception))

    def test_an_answer_that_is_not_json_is_a_clear_error(self):
        source = self.source(lambda request: httpx.Response(200, text="<html>nope</html>"))
        with self.assertRaises(UsageSourceError):
            source.fetch(buildQuery(7))


class CredentialsTests(unittest.TestCase):
    def test_both_values_are_needed(self):
        self.assertEqual(readCredentials({"CLOUDFLARE_ACCOUNT_ID": "a", "CLOUDFLARE_API_TOKEN": "t"}), ("a", "t"))
        self.assertIsNone(readCredentials({"CLOUDFLARE_ACCOUNT_ID": "a"}))
        self.assertIsNone(readCredentials({"CLOUDFLARE_API_TOKEN": "t"}))
        self.assertIsNone(readCredentials({"CLOUDFLARE_ACCOUNT_ID": "", "CLOUDFLARE_API_TOKEN": "t"}))
        self.assertIsNone(readCredentials({}))


class FakeSource:
    def __init__(self, records):
        self.records, self.queries = records, []
    def fetch(self, query):
        self.queries.append(query)
        return self.records


class RunTests(unittest.TestCase):
    def test_every_complete_day_is_upserted_on_its_natural_key(self):
        client = FakeSupabase({"api_usage_daily": []})
        source = FakeSource([record(day="2026-10-13 00:00:00"), record(), record(client="curl", requests="3")])
        saved = run(client, source, now=NOW, sleep=lambda s: None)
        self.assertEqual(saved, 2)
        [write] = client.writes("api_usage_daily", "upsert")
        self.assertEqual(write.onConflict, "day,client,route,status")
        self.assertEqual({row["client"] for row in write.payload}, {"leekcf-ratings/3.0.1", "curl"})
        self.assertIn("INTERVAL '7' DAY", source.queries[0])

    def test_nothing_is_written_when_there_is_no_traffic(self):
        client = FakeSupabase({"api_usage_daily": []})
        self.assertEqual(run(client, FakeSource([]), now=NOW, sleep=lambda s: None), 0)
        self.assertEqual(client.writes("api_usage_daily", "upsert"), [])

    def test_a_long_gap_since_the_last_export_widens_the_window(self):
        client = FakeSupabase({"api_usage_daily": [{"day": "2026-10-01"}, {"day": "2026-09-30"}]})
        source = FakeSource([])
        run(client, source, now=NOW, sleep=lambda s: None)
        self.assertIn("INTERVAL '20' DAY", source.queries[0])

    def test_a_dropped_connection_while_saving_is_retried(self):
        client = FakeSupabase({"api_usage_daily": []}, networkFailures={("api_usage_daily", "upsert"): 2})
        self.assertEqual(run(client, FakeSource([record()]), now=NOW, sleep=lambda s: None), 1)
        self.assertEqual(len(client.writes("api_usage_daily", "upsert")), 3)


if __name__ == "__main__":
    unittest.main()
