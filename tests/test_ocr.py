import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget
from ocr_ui import OcrDialog, OcrJob, supported_languages, prepare_ocr_image


class OcrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_language_tag_matching(self):
        self.assertEqual(supported_languages(['ko', 'en-US']), {'ko-KR': True, 'en-US': True})
        self.assertEqual(supported_languages(['ko-KR', 'en-GB']), {'ko-KR': True, 'en-US': False})
        self.assertEqual(supported_languages([]), {'ko-KR': False, 'en-US': False})

    def test_image_scaling_and_cleanup(self):
        image = QImage(1200, 600, QImage.Format.Format_RGB32)
        image.fill(0xFFFFFFFF)
        job = OcrJob('Recognize', image=image, max_dimension=300)
        path = Path(job.folder.name) / 'capture.png'
        loaded = QImage(str(path))
        self.assertEqual((loaded.width(), loaded.height()), (300, 150))
        job.stop()
        self.assertFalse(path.exists())

    def test_result_edit_copy_and_missing_language(self):
        dialog = OcrDialog(None, QImage(20, 20, QImage.Format.Format_RGB32))
        with patch.object(dialog, 'extract') as extract:
            dialog.show_status({'ok': True, 'languages': ['ko'], 'max_dimension': 10000})
            extract.assert_called_once()
        dialog.update_buttons()
        self.assertTrue(dialog.recognize.isEnabled())
        dialog.language.setCurrentIndex(1)
        self.assertFalse(dialog.recognize.isEnabled())
        dialog.show_text({'ok': True, 'text': '한국어 English 123'})
        dialog.text.setPlainText('수정한 결과')
        dialog.text.selectAll()
        dialog.text.copy()
        self.assertEqual(self.app.clipboard().text(), '수정한 결과')
        self.assertTrue(dialog.language.isHidden())
        self.assertTrue(dialog.recognize.isHidden())
        self.assertTrue(dialog.install.isHidden())
        self.assertTrue(dialog.copy.isHidden())
        self.assertEqual(dialog.minimumSize(), dialog.maximumSize())
        dialog.shutdown()

    def test_no_language_shows_setup_guidance_without_recognition(self):
        dialog = OcrDialog(None, QImage(20, 20, QImage.Format.Format_RGB32))
        with patch.object(dialog, 'extract') as extract:
            dialog.show_status({'ok': True, 'languages': [], 'max_dimension': 10000})
            extract.assert_not_called()
        self.assertIn('설정', dialog.text.placeholderText())
        self.assertEqual(dialog.text.toPlainText(), '')
        dialog.shutdown()

    def test_small_crop_padding_and_original_unchanged(self):
        image = QImage(30, 8, QImage.Format.Format_RGB32)
        image.fill(0xFF000000)
        enlarged = prepare_ocr_image(image, 4, 10000)
        self.assertEqual(enlarged.size().toTuple(), (120, 64))
        self.assertEqual(enlarged.pixelColor(0, 0).name(), '#ffffff')
        self.assertEqual(enlarged.pixelColor(60, 32).name(), '#000000')
        self.assertEqual(image.size().toTuple(), (30, 8))
        limited = prepare_ocr_image(image, 4, 80)
        self.assertLessEqual(max(limited.width(), limited.height()), 80)

    def test_retry_empty_and_engine_error_then_success(self):
        dialog = OcrDialog(None, QImage(120, 30, QImage.Format.Format_RGB32))
        with patch.object(dialog, 'run_job') as job:
            dialog.extract()
            self.assertEqual(job.call_args.kwargs['scale'], 1)
            dialog.show_text({'ok': False, 'stage': 'recognize', 'error': 'Image too small'})
            self.assertEqual(job.call_args.kwargs['scale'], 2)
            dialog.show_text({'ok': True, 'text': '  '})
            self.assertEqual(job.call_count, 2)
            dialog.show_text({'ok': True, 'text': '인식 성공'})
            self.assertEqual(job.call_count, 2)
            self.assertEqual(dialog.text.toPlainText(), '인식 성공')
        dialog.shutdown()

    def test_retry_limit_and_setup_error(self):
        dialog = OcrDialog(None, QImage(120, 30, QImage.Format.Format_RGB32))
        with patch.object(dialog, 'run_job') as job:
            dialog.extract()
            for _ in range(3):
                dialog.show_text({'ok': True, 'text': ''})
            self.assertEqual(job.call_count, 2)
            self.assertIn('텍스트를 찾지 못했습니다', dialog.text.placeholderText())
            job.reset_mock()
            dialog.extract()
            dialog.show_text({'ok': False, 'stage': 'setup', 'error': 'Language unavailable'})
            self.assertEqual(job.call_count, 1)
            dialog.stopping = True
            dialog.show_text({'ok': True, 'text': ''})
            self.assertEqual(job.call_count, 1)
        dialog.shutdown()

    def test_selected_scale_only_and_disabled(self):
        for scale, expected in [(1, [1]), (2, [1, 2]), (4, [1, 4])]:
            with self.subTest(scale=scale):
                parent = QWidget()
                parent.ocr_scale = scale
                dialog = OcrDialog(parent, QImage(120, 30, QImage.Format.Format_RGB32))
                with patch.object(dialog, 'run_job') as job:
                    dialog.extract()
                    dialog.show_text({'ok': True, 'text': ''})
                    attempts = [call.kwargs['scale'] for call in job.call_args_list]
                    self.assertEqual(attempts, expected)
                    self.assertNotIn('배', dialog.text.placeholderText())
                    dialog.show_text({'ok': True, 'text': '완료'})
                    self.assertEqual(job.call_count, len(expected))
                dialog.shutdown()
                parent.deleteLater()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows OCR requires Windows')
    def test_real_windows_status_helper(self):
        job = OcrJob('Status')
        results = []
        loop = QEventLoop()
        job.completed.connect(lambda result: (results.append(result), loop.quit()))
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(15000)
        job.start()
        loop.exec()
        timeout.stop()
        job.stop()
        self.assertTrue(results, 'Windows helper timed out')
        self.assertTrue(results[0].get('ok'), results)
        self.assertIsInstance(results[0]['languages'], list)


if __name__ == '__main__':
    unittest.main()
