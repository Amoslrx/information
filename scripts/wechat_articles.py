"""Import public WeChat article URLs and extract cached, evidenced article bodies."""
import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from notice_content import Tree, extract

ROOT = Path(__file__).resolve().parent.parent


def canonical_url(value):
    u = urlsplit(value.strip())
    if u.scheme != 'https' or u.netloc != 'mp.weixin.qq.com':
        raise ValueError('只接受 https://mp.weixin.qq.com 的文章链接')
    if re.fullmatch(r'/s/[A-Za-z0-9_-]+', u.path):
        return 'https://mp.weixin.qq.com' + u.path
    q = parse_qs(u.query)
    if u.path == '/s' and all(q.get(k) for k in ('__biz', 'mid', 'idx', 'sn')):
        return 'https://mp.weixin.qq.com/s?' + urlencode({k: q[k][0] for k in ('__biz', 'mid', 'idx', 'sn')})
    raise ValueError('不是可识别的微信文章链接')


def parse_article(source, url):
    tree = Tree(source)
    nodes = {n.attrs['id']: n for n in tree.root.walk() if n.attrs.get('id')}
    root = nodes.get('js_content')
    if root is None:
        visible = tree.root.text()
        reason = next((code for word, code in [('环境异常', 'verification_required'), ('验证码', 'verification_required'),
                      ('已被删除', 'deleted'), ('无法查看', 'unavailable'), ('登录', 'login_required')]
                       if word in visible), 'body_not_found')
        raise ValueError(reason)
    content = extract(root, url)
    if not content['body'] and not content['images']:
        raise ValueError('empty_body')
    def text(key):
        return nodes[key].text().strip() if key in nodes else ''
    title = text('activity-name')
    account = text('js_name')
    date = ''
    evidence = text('publish_time')
    match = re.search(r'(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})', evidence)
    if match:
        date = dt.date(*map(int, match.groups())).isoformat()
    else:
        match = re.search(r'\b(?:var\s+)?ct\s*=\s*[\"\x27](\d{10})[\"\x27]', source)
        if match:
            evidence = match.group(0)
            date = dt.datetime.fromtimestamp(int(match[1]), dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    return dict(content, url=url, title=title, account=account, sourceLabel=account,
                date=date, dateEvidence=evidence, status='success', error='',
                metadataStatus='complete' if title and account and date else 'incomplete',
                accountVerification='unverified', sourceKind='wechat_article')


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urlsplit(newurl)
        if u.scheme != 'https' or u.netloc != 'mp.weixin.qq.com':
            raise ValueError('unexpected_redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    with build_opener(SafeRedirect()).open(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=25) as response:
        data = response.read(5_000_001)
        if len(data) > 5_000_000:
            raise ValueError('response_too_large')
        return data.decode('utf-8', errors='replace')


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--import-file', type=Path, help='UTF-8 文件，每行一个文章 URL')
    p.add_argument('--fetch', action='store_true', help='抓取待处理和失败的文章；成功记录跳过')
    p.add_argument('--limit', type=int, default=20)
    p.add_argument('--html', type=Path, help='导入用户在浏览器中保存的文章 HTML')
    p.add_argument('--url', help='本地 HTML 对应的真实文章 URL')
    p.add_argument('--output', type=Path, default=ROOT / 'data/seed/wechat_bodies.json')
    args = p.parse_args()
    payload = json.loads(args.output.read_text(encoding='utf-8')) if args.output.exists() else {'items': []}
    records = {r['url']: r for r in payload['items']}
    if args.html:
        if not args.url:
            p.error('--html 必须同时提供 --url')
        url = canonical_url(args.url)
        source = args.html.read_text(encoding='utf-8-sig')
        try:
            records[url] = dict(parse_article(source, url), importedFrom=str(args.html),
                                importedAt=dt.datetime.now(dt.timezone.utc).isoformat())
        except ValueError as exc:
            records.setdefault(url, {'url': url, 'status': 'failed', 'error': str(exc), 'sourceKind': 'wechat_article'})
            print('HTML 导入失败：' + str(exc))
    if args.import_file:
        # Validate the entire import before changing the queue.
        urls = [canonical_url(line) for line in args.import_file.read_text(encoding='utf-8-sig').splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
        for url in urls:
            records.setdefault(url, {'url': url, 'status': 'pending', 'sourceKind': 'wechat_article', 'error': ''})
    attempted = 0
    for url, old in list(records.items()):
        if not args.fetch or old['status'] == 'success' or attempted >= args.limit:
            continue
        attempted += 1
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            source = fetch(url)
            import hashlib
            raw = ROOT / 'data/raw/wechat' / (hashlib.sha256(url.encode()).hexdigest() + '.html')
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(source, encoding='utf-8')
            records[url] = dict(parse_article(source, url), fetchedAt=now, rawPath=str(raw.relative_to(ROOT)))
        except Exception as exc:
            records[url] = dict(old, status='failed', error=str(exc)[:300], attemptedAt=now)
        save(args.output, {'schema_version': 1, 'count': len(records), 'items': list(records.values())})
        time.sleep(1.6)
    save(args.output, {'schema_version': 1, 'count': len(records), 'items': list(records.values())})
    print('文章队列 %d 条，本次尝试 %d 条' % (len(records), attempted))


if __name__ == '__main__':
    main()
