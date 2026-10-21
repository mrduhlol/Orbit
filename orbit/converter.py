"""Local conversion with atomic, non-overwriting output publication."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
from PIL import Image, ImageOps

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.gif', '.avif'}
AUDIO_EXTS = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.opus'}
VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}

def formats(path):
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTS:
        return ['PNG', 'JPG', 'WEBP', 'TIFF', 'BMP', 'PDF']
    if suffix == '.pdf':
        return (['PNG', 'JPG'] if shutil.which('pdftoppm') else []) + (['TXT'] if shutil.which('pdftotext') else [])
    if shutil.which('ffmpeg'):
        if suffix in AUDIO_EXTS:
            return ['MP3', 'WAV', 'FLAC', 'OGG']
        if suffix in VIDEO_EXTS:
            return ['MP4', 'WEBM', 'MP3', 'WAV']
    return []

def common_formats(paths):
    return [f for f in formats(paths[0]) if all(f in formats(p) for p in paths)] if paths else []

def run(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=1800)
    except FileNotFoundError as exc:
        raise ValueError(f'Missing converter: {args[0]}') from exc
    if result.returncode:
        raise ValueError(result.stderr.strip()[-600:] or 'Conversion failed')

def publish(source, parent, stem, suffix):
    # Hard links give atomic create-if-absent semantics, including concurrent jobs.
    for n in range(10000):
        dest = parent / f'{stem}{"" if n == 0 else f" ({n})"}.{suffix}'
        try:
            os.link(source, dest)
            return dest
        except FileExistsError:
            continue
    raise ValueError('Too many existing output copies')

def convert(path, target):
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError('Please choose a regular file')
    if target not in formats(path):
        raise ValueError(f'{target} is not supported for {path.name}')
    suffix = target.lower()
    with tempfile.TemporaryDirectory(prefix='.orbit-', dir=path.parent) as tmp:
        tmp = Path(tmp)
        output = tmp / f'converted.{suffix}'
        if path.suffix.lower() in IMAGE_EXTS:
            with Image.open(path) as original:
                if getattr(original, 'n_frames', 1) > 1:
                    raise ValueError('Animated or multi-page images are not supported yet')
                img = ImageOps.exif_transpose(original)
                if target in {'JPG', 'PDF', 'BMP'}:
                    rgba = img.convert('RGBA')
                    img = Image.new('RGB', rgba.size, 'white')
                    img.paste(rgba, mask=rgba.getchannel('A'))
                img.save(output, format={'JPG': 'JPEG'}.get(target, target), **({'quality': 92} if target in {'JPG', 'WEBP'} else {}))
        elif path.suffix.lower() == '.pdf':
            if target == 'TXT':
                run(['pdftotext', '-layout', str(path), str(output)])
            else:
                run(['pdftoppm', '-r', '150', '-png' if target == 'PNG' else '-jpeg', str(path), str(tmp / 'page')])
                pages = sorted(tmp.glob(f'page-*.{suffix}'))
                if not pages:
                    raise ValueError('PDF produced no pages')
                return [publish(p, path.parent, f'{path.stem}-page-{i:03}', suffix) for i, p in enumerate(pages, 1)]
        else:
            codecs = {
                'MP3': ['-vn', '-c:a', 'libmp3lame', '-q:a', '2'],
                'WAV': ['-vn', '-c:a', 'pcm_s16le'],
                'FLAC': ['-vn', '-c:a', 'flac'],
                'OGG': ['-vn', '-c:a', 'libvorbis', '-q:a', '5'],
                'MP4': ['-c:v', 'libx264', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-pix_fmt', 'yuv420p', '-crf', '22', '-c:a', 'aac', '-movflags', '+faststart'],
                'WEBM': ['-c:v', 'libvpx-vp9', '-crf', '32', '-b:v', '0', '-c:a', 'libopus'],
            }
            run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path), *codecs[target], str(output)])
        return [publish(output, path.parent, path.stem, suffix)]
