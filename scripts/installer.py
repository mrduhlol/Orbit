"""Small, conservative installer for the local Orbit checkout."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
START = '-- BEGIN ORBIT SHIFT GESTURE'
END = '-- END ORBIT SHIFT GESTURE'
MARKER = '# Managed by Orbit installer'


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True, timeout=30)


def check_dependencies(gesture):
    missing = []
    for module, package in [('gi', 'python-gobject'), ('cairo', 'python-cairo'), ('PIL', 'python-pillow')]:
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    try:
        import gi
        gi.require_version('Gtk', '4.0')
        gi.require_version('Gtk4LayerShell', '1.0')
    except (ImportError, ValueError):
        missing.extend(['gtk4', 'gtk4-layer-shell'])
    if gesture:
        missing.extend(command for command in ('hyprctl', 'gapplication', 'systemctl') if not shutil.which(command))
    if missing:
        raise RuntimeError('Missing dependencies: ' + ', '.join(sorted(set(missing))) + '. Install the corresponding Arch packages and retry using /usr/bin/python.')
    optional = [command for command in ('ffmpeg', 'ffprobe', 'pdftoppm', 'pdftotext') if not shutil.which(command)]
    if optional:
        print('Optional converters missing (install ffmpeg/poppler): ' + ', '.join(optional), file=sys.stderr)


def block():
    lines = [START]
    for side, key in [('left', 'Shift_L'), ('right', 'Shift_R')]:
        for state in ('down', 'up'):
            options = 'non_consuming = true, ignore_mods = true, transparent = true'
            if state == 'up':
                options += ', release = true'
            lines.append(f'o.bind("{key}", "Orbit gesture {side} {state}", "gapplication action dev.orbit.Converter shift-{side}-{state}", {{ {options} }})')
    return '\n'.join(lines + [END])


def update_bindings(text, remove=False):
    if START not in text and END not in text:
        return text if remove else text + ('\n' if text and not text.endswith('\n') else '') + block() + '\n'
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise RuntimeError('Malformed Orbit markers in bindings.lua; refusing to modify it.')
    before, rest = text.split(START)
    _, after = rest.split(END)
    if remove and after.startswith('\n'):
        after = after[1:]
    return before + ('' if remove else block()) + after


def snapshot(path):
    if path.is_symlink():
        return ('link', os.readlink(path))
    if path.exists():
        return ('file', path.read_bytes(), path.stat().st_mode & 0o777)
    return None


def write(path, state):
    if snapshot(path) == state:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if state is None:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_name(path.name + f'.orbit-tmp-{os.getpid()}')
    try:
        if state[0] == 'link':
            temporary.symlink_to(state[1])
        else:
            temporary.write_bytes(state[1])
            temporary.chmod(state[2])
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def file_state(text, mode=0o644):
    return ('file', text.encode(), mode)


def quote(value, desktop=False):
    value = str(value).replace('\\', '\\\\').replace('"', '\\"')
    if desktop:
        value = value.replace('`', '\\`').replace('$', '\\$')
    else:
        value = value.replace('$', '$$')
    return '"' + value.replace('%', '%%') + '"'


def install(home, gesture=False, remove=False):
    launcher = home / '.local/bin/orbit'
    desktop = home / '.local/share/applications/dev.orbit.Converter.desktop'
    service = home / '.config/systemd/user/orbit.service'
    bindings = home / '.config/hypr/bindings.lua'
    paths = [launcher, desktop] + ([service, bindings] if gesture or remove else [])
    original = {path: snapshot(path) for path in paths}
    # Never replace unrelated files, including dangling symlinks.
    for path in paths:
        state = original[path]
        if state is None or path == bindings:
            continue
        if path == launcher:
            owned = state[0] == 'link' and Path(state[1]).resolve() == ROOT / 'scripts/orbit'
        else:
            text = state[1].decode() if state[0] == 'file' else ''
            owned = MARKER in text or (
                path == desktop and 'Comment=Local radial file converter\n' in text and f'Exec="{launcher}" %F\n' in text
            ) or (path == service and 'Description=Orbit Shift-drag file converter\n' in text and f'ExecStart="{launcher}" --daemon\n' in text)
        if not owned:
            raise RuntimeError(f'Refusing to replace or remove unrelated file: {path}')
    changes = {}
    if not remove:
        check_dependencies(gesture)
        changes[launcher] = ('link', str(ROOT / 'scripts/orbit'))
        changes[desktop] = file_state(f'''{MARKER}
[Desktop Entry]
Type=Application
Name=Orbit
Comment=Local radial file converter
Exec={quote(launcher, desktop=True)} %F
Icon=document-save-as
Terminal=false
Categories=Utility;Graphics;
MimeType=image/png;image/jpeg;image/webp;application/pdf;audio/mpeg;video/mp4;
StartupNotify=false
''')
    else:
        changes.update({path: None for path in (launcher, desktop, service)})
    if gesture or (remove and bindings.exists()):
        if not bindings.is_file() or bindings.is_symlink():
            raise RuntimeError('Expected regular Omarchy Lua config at ~/.config/hypr/bindings.lua')
        old = bindings.read_text()
        new = update_bindings(old, remove)
        if gesture:
            current = json.loads(run('hyprctl', 'binds', '-j').stdout)
            if any(b.get('key', '').lower() in ('shift_l', 'shift_r') and not b.get('description', '').startswith('Orbit gesture') for b in current):
                raise RuntimeError('Existing Shift bindings found; resolve them before installing Orbit.')
        if old != new:
            changes[bindings] = file_state(new, original[bindings][2])
    if gesture:
        changes[service] = file_state(f'''{MARKER}
[Unit]
Description=Orbit Shift-drag file converter
PartOf=graphical-session.target
After=graphical-session-pre.target

[Service]
ExecStart={quote(launcher)} --daemon
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
''')
    service_work = gesture or (remove and original.get(service) is not None)
    enabled = active = False
    if service_work:
        enabled = run('systemctl', '--user', 'is-enabled', 'orbit.service', check=False).returncode == 0
        active = run('systemctl', '--user', 'is-active', 'orbit.service', check=False).returncode == 0
    try:
        if bindings in changes:
            bindings.with_name(bindings.name + f'.bak.orbit.{time.time_ns()}').write_bytes(original[bindings][1])
        if remove and service_work:
            run('systemctl', '--user', 'disable', '--now', 'orbit.service')
        for path, state in changes.items():
            write(path, state)
        if bindings in changes:
            run('hyprctl', 'reload')
            errors = run('hyprctl', 'configerrors').stdout.strip()
            if errors:
                raise RuntimeError('Hyprland rejected the configuration: ' + errors)
        if service_work:
            run('systemctl', '--user', 'daemon-reload')
            if not remove:
                run('systemctl', '--user', 'enable', 'orbit.service')
                run('systemctl', '--user', 'restart', 'orbit.service')
    except Exception:
        for path in changes:
            write(path, original[path])
        if bindings in changes:
            run('hyprctl', 'reload', check=False)
        if service_work:
            run('systemctl', '--user', 'daemon-reload', check=False)
            run('systemctl', '--user', 'enable' if enabled else 'disable', 'orbit.service', check=False)
            run('systemctl', '--user', 'restart' if active else 'stop', 'orbit.service', check=False)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gesture', action='store_true', help='Install Shift bindings and session service (requires a running Hyprland session).')
    parser.add_argument('--uninstall', action='store_true', help='Remove Orbit-managed files and gesture bindings; keep converted files and unrelated shortcuts.')
    args = parser.parse_args()
    try:
        install(Path.home(), args.gesture, args.uninstall)
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
        detail = getattr(error, 'stderr', None) or ''
        parser.exit(1, f'Orbit: {error}\n{detail}')
    print('Orbit uninstalled.' if args.uninstall else 'Orbit installed.' + (' Hold Shift after starting a file drag.' if args.gesture else ' Launch with: orbit'))


if __name__ == '__main__':
    main()
