"""
Vector Clock implementation for the distributed food delivery system.

Each process owns one VectorClock instance sized N (number of processes).
Rules implemented:
  - Internal event / Send event: increment own component.
  - Receive event: element-wise max with the incoming vector, then increment own component.
"""


class VectorClock:
    def __init__(self, n, index):
        self.n = n
        self.index = index
        self.vector = [0] * n

    def tick(self):
        """Called on an internal event or right before sending a message."""
        self.vector[self.index] += 1
        return self.vector.copy()

    def update(self, other_vector):
        """Called on receiving a message carrying `other_vector`."""
        self.vector = [max(a, b) for a, b in zip(self.vector, other_vector)]
        self.vector[self.index] += 1
        return self.vector.copy()

    @staticmethod
    def compare(v1, v2):
        """
        Compares two vector timestamps.
        Returns one of: 'equal', 'before' (v1 -> v2), 'after' (v2 -> v1), 'concurrent'.
        """
        le = all(a <= b for a, b in zip(v1, v2))
        ge = all(a >= b for a, b in zip(v1, v2))
        if le and ge:
            return "equal"
        elif le:
            return "before"
        elif ge:
            return "after"
        else:
            return "concurrent"
