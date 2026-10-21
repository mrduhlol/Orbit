"""GTK callback tests. Run with GDK_BACKEND=broadway BROADWAY_DISPLAY=:19
ORBIT_UI_TESTS=1 /usr/bin/python -m unittest discover -s tests -p test_ui.py -v
while gtk4-broadwayd :19 is running. This is NOT a Wayland DND test.
"""
import os
import tempfile
import unittest
from pathlib import Path

@unittest.skipUnless(os.environ.get('ORBIT_UI_TESTS') == '1', 'requires explicit headless GTK session')
class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from orbit.app import Orbit
        from gi.repository import Gio, Gdk
        cls.Gio, cls.Gdk = Gio, Gdk
        cls.app = Orbit()
        cls.app.set_application_id('dev.orbit.CallbackTests')
        cls.app.register(None)
        cls.app.build()
        cls.directory = tempfile.TemporaryDirectory()
        cls.path = Path(cls.directory.name) / 'sample.png'
        from PIL import Image
        Image.new('RGB', (4, 4)).save(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.app.window.destroy()
        cls.app.release()
        cls.directory.cleanup()

    def setUp(self):
        from orbit.gesture import Gesture
        self.app.gesture = Gesture()
        self.app.busy = False
        self.app.set_gesture_mode(True)
        self.app.select([self.path])
        self.app.gesture.press('left')
        self.app.gesture.reveal()

    def test_center_drop_dismisses_without_converting(self):
        value = self.Gdk.FileList.new_from_array([self.Gio.File.new_for_path(str(self.path))])
        self.assertFalse(self.app.dropped(None, value, 210, 210))
        self.assertEqual(self.app.gesture.phase, 'idle')
        self.assertFalse(self.app.busy)

    def test_drag_leave_expires_only_current_drag(self):
        app = self.app
        generation, serial = app.gesture.generation, app.drag_serial
        app.drag_motion(None, 210, 69)
        app.expire_drag(generation, serial)
        self.assertEqual(app.gesture.phase, 'visible')
        app.expire_drag(generation, app.drag_serial)
        self.assertEqual(app.gesture.phase, 'idle')

    def test_old_probe_timeout_cannot_close_new_gesture(self):
        app = self.app
        generation = app.gesture.generation
        app.gesture.release('left')
        app.gesture.press('left')
        app.expire_probe(generation)
        self.assertEqual(app.gesture.phase, 'probe')

    def test_hit_and_drag_feedback(self):
        app = self.app
        self.assertEqual(app.hit(210, 69), 0)
        self.assertEqual(app.hit(210, 210), -1)
        self.assertEqual(app.drag_motion(None, 210, 210), self.Gdk.DragAction(0))
        self.assertEqual(app.drag_motion(None, 210, 69), self.Gdk.DragAction.COPY)
        app.busy = True
        self.assertEqual(app.drag_motion(None, 210, 69), self.Gdk.DragAction(0))

    def test_mixed_remote_selection_is_rejected_as_a_whole(self):
        value = self.Gdk.FileList.new_from_array([self.Gio.File.new_for_path(str(self.path)), self.Gio.File.new_for_uri('sftp://example.com/file.png')])
        self.assertEqual(self.app.local_paths(value), [])

    def test_probe_accepts_offer_before_preload(self):
        self.app.gesture.phase = 'probe'
        self.app.options = []
        self.assertEqual(self.app.drag_motion(None, 210, 210), self.Gdk.DragAction.COPY)

    def test_draw_with_filename_and_hover(self):
        import cairo
        app = self.app
        app.hover = 0
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 420, 420)
        app.draw(None, cairo.Context(surface), 420, 420)
        self.assertTrue(any(surface.get_data()))

if __name__ == '__main__':
    unittest.main()
