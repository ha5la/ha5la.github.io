import unittest
from datetime import date

import numpy as np

import geocaching_route as gr


class SunTimesTest(unittest.TestCase):
    def test_should_give_budapest_sunrise_and_sunset_on_2026_10_11(self):
        # referencia: api.sunrise-sunset.org, 06:55:16 és 18:05:53
        sunrise, sunset = gr.sun_times(47.4979, 19.0402, date(2026, 10, 11))
        self.assertAlmostEqual(sunrise.hour * 60 + sunrise.minute, 6 * 60 + 55, delta=3)
        self.assertAlmostEqual(sunset.hour * 60 + sunset.minute, 18 * 60 + 6, delta=3)


class RoadPointTest(unittest.TestCase):
    cache = (47.0, 19.0)

    def way(self, highway, lat):
        return {'tags': {'highway': highway}, 'geometry': [{'lat': lat, 'lon': 18.99}, {'lat': lat, 'lon': 19.01}]}

    def test_should_skip_motorway_even_if_closer(self):
        ways = [self.way('motorway', 47.0006), self.way('residential', 47.0010)]
        lat, lon = gr.road_point(self.cache, ways, [self.cache])
        self.assertAlmostEqual(lat, 47.0010, places=6)

    def test_should_skip_tracks_and_primary_roads(self):
        ways = [self.way('track', 47.0006), self.way('primary', 47.0007), self.way('unclassified', 47.0012)]
        lat, lon = gr.road_point(self.cache, ways, [self.cache])
        self.assertAlmostEqual(lat, 47.0012, places=6)

    def test_should_stay_at_least_50_m_from_every_cache(self):
        ways = [self.way('residential', 47.0)]  # az út a ládán megy át
        lat, lon = gr.road_point(self.cache, ways, [self.cache])
        self.assertGreaterEqual(gr.meters((lat, lon), self.cache), 50)
        self.assertLess(gr.meters((lat, lon), self.cache), 65)


class PlanTest(unittest.TestCase):
    def test_should_leave_out_cache_that_makes_return_too_late(self):
        # 0: otthon, 1: közeli láda, 2: távoli láda (60 perc oda és vissza)
        T = np.array([[0, 10, 60], [10, 0, 55], [60, 55, 0]], float)
        svc = np.array([0, 10, 10], float)
        fits = lambda out, field, back: out <= 60 and field <= 600 and field + back <= 80
        rt, _ = gr.plan(T, svc, fits, [1, 2])
        self.assertEqual(rt, [1])

    def test_should_return_empty_route_when_nothing_fits(self):
        T = np.array([[0, 90], [90, 0]], float)
        rt, _ = gr.plan(T, np.array([0, 10], float), lambda out, field, back: out <= 60, [1])
        self.assertEqual(rt, [])


if __name__ == '__main__':
    unittest.main()
