import time
from pytest import approx
from freezegun import freeze_time
from pypytools.gc.uniform import UniformGcStrategy

class FakeGcCollectStats(object):

    def __init__(self, major_is_done):
        self.major_is_done = major_is_done

class TestUniformGcStrategy(object):

    def new(self, initial_mem=0, **kwds):
        s = UniformGcStrategy(initial_mem)
        s.__dict__.update(**kwds)
        return s

    def test_target_memory(self):
        s = self.new(MAJOR_COLLECT=1.8,
                     GROWTH=1.5,
                     MIN_TARGET=50,
                     target_memory=200)
        #
        s.compute_target_memory(mem=100)
        assert s.target_memory == 180 # 100*1.8
        #
        s.compute_target_memory(mem=500)
        assert s.target_memory == 270 # 180*1.5, limited by GROWTH
        #
        s.compute_target_memory(mem=10)
        assert s.target_memory == 50  # MIN_TARGET

    def test_alloc_rate(self):
        with freeze_time('2018-01-01') as freezer:
            s = self.new(initial_mem=100)

            freezer.tick(0.5)           # 0.5 second
            s.tick(mem=150)             # delta_mem == 50
            assert s.alloc_rate == 100  # 50/0.5 bytes/s
            #
            freezer.tick(2)             # 2 seconds
            s.tick(mem=250)             # delta_mem == 100
            assert s.alloc_rate == 75   # because of the average
            #
            freezer.tick(1)
            s.tick(mem=100)             # negative delta_mem
            assert s.alloc_rate == 38   # capped at 1

    def test_alloc_rate_nonzero(self):
        s = self.new(initial_mem=100)
        s.tick(mem=90)
        assert s.alloc_rate == 1

    def test_get_time_for_next_step(self):
        s = self.new(initial_mem=0)
        s.gc_reset()
        # time to allocate 900 bytes:  9 s
        # time estimated for the GC:   1 s
        # total estimated time:       10 s
        # GC / total:                 10%
        s.target_memory = 900.0
        s.alloc_rate = 100.0 # bytes/s
        s.gc_estimated_t = 1
        # If the last step took 0.01 s, I wait for 0.09 to keep the expected
        # GC/total ration
        s.gc_last_step_t = 42
        s.gc_last_step_duration = 0.01
        t = s.get_time_for_next_step(mem=0)
        assert t == 42.09
        #
        # the result changes accordingly to the allocation rate: if I allocate
        # slower, I have more time to finish the collection
        s.alloc_rate = 10.0
        t = s.get_time_for_next_step(mem=0)
        assert t == 42.9
        #
        # if I allocate faster, I need to hurry up
        s.alloc_rate = 1000.0
        t = s.get_time_for_next_step(mem=0)
        assert t == 42.009

    def test_emergency_delay(self):
        # we are using too much memory and we have not finished the GC yet
        s = self.new(EMERGENCY_DELAY=3)
        s.gc_last_step_t = 39
        s.target_memory = 100
        assert s.get_time_for_next_step(100) == 42

    def test_should_collect(self):
        with freeze_time('1970-01-01') as freezer:
            s = self.new(initial_mem=0)
            # with the following params and an alloc_rate of 100 bytes/s, the
            # GC takes an estimated 10% of the time
            s.target_memory = 900.0
            s.gc_estimated_t = 1
            s.gc_last_step_duration = 0.01

            # so, we expect to run 9 iterations before doing one step
            mem = 0
            i = 0
            while True:
                freezer.tick(0.01)
                i += 1
                mem += 1
                should_collect = s.tick(mem=mem)
                assert s.alloc_rate == approx(100) # floating point rounding :(
                assert s.last_t == time.time()
                assert s.last_mem == mem
                if should_collect:
                    break
            assert i == 9

    def test_record_gc_step(self):
        s = self.new()
        s.gc_reset()
        s.record_gc_step(100, 2, FakeGcCollectStats(major_is_done=False))
        s.record_gc_step(110, 3, FakeGcCollectStats(major_is_done=False))
        s.record_gc_step(120, 1, FakeGcCollectStats(major_is_done=False))
        assert s.gc_cumul_t == 2+3+1
        assert s.gc_steps == 3
        assert s.last_mem == 120
        #
        s.record_gc_step(130, 1, FakeGcCollectStats(major_is_done=True))
        assert s.gc_cumul_t == 0
        assert s.gc_steps == 0
        assert s.last_mem == 130