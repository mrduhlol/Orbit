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

The wheel stays fixed after appearing so you can target its segments. Placement is clamped to the monitor edges and accounts for scaling and rotation. Ordinary Shift presses show no visible popup. A transparent 24×24 pointer target probes for a file drag for up to 400 ms; it never takes keyboard focus, but can briefly intercept pointer input inside that small area. If a fast drag misses the probe, release and press Shift again while pausing the pointer. Starting the drag *after* holding Shift is not supported. Text, unsupported formats, and non-local URI drops do not reveal the wheel.

The implementation uses native GTK drag offers, not clipboard scraping or raw input-device access. The Shift bindings are non-consuming and do not replace Super window movement. The resident `orbit.service` starts with the graphical session. Both Shift keys are tracked; releasing the last held Shift cancels the popup. The actual file-manager-to-overlay gesture still requires verification in an unlocked Wayland session; automated UI checks exercise the callbacks, not a compositor-delivered drag.

**Super + Ctrl + Alt + O** remains the manually installed fallback for the full converter panel. Run `orbit` for the same panel. The installer does not add this optional fallback binding on other machines.

## Conversions

- Single-frame images → PNG, JPG, WebP, TIFF, BMP, PDF.
- PDF → PNG/JPG (one file per page, 150 DPI), TXT (embedded text, no OCR).
- Audio → MP3, WAV, FLAC, OGG.
- Video → MP4, WebM, MP3, WAV. Audio extraction requires an audio track.
- Batches expose only formats shared by all selected inputs.

JPEG/PDF/BMP flatten transparency onto white. Animated and multi-page input images are rejected to avoid silently discarding frames. PDF-to-DOCX, cropping, backgrounds, cancellation, and progress percentages are not implemented. Conversions have a 30-minute per-command timeout; keep the background service running during conversion. Individual batch failures are reported without discarding successful files. Converters need write access to the source directory. Atomic publication uses hard links and requires a filesystem that supports them. PDFs publish pages individually; already-published pages remain if a later publication fails.

## Development

```sh
/usr/bin/python -m unittest discover -s tests -v
```

`orbit/converter.py` contains conversion and output safety logic; `orbit/app.py` contains the native overlay and file drop handling. No web server or external API is used.

To stop the gesture service: `systemctl --user stop orbit.service`. Inspect logs with `journalctl --user -u orbit.service`.

To uninstall, run `systemctl --user disable --now orbit.service`, remove `~/.config/systemd/user/orbit.service`, `~/.local/bin/orbit`, and `~/.local/share/applications/dev.orbit.Converter.desktop`. Remove the marked `BEGIN ORBIT SHIFT GESTURE` / `END ORBIT SHIFT GESTURE` block and optional Orbit shortcut from `~/.config/hypr/bindings.lua`, then run `hyprctl reload` and `hyprctl configerrors`. The installer backs up bindings before changes.
