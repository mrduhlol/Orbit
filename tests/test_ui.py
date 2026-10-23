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
        self.assertFalse(self.app.dropped(None, value, 50, 50))
        self.assertEqual(self.app.gesture.phase, 'idle')
        self.assertFalse(self.app.busy)

    def test_drag_leave_expires_only_current_drag(self):
        app = self.app
        generation, serial = app.gesture.generation, app.drag_serial
        app.drag_motion(None, 50, 25)
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

    def test_probe_accepts_offer_before_preload(self):
        self.app.gesture.phase = 'probe'
        self.app.options = []
        self.assertEqual(self.app.drag_motion(None, 50, 50), self.Gdk.DragAction.COPY)

    def test_wheel_is_more_compact(self):
        from orbit.app import SIZE
        hub = SIZE // 2
        self.assertEqual(SIZE, 100)
        self.assertEqual(self.app.window.get_default_size(), (100, 100))
        # A point inside the ring is still a selectable segment.
        self.assertEqual(self.app.hit(hub, hub - 30), 0)
        # A point beyond the outer radius is outside the wheel entirely.
        self.assertEqual(self.app.hit(hub, hub - 50), -1)

    def test_mixed_remote_selection_is_rejected_as_a_whole(self):
        value = self.Gdk.FileList.new_from_array([self.Gio.File.new_for_path(str(self.path)), self.Gio.File.new_for_uri('sftp://example.com/file.png')])
        self.assertEqual(self.app.local_paths(value), [])

    def test_uri_offer_is_accepted_before_actions_are_negotiated(self):
        from types import SimpleNamespace
        uri = self.Gdk.ContentFormats.new(['text/uri-list'])
        text = self.Gdk.ContentFormats.new(['text/plain'])
        self.assertTrue(self.app.accept_drop(None, SimpleNamespace(get_formats=lambda: uri)))
        self.assertFalse(self.app.accept_drop(None, SimpleNamespace(get_formats=lambda: text)))
        self.app.busy = True
        self.assertFalse(self.app.accept_drop(None, SimpleNamespace(get_formats=lambda: uri)))

    def test_hit_and_drag_feedback(self):
        app = self.app
        self.assertEqual(app.hit(50, 25), 0)
        self.assertEqual(app.hit(50, 50), -1)
        self.assertEqual(app.drag_motion(None, 50, 50), self.Gdk.DragAction(0))
        self.assertEqual(app.drag_motion(None, 50, 25), self.Gdk.DragAction.COPY)
        app.busy = True
        self.assertEqual(app.drag_motion(None, 50, 25), self.Gdk.DragAction(0))

    def test_draw_with_filename_and_hover(self):
        import cairo
        app = self.app
        app.hover = 0
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 100)
        app.draw(None, cairo.Context(surface), 100, 100)
        self.assertTrue(any(surface.get_data()))

if __name__ == '__main__':
    unittest.main()
