"""Additional public sources for the A/B and electrical C catalogue.

Uses the shared HTML tree, isolates each article row before extracting dates,
and records failures separately so an empty/JS page is never called coverage.
"""
import re
import json
from datetime import date, datetime
from urllib.parse import urljoin, urlsplit
from notice_content import Tree

DATE = re.compile(r'(?<!\d)(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})(?:日)?(?!\d)')


def dates(text):
    out = []
    for y, m, d in DATE.findall(text):
        try:
            value = date(int(y), int(m), int(d)).isoformat()
            if value not in out:
                out.append(value)
        except ValueError:
            pass
    return out


def date_element(node):
    """Prefer a row's explicit date element over dates in its summary."""
    for part in node.walk():
        if not re.search(r'date|time', part.attrs.get('class', ''), re.I):
            continue
        text = part.text().strip()
        found = dates(text)
        if len(found) == 1:
            return found[0]
        split = re.fullmatch(r'(\d{1,2})[-/](\d{1,2})\s*(20\d{2})', text)
        if split:
            return date(int(split[3]), int(split[1]), int(split[2])).isoformat()
    return ''


def article_date(tree):
    for node in tree.root.walk():
        if node.tag == 'meta' and (node.attrs.get('name') or node.attrs.get('property') or '').lower() in (
                'articledate', 'pubdate', 'publishdate', 'article:published_time', 'date', 'dc.date'):
            found = dates(node.attrs.get('content', ''))
            if found:
                return found[0]
        if re.search(r'(?:^|[-_\s])(?:publish[-_]?time|pubdate|news[-_]?date|article[-_]?date|newsInfoDate)(?:$|[-_\s])',
                     node.attrs.get('class', ''), re.I):
            found = dates(node.text())
            if len(found) == 1:
                return found[0]
    # Only labelled publication metadata, never the first date in the body.
    for node in tree.root.walk():
        if 'article-sm' in node.attrs.get('class', '').split():
            found = dates(node.text())
            if len(found) == 1:
                return found[0]
    match = re.search(r'(?:发布时间|发布日期|发表时间|发布于|日期)\s*[:：]?\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})', tree.root.text())
    return dates(match[1])[0] if match and dates(match[1]) else ''


def list_rows(source, url, src):
    tree = Tree(source)
    if src['key'] == 'acm_vjudge':
        payload = next((n.text() for n in tree.root.walk() if n.tag == 'textarea' and n.attrs.get('name') == 'dataJson'), '')
        if payload:
            data = json.loads(payload)
            # Group creation and contest start timestamps are not publication dates.
            return [{'title': data.get('brief', '西交ACM校队选拔') + ' ' + data.get('shortName', ''),
                     'date': '', 'url': url, 'site': src['site'], 'source': src['key'],
                     'sourceLabel': src['label'], 'dateUnavailableReason': '平台仅标注团队创建时间与比赛时间，未标注公告发布时间'}]
    rows, seen = [], set()
    pattern = src.get('article_pattern', r'/info/\d+/\d+\.htm')
    for anchor in tree.root.walk():
        if anchor.tag != 'a':
            continue
        href = urljoin(url, anchor.attrs.get('href') or '')
        if not re.search(pattern, href) or urlsplit(href).netloc != urlsplit(url).netloc:
            continue
        headings = [n.text().strip() for n in anchor.walk() if n.tag in ('h2', 'h3', 'h4') or
                    'news-title' in n.attrs.get('class', '').split()]
        title = (anchor.attrs.get('title') or (headings[0] if headings else anchor.text())).strip()
        title = DATE.sub('', title).strip() if not headings and not anchor.attrs.get('title') else title
        # Some responsive lists duplicate the same label for desktop/mobile.
        title = re.sub(r'^置顶\s*', '', title)
        if len(title) % 2 == 0 and title[:len(title)//2] == title[len(title)//2:]:
            title = title[:len(title)//2]
        if len(title) < 6 or href in seen:
            continue
        node, published = anchor, ''
        for _ in range(5):
            if node is None:
                break
            links = {urljoin(url, x.attrs.get('href') or '') for x in node.walk()
                     if x.tag == 'a' and re.search(pattern, urljoin(url, x.attrs.get('href') or ''))}
            if len(links) > 1:
                break
            published = date_element(node)
            if published:
                break
            found = dates(node.text().replace(title, ''))
            if len(found) == 1:
                published = found[0]
                break
            node = node.parent
        rows.append({'title': re.sub(r'\s+', ' ', title), 'date': published, 'url': href,
                     'site': src['site'], 'source': src['key'], 'sourceLabel': src['label']})
        seen.add(href)
    return rows


def crawl(src, fetch, next_page, pause):
    rows, seen = {}, set()
    url = src['url']
    status = {'key': src['key'], 'url': url, 'checkedAt': datetime.now().isoformat(timespec='seconds'),
              'pages': 0, 'count': 0, 'listed': 0, 'errors': []}
    for _ in range(src.get('max_pages', 3)):
        if not url or url in seen:
            break
        seen.add(url)
        try:
            _, source = fetch(url)
            status['pages'] += 1
            found = list_rows(source, url, src)
            status['listed'] += len(found)
            for row in found:
                if src.get('keywords') and not re.search(src['keywords'], row['title'], re.I):
                    continue
                if not row['date']:
                    try:
                        pause()
                        _, detail = fetch(row['url'])
                        row['date'] = article_date(Tree(detail))
                    except Exception as exc:
                        status['errors'].append(row['url'] + ': ' + str(exc)[:120])
                rows[row['url']] = row
            url = next_page(source, url)
            pause()
        except Exception as exc:
            status['errors'].append(url + ': ' + str(exc)[:160])
            break
    # Known evidence pages stay watched even when they have left list page 1.
    for url in src.get('seeds', []):
        if url in rows:
            continue
        try:
            _, source = fetch(url)
            tree = Tree(source)
            titles = [n.attrs.get('content') for n in tree.root.walk()
                      if n.tag == 'meta' and (n.attrs.get('name') or '').lower() == 'articletitle']
            if not titles:
                titles = [n.text().strip() for n in tree.root.walk() if n.tag == 'h1']
            if not titles:
                titles = [n.text().strip() for n in tree.root.walk() if n.tag == 'title']
            title = next((t for t in titles if t), '')
            if title and not re.search(r'403|404|Access Denied|Just a moment|验证', title, re.I):
                rows[url] = {'title': title, 'date': article_date(tree), 'url': url,
                             'site': src['site'], 'source': src['key'], 'sourceLabel': src['label']}
            pause()
        except Exception as exc:
            status['errors'].append(url + ': ' + str(exc)[:160])
    status['count'] = len(rows)
    status['missingDates'] = sum(not r['date'] for r in rows.values())
    status['state'] = ('partial' if status['errors'] or status['missingDates'] else 'ok') if rows else 'needs_adapter_or_unavailable'
    if not rows and status['listed'] and not status['errors']:
        status['state'] = 'ok_no_matching_notices'
    return list(rows.values()), status
