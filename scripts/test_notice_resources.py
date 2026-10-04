import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / '.tools'))
from PIL import Image, ImageDraw, ImageFont
import zxingcpp

import crawl_notice_resources as crawler
import resource_extract as parser
from notice_evidence import enrich
from notice_fields import rules, safe_deadline, check_evidence, all_facts, validate_model, validate_shape


class Response(io.BytesIO):
    def __init__(self, body, **headers):
        super().__init__(body)
        self.headers = headers
    def geturl(self):
        return 'https://example.edu/file.pdf'


def docx(path, texts):
    xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    xml += ''.join('<w:p><w:r><w:t>' + escape(t) + '</w:t></w:r></w:p>' for t in texts)
    xml += '</w:body></w:document>'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', xml.encode('utf-8'))


def record():
    return {'url': 'https://example.edu/notice', 'title': '竞赛通知', 'body': '报名安排见附件。',
            'date': '2026-09-15', 'status': 'success', 'contentHash': 'bodyhash',
            'attachments': [{'url': 'https://example.edu/arrangement.docx', 'text': '报名安排.docx'}],
            'images': [{'url': 'https://example.edu/poster.png', 'context': '报名海报'}]}


def resource(chunks, url='https://example.edu/arrangement.docx'):
    return {'id': 'asset-1', 'url': url, 'noticeUrl': record()['url'], 'kind': 'attachment', 'status': 'success',
            'download': {'sha256': 'filehash'}, 'chunks': chunks}


class DownloadTests(unittest.TestCase):
    def test_limit_header_and_stream_cleanup(self):
        for body, headers in [(b'%PDF-1234', {'Content-Length': '1000'}), (b'%PDF-' + b'a'*100, {})]:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(crawler.ResourceLimitError):
                    crawler.download('https://example.edu/file', 'https://example.edu/notice', tmp, max_bytes=20,
                                     opener=lambda *a, **k: Response(body, **headers))
                self.assertFalse(list(Path(tmp).glob('*.part')))

    def test_timeout_preserved(self):
        with patch.object(crawler, 'download', side_effect=TimeoutError('download timed out')):
            result = crawler.process_one({'id': 'a', 'url': 'https://example.edu/a', 'noticeUrl': record()['url']})
            self.assertEqual(result['status'], 'failed')
            self.assertIn('TimeoutError', result['error'])

    def test_html_and_captcha_not_parsed_as_documents(self):
        for body, expected in [(b'<html>navigation footer</html>', 'unexpected_html'),
                               (b'<!doctype html><input name="codeValue">', 'captcha_required')]:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(ValueError, expected):
                    crawler.download('https://example.edu/file.pdf', record()['url'], tmp,
                                     opener=lambda *a, **k: Response(body))

    def test_content_addressed_cache_and_referer(self):
        requests = []
        def open_request(req, **kwargs):
            requests.append(req)
            return Response(b'%PDF-test', **{'Content-Disposition': 'attachment; filename="plan.pdf"'})
        with tempfile.TemporaryDirectory() as tmp:
            blob = crawler.download('https://example.edu/file', record()['url'], tmp, opener=open_request)
            self.assertEqual(blob['format'], 'pdf')
            self.assertTrue(Path(blob['path']).is_file())
            self.assertEqual(requests[0].get_header('Referer'), record()['url'])
            asset = {'id': 'a', 'url': 'https://example.edu/file', 'noticeUrl': record()['url']}
            previous = {**asset, 'download': blob, 'status': 'success', 'parserVersion': crawler.PARSER_VERSION,
                        'chunks': [], 'images': []}
            with patch.object(crawler, 'download') as download:
                crawler.process_one(asset, previous, cache_dir=tmp)
                download.assert_not_called()
                Path(blob['path']).write_bytes(b'corrupt')
                crawler.process_one(asset, previous, cache_dir=tmp)
                download.assert_called_once()

    def test_parser_timeout(self):
        with patch.object(crawler.subprocess, 'run', side_effect=subprocess.TimeoutExpired('worker', 1)):
            result = crawler.parse_download({'path': '/tmp/file', 'format': 'pdf', 'sha256': 'a'}, parse_timeout=1)
            self.assertEqual(result['status'], 'failed')
            self.assertIn('TimeoutExpired', result['error'])

    def test_parser_config_change_reuses_blob_but_reextracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            blob = crawler.download('https://example.edu/file', record()['url'], tmp,
                                    opener=lambda *a, **k: Response(b'%PDF-test'))
            asset = {'id': 'a', 'url': 'https://example.edu/file', 'noticeUrl': record()['url']}
            previous = {**asset, 'download': blob, 'status': 'success', 'parserVersion': crawler.PARSER_VERSION,
                        'parserConfig': {'ocrBackend': 'auto', 'maxPages': 30}, 'chunks': [], 'images': []}
            with patch.object(crawler, 'download') as download, patch.object(crawler, 'parse_download',
                return_value={'status': 'empty', 'chunks': [], 'images': []}) as parse:
                crawler.process_one(asset, previous, cache_dir=tmp)
                parse.assert_not_called()
                result = crawler.process_one(asset, previous, cache_dir=tmp, max_pages=40)
                parse.assert_called_once()
                download.assert_not_called()
                self.assertEqual(result['parserConfig']['maxPages'], 40)


class ParserTests(unittest.TestCase):
    def test_word_attachment_uses_same_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'schedule.docx'
            docx(path, ['报名截止：2026年11月25日18点。', '联系人：张老师 电话：13800138000', 'QQ群：737707930'])
            parsed = parser.extract_resource({'path': str(path), 'format': 'docx', 'outputDir': str(Path(tmp)/'out')})
            self.assertEqual(parsed['status'], 'success')
            self.assertIsNone(parsed['chunks'][0]['page'])
            enriched = enrich(record(), [resource(parsed['chunks'])])
            fields = rules(enriched)
            event = safe_deadline(fields)
            self.assertEqual(event['value'], '2026-11-25')
            self.assertEqual(event['time'], '18:00')
            self.assertEqual(event['method'], 'attachment')
            self.assertEqual(event['sourceUrl'], record()['attachments'][0]['url'])
            self.assertEqual(fields['groups'][0]['number']['value'], '737707930')
            for field in all_facts(fields):
                check_evidence(field, enriched)
            validate_shape(fields)
            validate_model(fields, enriched)

    def test_pdf_page_numbers_and_scan_ocr(self):
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'schedule.pdf'
            pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
            pdf = canvas.Canvas(str(path))
            pdf.setFont('STSong-Light', 18)
            pdf.drawString(50, 760, '报名截止：2026年11月25日18点。')
            pdf.showPage()
            image = Image.new('RGB', (800, 300), 'white')
            poster = Path(tmp)/'poster.png'
            image.save(poster)
            pdf.drawImage(str(poster), 50, 500, width=400, height=150)
            pdf.save()
            with patch.object(parser, 'ocr_image', return_value={'text': 'QQ群：737707930', 'engine': 'fixture-ocr', 'lines': []}):
                parsed = parser.extract_resource({'path': str(path), 'format': 'pdf', 'outputDir': str(Path(tmp)/'out')})
            native = next(c for c in parsed['chunks'] if c['method'] == 'attachment')
            self.assertEqual(native['page'], 1)
            self.assertIn('报名截止', native['text'])
            self.assertTrue(any(c['page'] == 2 and c['method'] == 'ocr' for c in parsed['chunks']))
            enriched = enrich(record(), [resource(parsed['chunks'])])
            fields = rules(enriched)
            self.assertEqual(safe_deadline(fields)['location']['page'], 1)
            self.assertEqual(fields['groups'][0]['number']['verification'], 'needs_review')

    def test_qr_real_decode_and_no_guess(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = zxingcpp.create_barcode('https://example.com/register', zxingcpp.BarcodeFormat.QRCode)
            path = Path(tmp)/'qr.png'
            Image.fromarray(code.to_image(scale=8)).save(path)
            self.assertEqual(parser.qr_image(path)[0]['text'], 'https://example.com/register')
            plain = Path(tmp)/'plain.png'
            Image.new('RGB', (300, 300), 'white').save(plain)
            self.assertEqual(parser.qr_image(plain), [])
            with patch.object(parser, 'ocr_image', return_value={'text': '', 'engine': 'fixture-ocr', 'lines': []}):
                parsed = parser.extract_resource({'path': str(plain), 'format': 'image', 'outputDir': str(Path(tmp)/'out')})
            self.assertEqual(parsed['chunks'], [])
            self.assertEqual(parsed['images'][0]['qrStatus'], 'not_decoded')
            self.assertTrue(Path(parsed['images'][0]['previewPath']).is_file())

    def test_ocr_fail_preserves_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'plain.png'
            Image.new('RGB', (300, 300), 'white').save(path)
            with patch.object(parser, 'ocr_image', side_effect=RuntimeError('backend unavailable')):
                parsed = parser.extract_resource({'path': str(path), 'format': 'image', 'outputDir': str(Path(tmp)/'out')})
            self.assertEqual(parsed['status'], 'failed')
            self.assertTrue(Path(parsed['images'][0]['previewPath']).is_file())

    @unittest.skipUnless(os.name == 'nt' and Path('C:/Windows/Fonts/simhei.ttf').exists(), 'Windows Chinese OCR integration')
    def test_windows_poster_actual_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'poster.png'
            image = Image.new('RGB', (1800, 600), 'white')
            draw = ImageDraw.Draw(image)
            font = ImageFont.truetype('C:/Windows/Fonts/simhei.ttf', 70)
            draw.text((60,50), '报名截止：2026年11月25日18点', font=font, fill='black')
            draw.text((60,240), 'QQ群：737707930', font=font, fill='black')
            image.save(path)
            parsed = parser.extract_resource({'path': str(path), 'format': 'image', 'outputDir': str(Path(tmp)/'out'), 'ocrBackend': 'windows'})
            self.assertEqual(parsed['images'][0]['ocrStatus'], 'success')
            enriched = enrich(record(), [resource(parsed['chunks'], 'https://example.edu/poster.png')])
            fields = rules(enriched)
            self.assertEqual(fields['timeline'][0]['value'], '2026-11-25')
            self.assertEqual(fields['timeline'][0]['time'], '18:00')
            self.assertEqual(fields['groups'][0]['number']['value'], '737707930')
            self.assertIsNone(safe_deadline(fields))
            self.assertEqual(fields['groups'][0]['number']['verification'], 'needs_review')

    def test_oversized_zip_and_invalid_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'bad.docx'
            docx(path, ['text'])
            with patch.object(parser, 'MAX_XML_BYTES', 10), self.assertRaisesRegex(ValueError, 'size_limit'):
                parser.read_docx(path, Path(tmp), 'auto')
            with self.assertRaises(Exception):
                parser.read_pdf(path, Path(tmp), 30, 'auto')


class EvidenceTests(unittest.TestCase):
    def test_model_cannot_promote_ocr_to_confirmed_deadline(self):
        enriched = enrich(record(), [resource([{'id': 'ocr', 'page': 1, 'method': 'ocr',
                           'text': '报名截止2026年11月25日。'}])])
        fields = rules(enriched)
        candidate = copy.deepcopy(fields)
        candidate['timeline'][0]['verification'] = 'source_matched'
        validated = validate_model(candidate, enriched)
        self.assertEqual(validated['timeline'][0]['verification'], 'needs_review')
        self.assertIsNone(safe_deadline(validated))

    def test_resource_isolation_hash_and_no_cross_contact(self):
        chunks = [{'id': 'p1', 'page': 1, 'method': 'attachment', 'text': '联系人：张三'}]
        first = resource(chunks)
        second = resource([{'id': 'p2', 'page': 2, 'method': 'attachment', 'text': '电话：13800138000'}])
        second['id'] = 'asset-2'
        enriched = enrich(record(), [first, second])
        fields = rules(enriched)
        self.assertEqual(fields['contacts'][0]['phones'], [])
        self.assertIsNone(fields['contacts'][1]['name'])
        other = copy.deepcopy(first)
        other['noticeUrl'] = 'https://example.edu/other-notice'
        self.assertEqual(enrich(record(), [other]), record())
        first['chunks'][0]['text'] = '不同内容'
        self.assertNotEqual(enriched['contentHash'], enrich(record(), [first, second])['contentHash'])

    def test_false_page_or_quote_rejected(self):
        enriched = enrich(record(), [resource([{'id': 'p1', 'page': 2, 'method': 'attachment', 'text': '报名截止2026年11月25日。'}])])
        fields = rules(enriched)
        field = fields['timeline'][0]
        check_evidence(field, enriched)
        field['location']['page'] = 1
        with self.assertRaises(ValueError):
            check_evidence(field, enriched)


if __name__ == '__main__':
    unittest.main()
