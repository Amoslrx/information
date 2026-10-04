"""Bounded attachment/image downloads, content-addressed cache and isolated extraction."""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from email.message import Message
from pathlib import Path

from extract_notice_fields import atomic_json

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / '.cache' / 'notice-resources'
DST = ROOT / 'data/seed/notice_resources.json'
PARSER_VERSION = 1
DEFAULT_MAX_BYTES = 20 * 1024 * 1024


class ResourceLimitError(ValueError):
    pass


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            hasher.update(block)
    return hasher.hexdigest()


def detect_format(path, name='', mime=''):
    with Path(path).open('rb') as f:
        head = f.read(1024)
    if head.lstrip().lower().startswith((b'<!doctype html', b'<html')):
        if b'codeValue' in Path(path).read_bytes()[:65536] or b'createimage.jsp' in Path(path).read_bytes()[:65536]:
            raise ValueError('captcha_required: open original link and import the downloaded file')
        raise ValueError('unexpected_html_instead_of_resource')
    if head.startswith(b'%PDF-'):
        return 'pdf'
    if head.startswith(b'PK\x03\x04'):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if 'word/document.xml' in names:
                return 'docx'
        return 'unsupported'
    if head.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        return 'doc' if re.search(r'\.doc$', name, re.I) or mime == 'application/msword' else 'unsupported'
    if head.startswith((b'\x89PNG\r\n', b'\xff\xd8\xff', b'GIF8', b'II*\x00', b'MM\x00*', b'BM')) or head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image'
    return 'unsupported'


def download(url, referer, cache_dir=CACHE, max_bytes=DEFAULT_MAX_BYTES, timeout=20, total_timeout=45, opener=None):
    if urllib.parse.urlsplit(url).scheme not in {'https', 'http'}:
        raise ValueError('unsupported_resource_url')
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    url_key = hashlib.sha256((url + '\n' + referer).encode()).hexdigest()
    temporary = cache_dir / (url_key + '.part')
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (notice-resource-crawler)',
                                                   'Referer': referer, 'Accept-Encoding': 'identity'})
    start = time.monotonic()
    try:
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
            length = response.headers.get('Content-Length')
            if length and int(length) > max_bytes:
                raise ResourceLimitError('download_size_limit')
            msg = Message()
            msg['Content-Disposition'] = response.headers.get('Content-Disposition', '')
            name = msg.get_filename() or Path(urllib.parse.urlsplit(url).path).name or 'resource'
            mime = response.headers.get('Content-Type', '').split(';')[0]
            count = 0
            with temporary.open('wb') as output:
                while True:
                    if time.monotonic() - start > total_timeout:
                        raise ResourceLimitError('download_total_timeout')
                    block = response.read(65536)
                    if not block:
                        break
                    count += len(block)
                    if count > max_bytes:
                        raise ResourceLimitError('download_size_limit')
                    output.write(block)
            if not count:
                raise ValueError('empty_download')
            content_hash = digest(temporary)
            kind = detect_format(temporary, name, mime)
            extension = {'pdf': '.pdf', 'docx': '.docx', 'doc': '.doc', 'image': '.img'}.get(kind, '.bin')
            blob = cache_dir / (content_hash + extension)
            os.replace(temporary, blob)
            return {'path': str(blob), 'sha256': content_hash, 'bytes': count, 'filename': name,
                    'mime': mime, 'format': kind, 'finalUrl': response.geturl()}
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_download(blob, cache_dir=CACHE, ocr_backend='auto', max_pages=30, parse_timeout=120):
    output_dir = Path(cache_dir) / 'extracted' / blob['sha256']
    request = {'path': blob['path'], 'format': blob['format'], 'outputDir': str(output_dir),
               'ocrBackend': ocr_backend, 'maxPages': max_pages}
    try:
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/resource_extract.py')],
                                 input=json.dumps(request), capture_output=True, text=True, encoding='utf-8',
                                 timeout=parse_timeout, check=True)
        if len(process.stdout) > 12_000_000:
            raise ResourceLimitError('extraction_output_limit')
        return json.loads(process.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {'status': 'failed', 'error': type(exc).__name__ + ':' + str(exc)[:180],
                'chunks': [], 'images': [], 'errors': []}


def publish_previews(result):
    """Only bounded raster previews are published, never raw documents or active content."""
    media = ROOT / 'site/media'
    for item in result.get('images', []) + result.get('chunks', []):
        path = item.get('previewPath')
        if not path or not Path(path).is_file():
            continue
        path = Path(path)
        expected_root = (CACHE / 'extracted').resolve()
        if not path.resolve().is_relative_to(expected_root):
            raise ValueError('preview_outside_cache')
        if path.stat().st_size > 3 * 1024 * 1024:
            continue
        key = digest(path)
        media.mkdir(parents=True, exist_ok=True)
        destination = media / (key + '.jpg')
        if not destination.exists():
            shutil.copyfile(path, destination)
        item['previewUrl'] = 'media/' + destination.name


def process_one(asset, previous=None, force=False, **options):
    config = {'ocrBackend': options.get('ocr_backend', 'auto'), 'maxPages': options.get('max_pages', 30)}
    result = {**asset, 'parserVersion': PARSER_VERSION, 'parserConfig': config,
              'fetchedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
              'downloadStatus': 'failed', 'status': 'failed', 'error': '', 'chunks': [], 'images': []}
    previous = previous or {}
    prior_blob = previous.get('download', {})
    blob = None
    cache_dir = options.get('cache_dir', CACHE)
    max_bytes = options.get('max_bytes', DEFAULT_MAX_BYTES)
    if not force and prior_blob.get('path'):
        path = Path(prior_blob['path'])
        if path.resolve().is_relative_to(Path(cache_dir).resolve()) and path.is_file() and path.stat().st_size <= max_bytes and digest(path) == prior_blob.get('sha256'):
            blob = prior_blob
            if previous.get('status') in {'success', 'empty', 'unsupported'} and previous.get('parserVersion') == PARSER_VERSION and previous.get('parserConfig') == config:
                # Restore previews if the static output directory was rebuilt.
                publish_previews(previous)
                return previous
    try:
        blob = blob or download(asset['url'], asset['noticeUrl'], cache_dir=cache_dir, max_bytes=max_bytes,
                                timeout=options.get('timeout', 20), total_timeout=options.get('total_timeout', 45))
        result.update(download=blob, downloadStatus='success')
        if blob['format'] == 'unsupported':
            result.update(status='unsupported', error='unsupported_format')
            return result
        parsed = parse_download(blob, cache_dir=cache_dir, ocr_backend=options.get('ocr_backend', 'auto'),
                                max_pages=options.get('max_pages', 30), parse_timeout=options.get('parse_timeout', 120))
        publish_previews(parsed)
        result.update(parsed)
    except Exception as exc:
        result['error'] = type(exc).__name__ + ':' + str(exc)[:180]
    if result['status'] == 'failed' and previous.get('status') in {'success', 'partial'}:
        result['lastSuccess'] = {k: v for k, v in previous.items() if k != 'lastSuccess'}
    return result


def asset_list(records):
    for record in records:
        if record.get('status') != 'success':
            continue
        seen = set()
        for kind, source in [('attachment', record.get('attachments', [])), ('image', record.get('images', []))]:
            for item in source:
                url = item['url']
                if url in seen:
                    continue
                seen.add(url)
                identity = hashlib.sha256((record['url'] + '\n' + url).encode()).hexdigest()
                yield {'id': identity, 'url': url, 'noticeUrl': record['url'], 'kind': kind,
                       'name': item.get('text') or item.get('alt') or '', 'context': item.get('context') or item.get('alt') or '',
                       'noticeBodyHash': record.get('contentHash', '')}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, default=ROOT / 'data/seed/notice_bodies.json')
    ap.add_argument('--output', type=Path, default=DST)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--notice-url', action='append', default=[])
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--max-mb', type=float, default=20)
    ap.add_argument('--timeout', type=float, default=20)
    ap.add_argument('--total-timeout', type=float, default=45)
    ap.add_argument('--parse-timeout', type=float, default=120)
    ap.add_argument('--max-pages', type=int, default=30)
    ap.add_argument('--ocr-backend', choices=['auto', 'windows', 'tesseract'], default='auto')
    ap.add_argument('--import-file', type=Path, help='导入用户已下载的原附件／图片，不自动处理下载验证码')
    ap.add_argument('--asset-url', help='导入文件对应的原始资源 URL；须与通知中的附件或图片一致')
    args = ap.parse_args(argv)
    if args.limit < 0 or min(args.max_mb, args.timeout, args.total_timeout, args.parse_timeout, args.max_pages) <= 0:
        ap.error('limits and timeouts must be positive; --limit >= 0')
    with args.input.open(encoding='utf-8') as f:
        records = json.load(f)['items']
    previous = {}
    if args.output.exists():
        with args.output.open(encoding='utf-8') as f:
            previous = {r['id']: r for r in json.load(f).get('items', [])}
    assets = list(asset_list(records))
    if args.notice_url:
        assets = [a for a in assets if a['noticeUrl'] in args.notice_url]
    if args.limit:
        assets = assets[:args.limit]
    if args.import_file:
        selected = [a for a in assets if a['url'] == args.asset_url]
        if len(selected) != 1 or not args.import_file.is_file():
            ap.error('--import-file requires an existing file and one matching --asset-url/--notice-url')
        if args.import_file.stat().st_size > args.max_mb * 1024 * 1024:
            ap.error('imported file exceeds --max-mb')
        kind = detect_format(args.import_file, args.import_file.name)
        sha = digest(args.import_file)
        CACHE.mkdir(parents=True, exist_ok=True)
        cached = CACHE / (sha + args.import_file.suffix.lower())
        if cached.resolve() != args.import_file.resolve():
            shutil.copyfile(args.import_file, cached)
        a = selected[0]
        previous[a['id']] = {**a, 'parserVersion': 0, 'status': 'downloaded',
                             'download': {'path': str(cached), 'format': kind, 'sha256': sha,
                              'bytes': cached.stat().st_size, 'filename': args.import_file.name,
                              'finalUrl': a['url'], 'imported': True}}
        assets = selected
        args.force = False
    for index, asset in enumerate(assets, 1):
        previous[asset['id']] = process_one(asset, previous.get(asset['id']), args.force,
            max_bytes=int(args.max_mb * 1024 * 1024), timeout=args.timeout, total_timeout=args.total_timeout,
            parse_timeout=args.parse_timeout, max_pages=args.max_pages, ocr_backend=args.ocr_backend)
        print('%d/%d %s %s' % (index, len(assets), previous[asset['id']]['status'], asset['name'][:50]), flush=True)
        # Persist after every asset so interrupted crawls remain usable.
        atomic_json(args.output, {'schema_version': 1, 'parser_version': PARSER_VERSION,
                    'count': len(previous), 'items': list(previous.values())})
        time.sleep(0.2)
    if not args.output.exists():
        atomic_json(args.output, {'schema_version': 1, 'parser_version': PARSER_VERSION, 'count': 0, 'items': []})


if __name__ == '__main__':
    main()
