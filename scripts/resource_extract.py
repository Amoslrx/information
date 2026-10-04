"""Isolated resource parser/OCR worker. All optional parsers are imported lazily."""
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / '.tools'))
MAX_PIXELS = 24_000_000
MAX_XML_BYTES = 40 * 1024 * 1024


def image_preview(image, output):
    image = image.convert('RGB')
    image.thumbnail((1600, 2400))
    image.save(output, 'JPEG', quality=88)


def ocr_image(path, backend='auto', timeout=35):
    from PIL import Image
    with Image.open(path) as original:
        if original.width * original.height > MAX_PIXELS:
            raise ValueError('image_pixel_limit')
        image = original.convert('RGB')
    image.thumbnail((3800, 3800))
    with tempfile.TemporaryDirectory() as tmp:
        normalized = Path(tmp) / 'ocr.png'
        image.save(normalized)
        if backend in {'auto', 'tesseract'} and shutil.which('tesseract'):
            process = subprocess.run(['tesseract', str(normalized), 'stdout', '-l', 'chi_sim+eng', 'tsv'],
                                     capture_output=True, text=True, encoding='utf-8', timeout=timeout, check=True)
            rows = list(csv.DictReader(io.StringIO(process.stdout), delimiter='\t'))
            groups = {}
            for word in rows:
                if not word.get('text', '').strip():
                    continue
                key = tuple(word.get(k) for k in ('page_num', 'block_num', 'par_num', 'line_num'))
                groups.setdefault(key, []).append({'text': word['text'], 'confidence': float(word['conf']) / 100,
                    'bbox': [int(word[k]) for k in ('left', 'top', 'width', 'height')]})
            lines = [{'text': ' '.join(w['text'] for w in words), 'words': words,
                      'confidence': min(w['confidence'] for w in words)} for words in groups.values()]
            result = {'engine': 'tesseract', 'language': 'chi_sim+eng', 'lines': lines}
        elif backend in {'auto', 'windows'} and os.name == 'nt':
            env = dict(os.environ, NOTICE_OCR_IMAGE=str(normalized.resolve()))
            process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                      '-File', str(ROOT / 'scripts/ocr_image.ps1')], env=env,
                                     capture_output=True, text=True, encoding='utf-8-sig', timeout=timeout, check=True)
            result = json.loads(process.stdout)
        else:
            raise RuntimeError('ocr_backend_unavailable')
    text = '\n'.join(line['text'] for line in result.get('lines', []))
    # Join separated Chinese words only; never correct digits or hallucinate characters.
    text = re.sub(r'(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])', '', text)
    result.update(text=text, normalization='join_cjk_word_spaces', width=image.width, height=image.height)
    return result


def qr_image(path):
    import zxingcpp
    from PIL import Image
    with Image.open(path) as image:
        if image.width * image.height > MAX_PIXELS:
            raise ValueError('image_pixel_limit')
        codes = zxingcpp.read_barcodes(image.convert('RGB'), formats=zxingcpp.BarcodeFormat.QRCode)
    return [{'text': code.text, 'format': str(code.format), 'position': str(code.position)} for code in codes if code.valid and code.text]


def image_results(path, page, output_dir, prefix, backend, do_ocr=True):
    from PIL import Image
    preview = output_dir / (prefix + '.jpg')
    with Image.open(path) as image:
        if image.width * image.height > MAX_PIXELS:
            raise ValueError('image_pixel_limit')
        image_preview(image, preview)
    info = {'page': page, 'previewPath': str(preview), 'ocrStatus': 'failed', 'ocrError': '',
            'qrStatus': 'failed', 'qrError': '', 'ocr': None, 'qr': []}
    chunks = []
    try:
        info['ocr'] = ocr_image(path, backend) if do_ocr else {'text': '', 'engine': 'not_needed', 'lines': []}
        info['ocrStatus'] = 'success' if info['ocr']['text'].strip() else 'empty'
        if not do_ocr:
            info['ocrStatus'] = 'not_needed'
        if info['ocrStatus'] == 'success':
            chunks.append({'id': prefix + '-ocr', 'page': page, 'text': info['ocr']['text'], 'method': 'ocr',
                           'engine': info['ocr']['engine'], 'previewPath': str(preview)})
    except Exception as exc:
        info['ocrError'] = type(exc).__name__ + ':' + str(exc)[:180]
    try:
        info['qr'] = qr_image(path)
        info['qrStatus'] = 'success' if info['qr'] else 'not_decoded'
        for index, code in enumerate(info['qr']):
            chunks.append({'id': prefix + '-qr-' + str(index), 'page': page, 'text': code['text'], 'method': 'qr',
                           'engine': 'zxing-cpp', 'previewPath': str(preview)})
    except Exception as exc:
        info['qrError'] = type(exc).__name__ + ':' + str(exc)[:180]
    return info, chunks


def read_pdf(path, output_dir, max_pages, backend):
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(str(path))
    chunks, images, errors = [], [], []
    try:
        total = len(document)
        for index in range(min(total, max_pages)):
            page = document[index]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_range().replace('\r\n', '\n')
                finally:
                    textpage.close()
                if text.strip():
                    chunks.append({'id': 'pdf-%d-text' % (index + 1), 'page': index + 1, 'text': text,
                                   'method': 'attachment', 'engine': 'pdfium'})
                # Render every page: digital PDFs can contain posters/QR images alongside text.
                width, height = page.get_size()
                scale = min(2.5, (MAX_PIXELS / max(width * height, 1)) ** 0.5)
                bitmap = page.render(scale=scale)
                try:
                    raster = output_dir / ('page-%d.png' % (index + 1))
                    bitmap.to_pil().save(raster)
                finally:
                    bitmap.close()
                image, recognized = image_results(raster, index + 1, output_dir, 'pdf-%d' % (index + 1), backend,
                                                  do_ocr=len(text.strip()) < 80)
                images.append(image)
                if len(text.strip()) < 80 and image['ocrStatus'] == 'failed':
                    errors.append({'page': index + 1, 'error': image['ocrError']})
                # Avoid duplicate OCR of a digital page unless it adds material the text layer missed.
                if len(text.strip()) < 80:
                    chunks.extend(recognized)
                else:
                    chunks.extend(c for c in recognized if c['method'] == 'qr')
                    ocr = next((c for c in recognized if c['method'] == 'ocr'), None)
                    if ocr and re.search(r'(?:报名|截止|QQ群)', ocr['text']) and not re.search(r'(?:报名|截止|QQ群)', text):
                        chunks.append(ocr)
            except Exception as exc:
                errors.append({'page': index + 1, 'error': type(exc).__name__ + ':' + str(exc)[:160]})
            finally:
                page.close()
    finally:
        document.close()
    return {'chunks': chunks, 'images': images, 'pageCount': total, 'truncated': total > max_pages, 'errors': errors}


def bounded_zip_member(archive, name):
    info = archive.getinfo(name)
    if info.file_size > MAX_XML_BYTES:
        raise ValueError('zip_member_size_limit')
    return archive.read(name)


def read_docx(path, output_dir, backend):
    chunks, images, errors = [], [], []
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
          'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    with zipfile.ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist()) > MAX_XML_BYTES:
            raise ValueError('zip_uncompressed_size_limit')
        root = ET.fromstring(bounded_zip_member(archive, 'word/document.xml'))
        texts = []
        for index, paragraph in enumerate(root.findall('.//w:p', ns)):
            text = ''.join(n.text or '' for n in paragraph.findall('.//w:t', ns))
            if text:
                texts.append(text)
        if texts:
            chunks.append({'id': 'docx-text', 'page': None, 'text': '\n'.join(texts),
                           'method': 'attachment', 'engine': 'ooxml', 'pageBasis': 'not_paginated'})
        relationships = {}
        if 'word/_rels/document.xml.rels' in archive.namelist():
            relationships = {n.attrib.get('Id'): n.attrib.get('Target') for n in
                             ET.fromstring(bounded_zip_member(archive, 'word/_rels/document.xml.rels'))
                             if n.attrib.get('TargetMode') != 'External'}
        seen = set()
        for index, drawing in enumerate(root.findall('.//a:blip', ns)):
            ref = drawing.attrib.get('{%s}embed' % ns['r'])
            target = relationships.get(ref, '')
            member = 'word/' + target.lstrip('/')
            if not member.startswith('word/media/') or '..' in target or member in seen:
                continue
            seen.add(member)
            try:
                binary = bounded_zip_member(archive, member)
                image_path = output_dir / ('embedded-%d%s' % (index, Path(member).suffix))
                image_path.write_bytes(binary)
                image, recognized = image_results(image_path, None, output_dir, 'docx-image-%d' % index, backend)
                images.append(image)
                chunks.extend(recognized)
                if image['ocrStatus'] == 'failed':
                    errors.append({'image': member, 'error': image['ocrError']})
            except Exception as exc:
                errors.append({'image': member, 'error': type(exc).__name__ + ':' + str(exc)[:160]})
    return {'chunks': chunks, 'images': images, 'pageCount': None, 'truncated': False, 'errors': errors}


def extract_resource(request):
    path = Path(request['path'])
    output_dir = Path(request['outputDir'])
    output_dir.mkdir(parents=True, exist_ok=True)
    kind, backend = request['format'], request.get('ocrBackend', 'auto')
    if kind == 'pdf':
        result = read_pdf(path, output_dir, request.get('maxPages', 30), backend)
    elif kind == 'docx':
        result = read_docx(path, output_dir, backend)
    elif kind == 'doc':
        converter = os.environ.get('NOTICE_ANTIWORD') or shutil.which('antiword')
        if not converter:
            raise RuntimeError('legacy_doc_converter_unavailable: install antiword or set NOTICE_ANTIWORD')
        process = subprocess.run([converter, str(path)], capture_output=True, text=True, encoding='utf-8',
                                 errors='replace', check=True, timeout=45)
        result = {'chunks': [{'id': 'doc-text', 'page': None, 'text': process.stdout, 'method': 'attachment',
                              'engine': 'antiword'}] if process.stdout.strip() else [],
                  'images': [], 'pageCount': None, 'truncated': False, 'errors': []}
    elif kind == 'image':
        image, chunks = image_results(path, None, output_dir, 'image', backend)
        result = {'chunks': chunks, 'images': [image], 'pageCount': None, 'truncated': False, 'errors': []}
    else:
        raise ValueError('unsupported_format:' + kind)
    for chunk in result['chunks']:
        chunk['textHash'] = hashlib.sha256(chunk['text'].encode('utf-8')).hexdigest()
    result['status'] = 'success' if result['chunks'] else 'empty'
    if not result['chunks'] and any(i.get('ocrStatus') == 'failed' for i in result['images']):
        result['status'] = 'failed'
    if result['errors'] or result['truncated']:
        result['status'] = 'partial' if result['chunks'] else 'failed'
    return result


if __name__ == '__main__':
    try:
        output = extract_resource(json.load(sys.stdin))
    except Exception as exc:
        output = {'status': 'failed', 'error': type(exc).__name__ + ':' + str(exc)[:200],
                  'chunks': [], 'images': [], 'errors': []}
    sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False).encode('utf-8'))
