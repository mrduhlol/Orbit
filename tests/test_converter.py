import tempfile
import unittest
from pathlib import Path
import subprocess
from PIL import Image
from orbit.converter import convert, common_formats

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
        for fmt in ['PNG', 'JPG', 'WEBP', 'TIFF', 'BMP', 'PDF']:
            output = convert(self.source, fmt)[0]
            self.assertTrue(output.stat().st_size)
            self.assertNotEqual(output, self.source)
        jpg = convert(self.source, 'JPG')[0]
        self.assertEqual(jpg.name, 'a tricky $ file (1).jpg')
        with Image.open(jpg) as img:
            self.assertEqual(img.size, (24, 16))
            self.assertEqual(img.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(self.source.read_bytes(), original)

    def test_pdf_pages(self):
        pdf = self.root / 'document.pdf'
        a = Image.new('RGB', (32, 32), 'red')
        a.save(pdf, save_all=True, append_images=[Image.new('RGB', (32, 32), 'blue')])
        self.assertEqual(len(convert(pdf, 'PNG')), 2)
        self.assertEqual(len(convert(pdf, 'JPG')), 2)
        self.assertTrue(convert(pdf, 'TXT')[0].exists())

    def test_bad_input_leaves_no_output(self):
        broken = self.root / 'broken.png'
        broken.write_text('not an image')
        with self.assertRaises(Exception):
            convert(broken, 'JPG')
        self.assertFalse((self.root / 'broken.jpg').exists())
        self.assertFalse(list(self.root.glob('.orbit-*')))
        self.assertEqual(common_formats([self.source, self.root / 'x.mp3']), [])

    def test_media(self):
        wav = self.root / 'tone.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.1', str(wav)], check=True)
        for fmt in ['MP3', 'FLAC', 'OGG', 'WAV']:
            self.assertTrue(convert(wav, fmt)[0].stat().st_size)
        video = self.root / 'clip.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=size=32x32:duration=0.1', str(video)], check=True)
        for fmt in ['MP4', 'WEBM']:
            self.assertTrue(convert(video, fmt)[0].stat().st_size)

if __name__ == '__main__':
    unittest.main()
