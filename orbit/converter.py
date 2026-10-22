"""Local file conversion with atomic, non-overwriting output publication."""
from pathlib import Path
import errno
import os
import re
import shutil
import subprocess
import tempfile
from PIL import Image, ImageOps, UnidentifiedImageError

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.gif', '.avif'}
AUDIO_EXTS = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.opus'}
VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}

IMAGE_TARGETS = (
    ('PNG', 'PNG'),
    ('JPG', 'JPEG'),
    ('WEBP', 'WEBP'),
    ('TIFF', 'TIFF'),
    ('BMP', 'BMP'),
    ('PDF', 'PDF'),
)
PDF_TARGETS = ('PNG', 'JPG', 'TXT')
AUDIO_TARGETS = ('MP3', 'WAV', 'FLAC', 'OGG')
VIDEO_TARGETS = ('MP4', 'WEBM', 'MP3', 'WAV')
TARGET_ALIASES = {'JPEG': 'JPG', 'TIF': 'TIFF'}

TIMEOUT = 1800
MAX_STEM_BYTES = 180
MAX_COPIES = 10000
# Some filesystems (exFAT, FAT, network shares) cannot create hard links.
UNSUPPORTED_LINK_ERRNOS = {
    errno.EPERM,
    errno.EMLINK,
    errno.EXDEV,
    errno.ENOSYS,
    getattr(errno, 'ENOTSUP', errno.EOPNOTSUPP),
    errno.EOPNOTSUPP,
}

_PAGE_NAME = re.compile(r'^page-(\d+)\.(png|jpe?g)$', re.IGNORECASE)
_IMAGE_ERRORS = (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError)


class _AnimatedImageError(ValueError):
    pass


def _kind(path):
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTS:
        return 'image'
    if suffix == '.pdf':
        return 'pdf'
    if suffix in AUDIO_EXTS:
        return 'audio'
    if suffix in VIDEO_EXTS:
        return 'video'
    return None


def _image_targets():
    Image.init()
    return [name for name, pil_name in IMAGE_TARGETS if pil_name in Image.SAVE]


def _image_frames(path):
    """Return the frame count for a readable image, or None if it cannot be read."""
    try:
        with Image.open(path) as image:
            return getattr(image, 'n_frames', 1)
    except _IMAGE_ERRORS:
        return None


def formats(path):
    try:
        path = Path(path)
    except TypeError:
        return []
    kind = _kind(path)
    if kind == 'image':
        frames = _image_frames(path)
        # Animated and multi-page inputs cannot be converted without losing frames.
        return _image_targets() if frames == 1 else []
    if kind == 'pdf':
        return (['PNG', 'JPG'] if shutil.which('pdftoppm') else []) + (['TXT'] if shutil.which('pdftotext') else [])
    if kind == 'audio':
        return list(AUDIO_TARGETS) if shutil.which('ffmpeg') else []
    if kind == 'video':
        if not shutil.which('ffmpeg'):
            return []
        targets = list(VIDEO_TARGETS)
        if shutil.which('ffprobe') and _has_audio_stream(path) is False:
            # A video without an audio stream cannot be reduced to an audio file.
            targets = [fmt for fmt in targets if fmt not in AUDIO_TARGETS]
        return targets
    return []


def common_formats(paths):
    paths = list(paths)
    if not paths:
        return []
    available = formats(paths[0])
    for path in paths[1:]:
        other = formats(path)
        available = [fmt for fmt in available if fmt in other]
    return available


def run(args):
    tool = Path(args[0]).name
    try:
        result = subprocess.run(
            args, capture_output=True, stdin=subprocess.DEVNULL, text=True,
            encoding='utf-8', errors='replace', timeout=TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise ValueError(f'Missing converter: {tool}') from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f'{tool} timed out after {TIMEOUT // 60} minutes') from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or '').strip()
        raise ValueError(detail[-600:] or f'{tool} failed with exit code {result.returncode}')


def _require_tool(tool):
    if not shutil.which(tool):
        raise ValueError(f'Missing converter: {tool}')


def _safe_stem(stem, tail=''):
    """Keep output names under common NAME_MAX limits while preserving ``tail``."""
    encoded_stem = os.fsencode(stem)
    encoded_tail = os.fsencode(tail)
    if len(encoded_stem) + len(encoded_tail) <= MAX_STEM_BYTES:
        return f'{stem}{tail}'
    room = max(1, MAX_STEM_BYTES - len(encoded_tail))
    return f'{os.fsdecode(encoded_stem[:room])}{tail}'


def _copy_exclusive(source, dest):
    """Claim ``dest`` exclusively and copy into it for hard-link-less filesystems."""
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, 'wb') as output, open(source, 'rb') as original:
            shutil.copyfileobj(original, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        # A failed copy must never leave a partial output behind.
        try:
            os.unlink(dest)
        except OSError:
            pass
        raise


def publish(source, parent, stem, suffix):
    """Create a new output name without overwriting anything.

    Hard links provide atomic create-if-absent semantics, including between
    concurrent jobs. Filesystems without hard links fall back to exclusive
    creation plus a copy; that path still never overwrites, but the output is
    visible while its contents are being copied.
    """
    stem = _safe_stem(stem)
    for n in range(MAX_COPIES):
        dest = parent / f'{stem}{"" if n == 0 else f" ({n})"}.{suffix}'
        try:
            os.link(source, dest)
            return dest
        except FileExistsError:
            continue
        except OSError as exc:
            if exc.errno not in UNSUPPORTED_LINK_ERRNOS:
                raise ValueError(f'Cannot publish output: {exc.strerror or exc}') from exc
            try:
                _copy_exclusive(source, dest)
                return dest
            except FileExistsError:
                continue
            except OSError as copy_exc:
                raise ValueError(f'Cannot publish output: {copy_exc.strerror or copy_exc}') from copy_exc
    raise ValueError('Too many existing output copies')


def _check_output(path):
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError('Converter produced no output') from exc
    if not size:
        raise ValueError('Converter produced an empty output')


def _unlink_if_same(path, info):
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return
    if info is not None and (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino):
        try:
            os.unlink(path)
        except OSError:
            pass


def _publish_pages(pages, parent, suffix):
    """Publish every page or remove the ones already published if one fails."""
    for source, _ in pages:
        _check_output(source)
    published = []
    try:
        for source, stem in pages:
            dest = publish(source, parent, stem, suffix)
            try:
                info = os.stat(dest, follow_symlinks=False)
            except OSError:
                info = None
            published.append((dest, info))
    except BaseException:
        for dest, info in reversed(published):
            _unlink_if_same(dest, info)
        raise
    return [dest for dest, _ in published]


def _ordered_pages(directory, suffix):
    pages = []
    for item in directory.iterdir():
        match = _PAGE_NAME.match(item.name)
        if not match:
            continue
        extension = match.group(2).lower()
        if extension in {'jpg', 'jpeg'}:
            extension = 'jpg'
        if extension == suffix:
            pages.append((int(match.group(1)), item))
    pages.sort(key=lambda page: page[0])
    return pages


def _normalize_target(target):
    if not isinstance(target, str):
        raise ValueError('Target format must be a name')
    target = TARGET_ALIASES.get(target.strip().upper(), target.strip().upper())
    if not target:
        raise ValueError('Please choose an output format')
    return target


def _has_audio_stream(path):
    """True/False whether the media contains audio; None when unknown."""
    if not shutil.which('ffprobe'):
        return None
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type',
             '-of', 'csv=p=0', str(path)],
            capture_output=True, stdin=subprocess.DEVNULL, text=True,
            encoding='utf-8', errors='replace', timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode:
        return None
    return 'audio' in result.stdout.split()


def _check_target(target, allowed, source):
    if target not in allowed:
        raise ValueError(f'{target} is not supported for {source.name}')


def _convert_image(source, target, output):
    pil_format = dict(IMAGE_TARGETS)[target]
    try:
        with Image.open(source) as original:
            if getattr(original, 'n_frames', 1) > 1:
                raise _AnimatedImageError('Animated or multi-page images are not supported yet')
            image = ImageOps.exif_transpose(original)
            image.load()
    except _AnimatedImageError:
        raise
    except _IMAGE_ERRORS as exc:
        raise ValueError(f'Cannot read image: {exc}') from exc
    try:
        if target in {'JPG', 'PDF', 'BMP'}:
            rgba = image.convert('RGBA')
            flattened = Image.new('RGB', rgba.size, 'white')
            flattened.paste(rgba, mask=rgba.getchannel('A'))
            image = flattened
        options = {'quality': 92} if target in {'JPG', 'WEBP'} else {}
        image.save(output, format=pil_format, **options)
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError(f'Cannot convert to {target}: {exc}') from exc


def _media_args(target):
    return {
        'MP3': ['-vn', '-c:a', 'libmp3lame', '-q:a', '2'],
        'WAV': ['-vn', '-c:a', 'pcm_s16le'],
        'FLAC': ['-vn', '-c:a', 'flac'],
        'OGG': ['-vn', '-c:a', 'libvorbis', '-q:a', '5'],
        'MP4': [
            '-c:v', 'libx264', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-pix_fmt', 'yuv420p',
            '-crf', '22', '-c:a', 'aac', '-movflags', '+faststart',
        ],
        'WEBM': [
            '-c:v', 'libvpx-vp9', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2',
            '-crf', '32', '-b:v', '0', '-c:a', 'libopus',
        ],
    }[target]


def convert(path, target):
    try:
        candidate = Path(path).expanduser()
    except TypeError as exc:
        raise ValueError('Please choose a file') from exc
    try:
        source = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f'File not found: {candidate}') from exc
    except (OSError, RuntimeError) as exc:
        raise ValueError(f'Cannot open {candidate.name}: {exc}') from exc
    if not source.is_file():
        raise ValueError('Please choose a regular file')

    target = _normalize_target(target)
    kind = _kind(source)
    if kind is None:
        raise ValueError(f'Unsupported input format: {source.suffix or "no extension"}')
    if kind == 'image':
        _check_target(target, _image_targets(), source)
    elif kind == 'pdf':
        _check_target(target, PDF_TARGETS, source)
    elif kind == 'audio':
        _check_target(target, AUDIO_TARGETS, source)
    else:
        _check_target(target, VIDEO_TARGETS, source)

    if kind == 'pdf':
        _require_tool('pdftotext' if target == 'TXT' else 'pdftoppm')
    elif kind in {'audio', 'video'}:
        _require_tool('ffmpeg')
        if kind == 'video' and target in AUDIO_TARGETS and _has_audio_stream(source) is False:
            raise ValueError('This video has no audio to convert')

    try:
        workspace = tempfile.TemporaryDirectory(prefix='.orbit-', dir=source.parent)
    except OSError as exc:
        raise ValueError(f'Cannot write beside {source.name}: {exc.strerror or exc}') from exc

    suffix = target.lower()
    with workspace as tmp_name:
        tmp = Path(tmp_name)
        output = tmp / f'converted.{suffix}'
        if kind == 'image':
            _convert_image(source, target, output)
            _check_output(output)
        elif kind == 'pdf':
            if target == 'TXT':
                run(['pdftotext', '-layout', str(source), str(output)])
                if not output.is_file():
                    raise ValueError('Converter produced no output')
                return [publish(output, source.parent, source.stem, suffix)]
            run(['pdftoppm', '-r', '150', '-png' if target == 'PNG' else '-jpeg', str(source), str(tmp / 'page')])
            pages = _ordered_pages(tmp, suffix)
            if not pages:
                raise ValueError('PDF produced no pages')
            digits = max(3, len(str(pages[-1][0])))
            page_names = [
                (item, _safe_stem(source.stem, f'-page-{number:0{digits}d}'))
                for number, item in pages
            ]
            return _publish_pages(page_names, source.parent, suffix)
        else:
            run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(source), *_media_args(target), str(output)])
            _check_output(output)
        return [publish(output, source.parent, source.stem, suffix)]
