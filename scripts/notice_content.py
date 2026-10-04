"""Dependency-free, scoped HTML extraction shared by static and API adapters."""
import hashlib
import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

SELECTORS = {
    'jwc.xjtu.edu.cn': [('class', 'v_news_content'), ('id', 'vsb_content')],
    'pec.xjtu.edu.cn': [('class', 'v_news_content'), ('id', 'vsb_content')],
    'ee.xjtu.edu.cn': [('class', 'v_news_content'), ('id', 'vsb_content')],
}
VOID = {'img', 'br', 'hr', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'embed', 'param', 'col', 'base'}
IGNORE = {'script', 'style', 'nav', 'footer', 'noscript'}


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []
        self.parent = None

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self):
        if self.tag in IGNORE:
            return ''
        return ''.join(c.text() if isinstance(c, Node) else c for c in self.children) + (
            '\n' if self.tag in {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3'} else '\t' if self.tag in {'td', 'th'} else '')

    def markup(self, base):
        if self.tag in IGNORE:
            return ''
        attrs = dict(self.attrs)
        for key in ('href', 'src', 'data-src', 'orisrc', 'poster'):
            if key in attrs:
                attrs[key] = absolute(attrs[key], base)
        args = ''.join(' %s="%s"' % (k, html.escape(v or '', quote=True)) for k, v in attrs.items())
        inner = ''.join(c.markup(base) if isinstance(c, Node) else html.escape(c) for c in self.children)
        if not self.tag:
            return inner
        return '<%s%s>' % (self.tag, args) + ('' if self.tag in VOID else inner + '</%s>' % self.tag)


class Tree(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        node.parent = self.stack[-1]
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def absolute(value, base):
    value = urljoin(base, html.unescape(value or '').strip())
    return value if urlsplit(value).scheme in {'http', 'https'} else ''


def clean(value):
    return re.sub(r'[ \t\r\f\v]+', ' ', value.replace('\xa0', ' ').replace('\u3000', ' ')).strip()


def cms_root(source, url):
    tree = Tree(source)
    selectors = SELECTORS.get(urlsplit(url).hostname, [('class', 'v_news_content')])
    for key, value in selectors:
        for node in tree.root.walk():
            if value in (node.attrs.get(key) or '').split():
                # VSB renders its download list after v_news_content, in the
                # same article form. Collect only CMS download anchors there.
                article = node.parent
                while article is not None and article.tag != 'form':
                    article = article.parent
                node.extra_attachments = []
                if article is not None:
                    for link in article.walk():
                        if link.tag == 'a' and '/system/_content/download.jsp' in (link.attrs.get('href') or ''):
                            node.extra_attachments.append({'url': link.attrs['href'], 'name': clean(link.text())})
                return node
    raise ValueError('body_not_found: no configured article selector matched')


def extract(root, url, attachments=()):
    paragraphs, tables, images, links, blocks = [], [], [], [], []

    def visit(node):
        if node.tag in IGNORE:
            return
        if node.tag == 'table':
            rows = []
            for tr in node.walk():
                if tr.tag == 'tr':
                    rows.append([{'text': clean(c.text()), 'rowspan': c.attrs.get('rowspan', '1'),
                                  'colspan': c.attrs.get('colspan', '1'), 'header': c.tag == 'th'}
                                 for c in tr.children if isinstance(c, Node) and c.tag in {'td', 'th'}])
            tables.append({'rows': rows, 'html': node.markup(url)})
            blocks.append({'type': 'table', 'index': len(tables) - 1})
            return
        if node.tag in {'p', 'li', 'h1', 'h2', 'h3', 'h4', 'blockquote'}:
            # Descend if a block wraps a table; never duplicate table text as a paragraph.
            if not any(c.tag == 'table' for c in node.walk()):
                text = clean(node.text())
                if text:
                    paragraphs.append(text)
                    blocks.append({'type': 'paragraph', 'index': len(paragraphs) - 1})
                return
        for child in node.children:
            if isinstance(child, Node):
                visit(child)
            elif child.strip():
                paragraphs.append(clean(child))
                blocks.append({'type': 'paragraph', 'index': len(paragraphs) - 1})

    visit(root)
    # Resources are scoped to the selected article, including those inside table cells.
    def resources(node):
        if node.tag in IGNORE:
            return
        if node.tag == 'img':
            src = absolute(node.attrs.get('data-src') or node.attrs.get('src') or node.attrs.get('orisrc'), url)
            if src:
                context = clean(node.parent.text()) if node.parent is not None else ''
                if not context and node.parent is not None and node.parent.parent is not None:
                    siblings = node.parent.parent.children
                    index = siblings.index(node.parent)
                    preceding = [c for c in siblings[:index] if isinstance(c, Node) and clean(c.text())]
                    if preceding:
                        context = clean(preceding[-1].text())
                images.append({'url': src, 'alt': node.attrs.get('alt', ''), 'context': context})
        if node.tag == 'a':
            href = node.attrs.get('href') or ''
            dest = absolute(href, url)
            text = clean(node.text())
            if dest and not href.startswith('#') and dest != url and not any(x in text for x in ('上一篇', '下一篇', '打印', '关闭')):
                file = re.search(r'\.(pdf|docx?|xlsx?|pptx?|zip|rar|7z|csv|txt)(?:$|[?#])|/download\.jsp', dest, re.I)
                form = any(x in dest.lower() or x in text for x in ('docs.qq.com', 'wj.qq.com', 'forms.office', 'signup', 'register', 'enroll', '报名'))
                links.append({'url': dest, 'text': text or dest, 'kind': 'file' if file else 'form' if form else 'link'})
        for child in node.children:
            if isinstance(child, Node):
                resources(child)
    resources(root)
    for a in list(attachments or []) + getattr(root, 'extra_attachments', []):
        if isinstance(a, dict):
            dest = absolute(a.get('url') or a.get('fileUrl') or a.get('href'), url)
            if dest:
                links.append({'url': dest, 'text': a.get('name') or a.get('fileName') or '附件', 'kind': 'file'})
    links = list({x['url']: x for x in links}.values())
    links.sort(key=lambda x: {'form': 0, 'file': 1, 'link': 2}[x['kind']])
    body = '\n'.join(clean(line) for line in root.text().splitlines() if clean(line))
    result = {'body': body, 'bodyHtml': root.markup(url), 'bodyLen': len(body), 'paragraphs': paragraphs,
              'tables': tables, 'blocks': blocks, 'images': images, 'links': links,
              'attachments': [x for x in links if x['kind'] == 'file']}
    canonical = {k: result[k] for k in ('body', 'paragraphs', 'tables', 'images', 'links', 'blocks')}
    result['contentHash'] = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    return result
