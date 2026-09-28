import unittest
from forgeapp.ratelimit import TokenBucket


class RateLimitTests(unittest.TestCase):
    def test_burst_then_block(self):
        bucket = TokenBucket(capacity=2, refill_per_sec=1.0)
        self.assertTrue(bucket.allow(0.0))
        self.assertTrue(bucket.allow(0.0))
        self.assertFalse(bucket.allow(0.0))

    def test_refill(self):
        bucket = TokenBucket(capacity=1, refill_per_sec=1.0)
        self.assertTrue(bucket.allow(0.0))
        self.assertTrue(bucket.allow(1.0))
