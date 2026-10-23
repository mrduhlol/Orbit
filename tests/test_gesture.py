import unittest
from orbit.gesture import Gesture, placement

class GestureTests(unittest.TestCase):
    def test_release_cancels_and_invalidates_timeout(self):
        g = Gesture()
        self.assertTrue(g.press('left'))
        old = g.generation
        self.assertTrue(g.reveal())
        self.assertTrue(g.release('left'))
        self.assertNotEqual(old, g.generation)
        self.assertFalse(g.drop())
        self.assertFalse(g.reveal())

    def test_two_shifts_and_completed_drop(self):
        g = Gesture()
        self.assertTrue(g.press('left'))
        self.assertFalse(g.press('right'))
        self.assertFalse(g.release('left'))
        self.assertTrue(g.reveal())
        self.assertTrue(g.drop())
        self.assertFalse(g.release('right'))
        self.assertEqual(g.phase, 'converting')
        g.cancel()
        self.assertTrue(g.press('left'))

    def test_expired_probe_does_not_reopen_while_held(self):
        g = Gesture()
        g.press('left')
        g.cancel()
        self.assertFalse(g.press('left'))
        g.release('left')
        self.assertTrue(g.press('left'))

    def test_scaled_negative_and_rotated_monitors(self):
        monitors = [dict(name='left', x=-1536, y=0, width=1920, height=1080, scale=1.25),
                    dict(name='portrait', x=0, y=0, width=1920, height=1080, scale=1, transform=1)]
        self.assertEqual(placement(dict(x=-1000, y=400), monitors), ('left', 486, 350, 50, 50))
        self.assertEqual(placement(dict(x=-10, y=850), monitors), ('left', 1436, 764, 90, 86))
        self.assertEqual(placement(dict(x=1000, y=1800), monitors), ('portrait', 950, 1750, 50, 50))
        with self.assertRaises(ValueError):
            placement(dict(x=99999, y=0), monitors)

if __name__ == '__main__':
    unittest.main()
