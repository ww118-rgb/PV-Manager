"""Small independent tests of the PV Energiemanager distribution logic."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'custom_components' / 'pv_energiemanager'))
from engine import Consumer, distribute


class DistributionTests(unittest.TestCase):
    def c(self, ident, priority=1, subpriority=1, **kw):
        return Consumer(id=ident, priority=priority, subpriority=subpriority,
                        kind='continuous', minimum=1400, maximum=11000, **kw)

    def test_even_split(self):
        a, b = self.c('a'), self.c('b', subpriority=2)
        out = distribute(6000, [a, b])
        self.assertEqual(out.targets, {'a':3000, 'b':3000})

    def test_subpriority_admission(self):
        a, b = self.c('a'), self.c('b', subpriority=2)
        self.assertEqual(distribute(2000,[a,b]).targets, {'a':2000,'b':0})

    def test_no_demand(self):
        a = self.c('a', requested=False)
        b = self.c('b', priority=2)
        self.assertEqual(distribute(4000,[a,b]).targets, {'a':0,'b':4000})

    def test_measured_unused_flows_down(self):
        a = self.c('a', actual=6000, old_target=11000, feedback_settled=True)
        b = self.c('b', subpriority=2, actual=10000, old_target=11000, feedback_settled=True)
        c = Consumer('c',2,1,'continuous',500,3000)
        out = distribute(22000,[a,b,c])
        self.assertEqual(out.targets['c'],3000)

    def test_no_feedback_keeps_higher_budget(self):
        a, b = self.c('a'),self.c('b',subpriority=2)
        c = Consumer('c',2,1,'continuous',500,3000)
        self.assertEqual(distribute(22000,[a,b,c]).targets['c'],0)

    def test_discrete_steps(self):
        a = Consumer('a',1,1,'stepped',500,2000,(500,1000,1500,2000))
        self.assertEqual(distribute(1800,[a]).targets['a'],1500)

if __name__ == '__main__':
    unittest.main()

class NativeStepAwareAllocationTests(unittest.TestCase):
    def test_two_wallboxes_stepwise_just_under_8_amp_budget(self):
        wallboxes = [Consumer(id=f"wb{i}", priority=2, subpriority=i,
                             kind="continuous", minimum=4140, maximum=11040,
                             step_w=690) for i in (1, 2)]
        hp = Consumer(id="hp", priority=1, subpriority=1,
                      kind="continuous", minimum=5000, maximum=20000, step_w=1)
        result = distribute(31000, [hp, *wallboxes])
        self.assertEqual(result.targets["hp"], 20000)
        self.assertEqual(result.targets["wb1"], 5520)
        self.assertEqual(result.targets["wb2"], 4830)
        self.assertEqual(sum(result.targets.values()), 30350)

    def test_two_wallboxes_stable_above_8_amp_threshold(self):
        wb = [Consumer(id=f"wb{i}", priority=1, subpriority=i,
                       kind="continuous", minimum=4140, maximum=11040,
                       step_w=690) for i in (1, 2)]
        for budget in (11190, 11210):
            result = distribute(budget, wb)
            self.assertEqual(result.targets, {"wb1": 5520, "wb2": 5520})

    def test_unreachable_max_does_not_block_lower_priority(self):
        wb = Consumer(id="wb", priority=1, subpriority=1,
                      kind="continuous", minimum=4140, maximum=11000, step_w=690)
        lower = Consumer(id="lower", priority=2, subpriority=1,
                         kind="continuous", minimum=100, maximum=2000)
        result = distribute(11100, [wb, lower])
        self.assertEqual(result.targets["wb"], 10350)
        self.assertEqual(result.targets["lower"], 700)

    def test_legacy_continuous_still_uses_100_w_quantum(self):
        old = Consumer(id="x", priority=1, subpriority=1,
                       kind="continuous", minimum=100, maximum=1000)
        self.assertEqual(distribute(700, [old]).targets["x"], 700)
