"""Vector clock implementation for the distributed food-delivery system."""
import threading


class VectorClock:
    def __init__(self, process_id, all_processes):
        self.process_id = process_id
        self.processes = sorted(all_processes)
        self._lock = threading.Lock()
        self.clock = {p: 0 for p in self.processes}

    def tick(self):
        """Internal or send event: increment own component."""
        with self._lock:
            self.clock[self.process_id] += 1
            return dict(self.clock)

    def merge(self, received_clock):
        """Receive event: component-wise max with sender's clock, then own increment."""
        with self._lock:
            for p in self.processes:
                self.clock[p] = max(self.clock[p], received_clock.get(p, 0))
            self.clock[self.process_id] += 1
            return dict(self.clock)

    def snapshot(self):
        with self._lock:
            return dict(self.clock)


def compare(vc_a, vc_b):
    """Return 'A happened-before B', 'B happened-before A', 'equal', or 'concurrent'."""
    keys = set(vc_a) | set(vc_b)
    le = all(vc_a.get(k, 0) <= vc_b.get(k, 0) for k in keys)
    ge = all(vc_a.get(k, 0) >= vc_b.get(k, 0) for k in keys)
    if le and ge:
        return "equal"
    if le:
        return "A happened-before B"
    if ge:
        return "B happened-before A"
    return "concurrent"
