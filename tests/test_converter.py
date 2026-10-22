import concurrent.futures
import errno
import os
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from PIL import Image

from orbit.converter import common_formats, convert, formats

PDF_TOOLS = bool(shutil.which('pdftoppm') and shutil.which('pdftotext'))
FFMPEG = bool(shutil.which('ffmpeg'))


def make_pdf(path, pages=1):
    images = [Image.new('RGB', (40, 40), (min(i * 20, 255), 0, 0)) for i in range(pages)]
    images[0].save(path, save_all=True, append_images=images[1:])


def make_wav(path, seconds=0.1):
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\0\0' * int(8000 * seconds))


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'a tricky $ file.png'
        Image.new('RGBA', (24, 16), (255, 0, 0, 0)).save(self.source)

    def tearDown(self):
        self.tmp.cleanup()

    def test_image_formats_and_collision(self):
        original = self.source.read_bytes()
        self.assertEqual(formats(self.source), ['PNG', 'JPG', 'WEBP', 'TIFF', 'BMP', 'PDF'])
        for fmt in formats(self.source):
            output = convert(self.source, fmt)[0]
            self.assertTrue(output.stat().st_size)
            self.assertNotEqual(output, self.source)
        jpg = convert(self.source, 'JPG')[0]
        self.assertEqual(jpg.name, 'a tricky $ file (1).jpg')
        with Image.open(jpg) as img:
            self.assertEqual(img.size, (24, 16))
            self.assertEqual(img.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(self.source.read_bytes(), original)

    def test_target_names_are_case_insensitive_and_aliased(self):
        png = convert(self.source, 'png')[0]
        jpeg = convert(self.source, 'jpeg')[0]
        self.assertEqual(png.suffix, '.png')
        self.assertEqual(jpeg.suffix, '.jpg')
        with Image.open(jpeg) as img:
            self.assertEqual(img.size, (24, 16))
        with self.assertRaises(ValueError):
            convert(self.source, 'NOPE')
        with self.assertRaises(ValueError):
            convert(self.source, '')

    @unittest.skipUnless(PDF_TOOLS, 'poppler utilities required')
    def test_pdf_pages_order_and_names(self):
        pdf = self.root / 'document.pdf'
        make_pdf(pdf, pages=12)
        self.assertEqual(formats(pdf), ['PNG', 'JPG', 'TXT'])

        pages = convert(pdf, 'PNG')
        self.assertEqual(len(pages), 12)
        self.assertEqual(
            [page.name for page in pages],
            [f'document-page-{number:03}.png' for number in range(1, 13)],
        )
        reds = []
        for page in pages:
            with Image.open(page) as img:
                reds.append(img.getpixel((img.width // 2, img.height // 2))[0])
        self.assertEqual(reds, sorted(reds))
        self.assertLess(reds[0], 10)
        self.assertGreater(reds[-1], 200)

        jpgs = convert(pdf, 'JPG')
        self.assertEqual(len(jpgs), 12)
        self.assertEqual(jpgs[0].name, 'document-page-001.jpg')
        self.assertTrue(convert(pdf, 'TXT')[0].exists())

    @unittest.skipUnless(shutil.which('pdftoppm'), 'pdftoppm required')
    def test_pdf_page_order_uses_page_numbers_not_text(self):
        pdf = self.root / 'unpadded.pdf'
        pdf.write_bytes(b'not a real pdf; the renderer is stubbed')

        def fake_run(args):
            directory = Path(args[-1]).parent
            for number, colour in [(1, 'red'), (2, 'green'), (10, 'blue')]:
                Image.new('RGB', (4, 4), colour).save(directory / f'page-{number}.png')

        with mock.patch('orbit.converter.run', side_effect=fake_run):
            pages = convert(pdf, 'PNG')

        self.assertEqual(
            [page.name for page in pages],
            ['unpadded-page-001.png', 'unpadded-page-002.png', 'unpadded-page-010.png'],
        )
        colours = []
        for page in pages:
            with Image.open(page) as img:
                colours.append(img.getpixel((0, 0)))
        self.assertEqual(colours, [(255, 0, 0), (0, 128, 0), (0, 0, 255)])

    @unittest.skipUnless(shutil.which('pdftoppm'), 'pdftoppm required')
    def test_pdf_empty_page_publishes_nothing(self):
        pdf = self.root / 'unpadded.pdf'
        pdf.write_bytes(b'not a real pdf; the renderer is stubbed')

        def fake_run(args):
            directory = Path(args[-1]).parent
            Image.new('RGB', (4, 4), 'red').save(directory / 'page-1.png')
            (directory / 'page-2.png').touch()

        with mock.patch('orbit.converter.run', side_effect=fake_run):
            with self.assertRaisesRegex(ValueError, 'empty output'):
                convert(pdf, 'PNG')
        self.assertEqual(list(self.root.glob('unpadded-page-*')), [])
        self.assertFalse(list(self.root.glob('.orbit-*')))

    @unittest.skipUnless(shutil.which('pdftoppm'), 'pdftoppm required')
    def test_pdf_publication_rolls_back_on_failure(self):
        pdf = self.root / 'document.pdf'
        make_pdf(pdf, pages=3)
        real_link = os.link

        def flaky_link(source, dest, *args, **kwargs):
            if Path(dest).name == 'document-page-002.png':
                raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
            return real_link(source, dest, *args, **kwargs)

        with mock.patch('orbit.converter.os.link', side_effect=flaky_link):
            with self.assertRaises(ValueError) as caught:
                convert(pdf, 'PNG')

        self.assertIn('Cannot publish', str(caught.exception))
        self.assertEqual(list(self.root.glob('document-page-*')), [])
        self.assertFalse(list(self.root.glob('.orbit-*')))

    def test_single_output_publication_failure_leaves_nothing(self):
        def no_space(source, dest, *args, **kwargs):
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

        with mock.patch('orbit.converter.os.link', side_effect=no_space):
            with self.assertRaises(ValueError) as caught:
                convert(self.source, 'JPG')

        self.assertIn('Cannot publish', str(caught.exception))
        self.assertEqual(list(self.root.glob('*.jpg')), [])
        self.assertFalse(list(self.root.glob('.orbit-*')))

    def test_hardlink_fallback_never_overwrites(self):
        existing = self.root / 'a tricky $ file.jpg'
        existing.write_bytes(b'keep me')

        def no_links(source, dest, *args, **kwargs):
            raise OSError(errno.EPERM, os.strerror(errno.EPERM))

        with mock.patch('orbit.converter.os.link', side_effect=no_links):
            output = convert(self.source, 'JPG')[0]

        self.assertEqual(existing.read_bytes(), b'keep me')
        self.assertEqual(output.name, 'a tricky $ file (1).jpg')
        with Image.open(output) as img:
            self.assertEqual(img.size, (24, 16))
        self.assertFalse(list(self.root.glob('.orbit-*')))

    def test_long_output_names_are_truncated(self):
        long_source = self.root / ('x' * 240 + '.png')
        Image.new('RGB', (8, 8), 'blue').save(long_source)
        output = convert(long_source, 'JPG')[0]
        self.assertTrue(output.exists())
        self.assertLessEqual(len(output.name.encode('utf-8')), 255)
        self.assertEqual(output.suffix, '.jpg')

    def test_animated_and_multipage_images_are_rejected(self):
        gif = self.root / 'animated.gif'
        Image.new('RGB', (8, 8), 'red').save(
            gif, save_all=True, append_images=[Image.new('RGB', (8, 8), 'blue')]
        )
        tiff = self.root / 'multipage.tiff'
        Image.new('RGB', (8, 8), 'red').save(
            tiff, save_all=True, append_images=[Image.new('RGB', (8, 8), 'blue')]
        )
        for source in (gif, tiff):
            self.assertEqual(formats(source), [])
            with self.assertRaisesRegex(ValueError, 'Animated or multi-page'):
                convert(source, 'PNG')
        self.assertEqual(list(self.root.glob('animated*.png')), [])
        self.assertEqual(list(self.root.glob('multipage*.png')), [])
        self.assertFalse(list(self.root.glob('.orbit-*')))

    def test_corrupt_and_unsupported_images_are_rejected(self):
        broken = self.root / 'broken.png'
        broken.write_text('not an image')
        self.assertEqual(formats(broken), [])
        with self.assertRaisesRegex(ValueError, 'Cannot read image'):
            convert(broken, 'JPG')
        self.assertFalse((self.root / 'broken.jpg').exists())
        self.assertFalse(list(self.root.glob('.orbit-*')))

        unsupported = self.root / 'photo.heic'
        unsupported.write_bytes(b'\0' * 8)
        self.assertEqual(formats(unsupported), [])
        with self.assertRaisesRegex(ValueError, 'Unsupported input format'):
            convert(unsupported, 'PNG')

    def test_missing_source_and_non_regular_files(self):
        with self.assertRaisesRegex(ValueError, 'File not found'):
            convert(self.root / 'missing.png', 'JPG')
        with self.assertRaisesRegex(ValueError, 'regular file'):
            convert(self.root, 'JPG')
        self.assertEqual(common_formats([]), [])

    def test_missing_converter_errors(self):
        pdf = self.root / 'document.pdf'
        make_pdf(pdf)
        wav = self.root / 'tone.wav'
        make_wav(wav)
        real_which = shutil.which

        def without_tools(name, *args, **kwargs):
            if name in {'pdftoppm', 'pdftotext', 'ffmpeg'}:
                return None
            return real_which(name, *args, **kwargs)

        with mock.patch('orbit.converter.shutil.which', side_effect=without_tools):
            self.assertEqual(formats(pdf), [])
            self.assertEqual(formats(wav), [])
            with self.assertRaisesRegex(ValueError, 'Missing converter: pdftoppm'):
                convert(pdf, 'PNG')
            with self.assertRaisesRegex(ValueError, 'Missing converter: pdftotext'):
                convert(pdf, 'TXT')
            with self.assertRaisesRegex(ValueError, 'Missing converter: ffmpeg'):
                convert(wav, 'MP3')

        self.assertEqual(list(self.root.glob('document-page-*')), [])
        self.assertFalse((self.root / 'document.txt').exists())
        self.assertFalse((self.root / 'tone.mp3').exists())
        self.assertFalse(list(self.root.glob('.orbit-*')))

    def test_concurrent_publication_creates_distinct_outputs(self):
        def convert_once():
            return convert(self.source, 'JPG')[0]

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first, second = [future.result() for future in (pool.submit(convert_once), pool.submit(convert_once))]

        self.assertNotEqual(first, second)
        for output in (first, second):
            self.assertTrue(output.exists())
            with Image.open(output) as img:
                self.assertEqual(img.size, (24, 16))
        self.assertFalse(list(self.root.glob('.orbit-*')))

    @unittest.skipUnless(PDF_TOOLS, 'poppler utilities required')
    def test_common_formats(self):
        pdf = self.root / 'document.pdf'
        make_pdf(pdf)
        audio = self.root / 'tone.wav'
        make_wav(audio)
        self.assertEqual(common_formats([self.source, pdf]), ['PNG', 'JPG'])
        self.assertEqual(common_formats([self.source, audio]), [])
        self.assertEqual(common_formats([self.source]), formats(self.source))

    @unittest.skipUnless(FFMPEG, 'ffmpeg required')
    def test_media(self):
        wav = self.root / 'tone.wav'
        subprocess.run(
            ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.1', str(wav)],
            check=True,
        )
        for fmt in ['MP3', 'FLAC', 'OGG', 'WAV']:
            self.assertTrue(convert(wav, fmt)[0].stat().st_size)

        video = self.root / 'clip.mp4'
        subprocess.run(
            ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=size=32x32:duration=0.1', str(video)],
            check=True,
        )
        for fmt in ['MP4', 'WEBM']:
            self.assertTrue(convert(video, fmt)[0].stat().st_size)

        with self.assertRaises(ValueError):
            convert(video, 'MP3')
        self.assertFalse((self.root / 'clip.mp3').exists())
        self.assertFalse(list(self.root.glob('.orbit-*')))

    @unittest.skipUnless(FFMPEG, 'ffmpeg required')
    def test_video_without_audio_offers_no_audio_targets(self):
        video = self.root / 'silent-recording.mp4'
        subprocess.run(
            ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=size=32x32:duration=0.1', str(video)],
            check=True,
        )
        self.assertEqual(formats(video), ['MP4', 'WEBM'])

        with self.assertRaises(ValueError) as caught:
            convert(video, 'MP3')
        self.assertIn('no audio', str(caught.exception))
        self.assertFalse((self.root / 'silent-recording.mp3').exists())
        self.assertFalse(list(self.root.glob('.orbit-*')))

    @unittest.skipUnless(FFMPEG, 'ffmpeg required')
    def test_video_with_audio_offers_full_targets_and_extracts_mp3(self):
        video = self.root / 'clip-with-sound.mp4'
        subprocess.run(
            ['ffmpeg', '-v', 'error',
             '-f', 'lavfi', '-i', 'color=size=32x32:duration=0.1',
             '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.1',
             '-shortest', str(video)],
            check=True,
        )
        self.assertEqual(formats(video), ['MP4', 'WEBM', 'MP3', 'WAV'])
        mp3 = convert(video, 'MP3')[0]
        self.assertTrue(mp3.stat().st_size)
        self.assertFalse(list(self.root.glob('.orbit-*')))


if __name__ == '__main__':
    unittest.main()
