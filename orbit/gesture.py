"""Shift gesture state and logical-coordinate overlay placement."""
from dataclasses import dataclass, field

@dataclass
class Gesture:
    keys: set = field(default_factory=set)
    phase: str = 'idle'
    generation: int = 0

    def press(self, key):
        first = not self.keys
        self.keys.add(key)
        if first and self.phase == 'idle':
            self.generation += 1
            self.phase = 'probe'
            return True
        return False

    def release(self, key):
        self.keys.discard(key)
        if not self.keys and self.phase in {'probe', 'visible'}:
            self.cancel()
            return True
        return False

    def reveal(self):
        if self.keys and self.phase == 'probe':
            self.phase = 'visible'
            return True
        return False

    def cancel(self):
        self.phase = 'idle'
        self.generation += 1

    def drop(self):
        if self.phase == 'visible' and self.keys:
            self.phase = 'converting'
            return True
        return False


def placement(cursor, monitors, size=420):
    """hyprctl coordinates are logical; account for scale and rotated outputs."""
    for m in monitors:
        width, height = m['width'], m['height']
        if m.get('transform', 0) % 2:
            width, height = height, width
        width, height = width / m['scale'], height / m['scale']
        x, y = cursor['x'] - m['x'], cursor['y'] - m['y']
        if 0 <= x < width and 0 <= y < height:
            left = max(0, min(round(x - size / 2), max(0, int(width - size))))
            top = max(0, min(round(y - size / 2), max(0, int(height - size))))
            return m['name'], left, top, round(x - left), round(y - top)
    raise ValueError('Cursor is not on a connected monitor')
