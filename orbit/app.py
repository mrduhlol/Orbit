import math
import json
import subprocess
import cairo
from pathlib import Path
import threading
import gi
# Load layer-shell before GTK initializes the Wayland connection.
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gtk4LayerShell as Layer
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Gio, GLib
from .converter import common_formats, convert
from .gesture import Gesture, placement

SIZE = 420
CENTER = 210

class Orbit(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='dev.orbit.Converter', flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None
        self.paths = []
        self.options = []
        self.hover = -1
        self.busy = False
        self.message = 'Drop files into the orbit'
        self.outputs = []
        self.gesture = Gesture()
        self.gesture_mode = False
        self.probe_point = (CENTER, CENTER)
        self.layer_supported = False
        self.drag_serial = 0

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()
        cancel = Gio.SimpleAction.new('cancel-gesture', None)
        cancel.connect('activate', lambda *_: self.close_panel())
        self.add_action(cancel)
        for side in ('left', 'right'):
            for state in ('down', 'up'):
                action = Gio.SimpleAction.new(f'shift-{side}-{state}', None)
                action.connect('activate', self.shift_action, side, state)
                self.add_action(action)

    def do_command_line(self, command):
        args = command.get_arguments()[1:]
        if args == ['--daemon']:
            return 0
        self.do_activate()
        if args and not self.busy:
            self.select([Path(command.create_file_for_arg(arg).get_path()) for arg in args])
        return 0

    def shift_action(self, action, parameter, side, state):
        if state == 'up':
            if self.gesture.release(side) and self.gesture_mode:
                self.window.set_visible(False)
            return
        if self.busy or (self.window and self.window.get_visible() and not self.gesture_mode):
            return
        if not self.gesture.press(side):
            return
        if self.window is None:
            self.build()
        if not self.layer_supported:
            self.gesture.cancel()
            return
        try:
            cursor = json.loads(subprocess.check_output(['hyprctl', 'cursorpos', '-j'], timeout=1))
            monitors = json.loads(subprocess.check_output(['hyprctl', 'monitors', '-j'], timeout=1))
            name, left, top, px, py = placement(cursor, monitors)
            monitor = next(m for m in Gdk.Display.get_default().get_monitors() if m.get_connector() == name)
        except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
            self.gesture.cancel()
            return
        self.set_gesture_mode(True)
        self.paths, self.options, self.hover = [], [], -1
        self.probe_point = (px, py)
        Layer.set_monitor(self.window, monitor)
        Layer.set_anchor(self.window, Layer.Edge.LEFT, True)
        Layer.set_anchor(self.window, Layer.Edge.TOP, True)
        Layer.set_margin(self.window, Layer.Edge.LEFT, left)
        Layer.set_margin(self.window, Layer.Edge.TOP, top)
        self.window.present()
        self.update_input_region()
        self.area.queue_draw()
        GLib.timeout_add(800, self.expire_probe, self.gesture.generation)

    def expire_probe(self, generation):
        if generation == self.gesture.generation and self.gesture.phase == 'probe':
            self.gesture.cancel()
            self.window.set_visible(False)
        return False

    def set_gesture_mode(self, enabled):
        self.gesture_mode = enabled
        for widget in self.chrome:
            widget.set_visible(not enabled)
        if enabled:
            self.panel.remove_css_class('panel')
        else:
            self.panel.add_css_class('panel')
        if self.layer_supported:
            Layer.set_keyboard_mode(self.window, Layer.KeyboardMode.NONE if enabled else Layer.KeyboardMode.ON_DEMAND)
        self.window.set_default_size(SIZE if enabled else 454, SIZE if enabled else 600)

    def update_input_region(self, *_):
        surface = self.window.get_surface()
        if surface is None:
            return
        if not self.gesture_mode:
            surface.set_input_region(None)
        elif self.gesture.phase == 'probe':
            x, y = self.probe_point
            surface.set_input_region(cairo.Region(cairo.RectangleInt(max(0, x - 32), max(0, y - 32), min(64, SIZE - max(0, x - 32)), min(64, SIZE - max(0, y - 32)))))
        else:
            region = cairo.Region()
            for y in range(15, 406):
                half = int(math.sqrt(max(0, 195 ** 2 - (y - CENTER) ** 2)))
                region.union(cairo.RectangleInt(CENTER - half, y, half * 2, 1))
            surface.set_input_region(region)

    def close_panel(self, *_):
        if not self.busy:
            self.gesture.cancel()
            self.window.set_visible(False)
        return True

    def do_activate(self):
        if self.window is None:
            self.build()
        self.gesture.cancel()
        self.set_gesture_mode(False)
        if self.layer_supported:
            for edge in (Layer.Edge.TOP, Layer.Edge.LEFT):
                Layer.set_anchor(self.window, edge, False)
                Layer.set_margin(self.window, edge, 0)
        self.window.present()
        self.update_input_region()

    def do_open(self, files, count, hint):
        self.do_activate()
        if not self.busy:
            self.select([Path(f.get_path()) for f in files if f.get_path()])

    def build(self):
        self.window = Gtk.ApplicationWindow(application=self, title='Orbit')
        self.window.set_decorated(False)
        self.window.set_resizable(False)
        if 'Wayland' in type(Gdk.Display.get_default()).__name__ and Layer.is_supported():
            self.layer_supported = True
            Layer.init_for_window(self.window)
            Layer.set_namespace(self.window, 'orbit')
            Layer.set_layer(self.window, Layer.Layer.OVERLAY)
            Layer.set_keyboard_mode(self.window, Layer.KeyboardMode.ON_DEMAND)
        css = Gtk.CssProvider()
        css.load_from_data(b'window { background: transparent; } .panel { background: #191e29; border: 1px solid #364052; border-radius: 24px; padding: 16px; color: #e6edf5; } button { border-radius: 12px; } .hint { color: #9aa9bc; font-size: 12px; }')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.panel = box
        box.add_css_class('panel')
        self.window.set_child(box)
        header = Gtk.Box()
        title = Gtk.Label(label='O R B I T', hexpand=True, xalign=0)
        header.append(title)
        close = Gtk.Button(label='×', tooltip_text='Close')
        close.connect('clicked', self.close_panel)
        header.append(close)
        box.append(header)
        self.area = Gtk.DrawingArea(content_width=SIZE, content_height=SIZE)
        self.area.set_draw_func(self.draw)
        box.append(self.area)
        self.status = Gtk.Label(label=self.message, wrap=True, max_width_chars=48)
        box.append(self.status)
        hint = Gtk.Label(label='Local conversion · Originals stay untouched')
        hint.add_css_class('hint')
        box.append(hint)
        buttons = Gtk.Box(spacing=8, homogeneous=True)
        self.choose = Gtk.Button(label='Choose files')
        self.choose.connect('clicked', self.browse)
        buttons.append(self.choose)
        self.reveal = Gtk.Button(label='Open output folder', sensitive=False)
        self.reveal.connect('clicked', lambda *_: Gio.AppInfo.launch_default_for_uri(self.outputs[-1].parent.as_uri(), None))
        buttons.append(self.reveal)
        box.append(buttons)
        self.format_row = Gtk.Box(spacing=4, homogeneous=True)
        box.append(self.format_row)
        self.chrome = [header, self.status, hint, buttons, self.format_row]
        self.window.connect('map', self.update_input_region)
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.set_preload(True)
        drop.connect('notify::value', self.preload)
        drop.connect('enter', self.drag_motion)
        drop.connect('motion', self.drag_motion)
        drop.connect('drop', self.dropped)
        drop.connect('leave', self.drag_leave)
        self.area.add_controller(drop)
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self.motion)
        motion.connect('leave', lambda *_: self.motion(None, -1, -1))
        self.area.add_controller(motion)
        click = Gtk.GestureClick()
        click.connect('released', lambda _, n, x, y: self.start(self.hit(x, y)))
        self.area.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self.key)
        self.window.add_controller(keys)
        self.window.connect('close-request', self.close_panel)

    def key(self, _, key, code, state):
        if key == Gdk.KEY_Escape and not self.busy:
            self.close_panel()
            return True
        return False

    def set_message(self, message):
        self.message = message
        self.status.set_text(message)
        self.area.queue_draw()

    def select(self, paths):
        self.paths = paths
        self.options = common_formats(paths)
        self.hover = -1
        while child := self.format_row.get_first_child():
            self.format_row.remove(child)
        for i, fmt in enumerate(self.options):
            button = Gtk.Button(label=fmt, tooltip_text=f'Convert to {fmt}')
            button.connect('clicked', lambda _, index=i: self.start(index))
            self.format_row.append(button)
        self.set_message(('Choose an output format · ' + (paths[0].name if len(paths) == 1 else f'{len(paths)} files')) if self.options else 'No shared supported format. Try images, PDFs, audio, or video.')

    @staticmethod
    def local_paths(value):
        paths = [f.get_path() for f in value.get_files()]
        # Never silently convert only part of a mixed local/remote selection.
        return [Path(path) for path in paths] if paths and all(paths) else []

    def preload(self, drop, _):
        value = drop.get_value()
        if value and not self.busy:
            if self.gesture_mode and self.gesture.phase not in {'probe', 'visible'}:
                return
            paths = self.local_paths(value)
            if self.gesture_mode:
                if not common_formats(paths):
                    self.close_panel()
                    return
                self.gesture.reveal()
                self.update_input_region()
            self.select(paths)

    def dropped(self, _, value, x, y):
        if self.busy:
            return False
        self.drag_serial += 1
        paths = self.local_paths(value)
        if not paths:
            return False
        if self.gesture_mode and self.gesture.phase != 'visible':
            return False
        self.select(paths)
        index = self.hit(x, y)
        if self.gesture_mode:
            if index < 0 or not self.gesture.drop():
                self.close_panel()
                return False
            self.window.set_visible(False)
        self.start(index)
        return bool(self.options)

    def drag_leave(self, *_):
        self.motion(None, -1, -1)
        self.drag_serial += 1
        # Layer input-region changes can generate a transient leave/enter pair.
        # A generation token prevents that leave from closing a newer drag.
        if self.gesture_mode:
            GLib.timeout_add(250, self.expire_drag, self.gesture.generation, self.drag_serial)

    def expire_drag(self, generation, serial):
        if (self.gesture_mode and generation == self.gesture.generation
                and serial == self.drag_serial and self.gesture.phase == 'visible'):
            self.close_panel()
        return False

    def drag_motion(self, _, x, y):
        self.drag_serial += 1
        self.motion(None, x, y)
        accepted = not self.busy and (not self.gesture_mode or self.gesture.phase == 'probe' or self.hover >= 0)
        return Gdk.DragAction.COPY if accepted else Gdk.DragAction(0)

    def hit(self, x, y):
        dx, dy = x - CENTER, y - CENTER
        if not self.options or not 91 < math.hypot(dx, dy) < 191:
            return -1
        step = math.tau / len(self.options)
        angle = (math.atan2(dy, dx) + math.pi / 2 + step / 2) % math.tau
        # Match the visible gutter; dropping between formats must not choose one.
        if angle % step < .025 or angle % step > step - .025:
            return -1
        return int(angle / step)

    def motion(self, _, x, y):
        self.hover = self.hit(x, y)
        self.area.queue_draw()

    def browse(self, *_):
        dialog = Gtk.FileDialog(title='Choose files to convert')
        dialog.open_multiple(self.window, None, self.chosen)

    def chosen(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
            self.select([Path(f.get_path()) for f in files if f.get_path()])
        except GLib.Error:
            pass

    def start(self, index):
        if self.busy or index < 0 or index >= len(self.options):
            return
        target, paths = self.options[index], list(self.paths)
        self.busy = True
        self.choose.set_sensitive(False)
        self.format_row.set_sensitive(False)
        self.set_message(f'Converting {len(paths)} file(s) to {target}…')
        threading.Thread(target=self.work, args=(paths, target), daemon=True).start()

    def work(self, paths, target):
        outputs, errors = [], []
        for path in paths:
            try:
                outputs.extend(convert(path, target))
            except Exception as exc:
                errors.append(f'{path.name}: {exc}')
        GLib.idle_add(self.finished, outputs, errors)

    def finished(self, outputs, errors):
        self.busy = False
        self.outputs = outputs
        self.choose.set_sensitive(True)
        self.format_row.set_sensitive(True)
        self.reveal.set_sensitive(bool(outputs))
        message = f'Saved {len(outputs)} file(s) beside the originals.' if outputs else 'Conversion failed.'
        if errors:
            message += '\n' + '\n'.join(errors)
        self.set_message(message)
        if self.gesture_mode:
            self.gesture.cancel()
            notification = Gio.Notification.new('Orbit — conversion failed' if errors else 'Orbit — conversion complete')
            notification.set_body(message)
            self.send_notification('conversion', notification)
        return False

    def draw(self, _, cr, w, h):
        if self.gesture_mode and self.gesture.phase == 'probe':
            return
        options = self.options or ['PNG', 'JPG', 'WEBP', 'PDF', 'MP3', 'MP4']
        step = math.tau / len(options)
        for i, label in enumerate(options):
            mid = -math.pi / 2 + i * step
            a, b = mid - step / 2 + .025, mid + step / 2 - .025
            cr.new_path()
            cr.arc(CENTER, CENTER, 191, a, b)
            cr.arc_negative(CENTER, CENTER, 91, b, a)
            cr.close_path()
            active = i == self.hover and bool(self.options) and not self.busy
            cr.set_source_rgb(*((.64, .84, .66) if active else (.15, .19, .25)))
            cr.fill_preserve()
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.set_line_width(7)
            cr.stroke_preserve()
            cr.set_source_rgba(.65, .78, .89, .18)
            cr.set_line_width(1)
            cr.stroke()
            self.text(cr, label, CENTER + 141 * math.cos(mid), CENTER + 141 * math.sin(mid), 17, (.08, .13, .13) if active else (.85, .9, .95))
        cr.arc(CENTER, CENTER, 76, 0, math.tau)
        cr.set_source_rgb(.10, .13, .17)
        cr.fill()
        heading = 'Converting' if self.busy else ('ORBIT' if not self.paths else f'{len(self.paths)} FILE' + ('S' if len(self.paths) > 1 else ''))
        self.text(cr, heading, CENTER, CENTER - 21, 15, (.65, .85, .67))
        name = self.paths[0].name if len(self.paths) == 1 else ('Local conversion' if not self.paths else 'Batch conversion')
        if len(name) > 19:
            name = name[:11] + '…' + name[-7:]
        self.text(cr, name, CENTER, CENTER + 2, 11, (.82, .87, .92))
        instruction = 'Please wait' if self.busy else (f'To {self.options[self.hover]}' if self.hover >= 0 and self.options else 'Pick a format' if self.paths else 'Drop files')
        self.text(cr, instruction, CENTER, CENTER + 24, 12, (.6, .67, .75))

    @staticmethod
    def text(cr, text, x, y, size, color):
        cr.select_font_face('Sans', 0, 1)
        cr.set_font_size(size)
        ext = cr.text_extents(text)
        cr.move_to(x - ext.width / 2 - ext.x_bearing, y - ext.height / 2 - ext.y_bearing)
        cr.set_source_rgb(*color)
        cr.show_text(text)

def main():
    import sys
    Orbit().run(sys.argv)
