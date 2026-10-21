# Orbit

A native radial file converter for Omarchy / Hyprland, inspired by the supplied drag-to-convert reference. GTK 4 and Wayland layer shell; conversions run locally.

## Run

On Arch / Omarchy, dependencies are `python`, `python-gobject`, `python-cairo`, `python-pillow`, `gtk4`, `gtk4-layer-shell`, `ffmpeg`, and `poppler`.

```sh
./scripts/orbit
# Install launcher, Shift bindings, and background session service
./scripts/install-gesture
```

Open Orbit, then drag files onto a format segment to convert. Drop in the center to select files first, or use **Choose files**. Format buttons below the wheel support keyboard navigation. Escape closes the panel while idle. Output copies appear next to their source; existing names receive numbered suffixes. **Open output folder** opens the last output's directory.

## Shift-drag gesture

1. Start dragging a local file in your file manager.
2. Hold either **Shift** key while continuing the drag. The wheel appears near the pointer when the source provides a supported file list.
3. Keep Shift held and drop onto a format. The wheel disappears, conversion runs in the background, and a desktop notification reports the result.
4. Release Shift before dropping to dismiss the wheel. This cancels Orbit only; the original file-manager drag is still active.

The wheel stays fixed after appearing so you can target its segments. Placement is clamped to the monitor edges and accounts for scaling and rotation. Ordinary Shift presses show no visible popup. A transparent 64×64 pointer target probes for a file drag for up to 800 ms; it never takes keyboard focus, but can briefly intercept pointer input inside that small area. If a fast drag misses the probe, release and press Shift again while pausing the pointer. Starting the drag *after* holding Shift is not supported. Text, unsupported formats, and non-local URI drops do not reveal the wheel.

The implementation uses native GTK drag offers, not clipboard scraping or raw input-device access. The Shift bindings are non-consuming and do not replace Super window movement. The resident `orbit.service` starts with the graphical session. Both Shift keys are tracked; releasing the last held Shift cancels the popup. A separate Hyprland session has exercised a real cross-process GTK file drag, popup targeting, and successful conversion with the original preserved. That test invoked the Shift action over D-Bus; keyboard bindings could not be exercised while the parent desktop was locked. Verify the physical Shift gesture with your file manager after unlocking.

**Super + Ctrl + Alt + O** remains the manually installed fallback for the full converter panel. Run `orbit` for the same panel. The installer does not add this optional fallback binding on other machines.

## Conversions

- Single-frame images → PNG, JPG, WebP, TIFF, BMP, PDF.
- PDF → PNG/JPG (one file per page, 150 DPI), TXT (embedded text, no OCR).
- Audio → MP3, WAV, FLAC, OGG.
- Video → MP4, WebM, MP3, WAV. Audio extraction requires an audio track.
- Batches expose only formats shared by all selected inputs.

JPEG/PDF/BMP flatten transparency onto white. Animated and multi-page input images are rejected to avoid silently discarding frames. PDF-to-DOCX, cropping, backgrounds, cancellation, and progress percentages are not implemented. Conversions have a 30-minute per-command timeout; keep the background service running during conversion. Individual batch failures are reported without discarding successful files. Converters need write access to the source directory. Publication uses atomic hard links where supported, with an exclusive-create copy fallback on other filesystems. The fallback output is visible while copying but never overwrites an existing file. PDF pages are ordered numerically; publication failures roll back pages created by that conversion (process crashes cannot be rolled back). Long filenames are shortened to leave room for output extensions and collision suffixes.

## Development

```sh
/usr/bin/python -m unittest discover -s tests -v
```

GTK callback tests are opt-in and require a Broadway server:

```sh
gtk4-broadwayd :19 &
GDK_BACKEND=broadway BROADWAY_DISPLAY=:19 ORBIT_UI_TESTS=1 \
  /usr/bin/python -m unittest discover -s tests -p test_ui.py -v
```

These check widget callbacks and rendering; they do not substitute for an actual Wayland drag. GitHub Actions runs the core conversion, gesture, and isolated installer tests on every push.

`orbit/converter.py` contains conversion and output safety logic; `orbit/app.py` contains the native overlay and file drop handling. No web server or external API is used.

To stop the gesture service: `systemctl --user stop orbit.service`. Inspect logs with `journalctl --user -u orbit.service`.

To uninstall, run `systemctl --user disable --now orbit.service`, remove `~/.config/systemd/user/orbit.service`, `~/.local/bin/orbit`, and `~/.local/share/applications/dev.orbit.Converter.desktop`. Remove the marked `BEGIN ORBIT SHIFT GESTURE` / `END ORBIT SHIFT GESTURE` block and optional Orbit shortcut from `~/.config/hypr/bindings.lua`, then run `hyprctl reload` and `hyprctl configerrors`. The installer backs up bindings before changes. Alternatively, run `./scripts/uninstall` to remove the managed service, launcher, desktop entry, and marked gesture bindings while preserving unrelated settings. Re-running `./scripts/install-gesture` validates the configuration and restarts the daemon to load updated code; failed setup restores previous files and service state. Existing unrelated files are never overwritten.
