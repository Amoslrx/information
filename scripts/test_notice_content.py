import json
import tempfile
import unittest
import contextlib
import io
from pathlib import Path
from unittest.mock import patch

import build_site_data as build
import crawl_notice_bodies as crawl
from notice_content import Tree, cms_root, extract


class ContentTests(unittest.TestCase):
    url = 'https://jwc.xjtu.edu.cn/info/1/2.htm'

    def test_scope_structure_and_resources(self):
        source = """<nav>导航</nav><div class='v_news_content'><p>202<span>6</span>年通知</p>
        <div><p>第一段</p><table><tr><th rowspan='2'>项目</th><td><p>报名</p></td></tr>
        <tr><td colspan='2'>安排</td></tr></table><p>表后</p></div>
        <p><img src='/images/a.png' alt='二维码'><a href='../../files/a.pdf'>附件</a>
        <a href='https://docs.qq.com/form/one'>报名表</a></p></div><footer>页脚</footer>"""
        result = extract(cms_root(source, self.url), self.url)
        self.assertNotIn('导航', result['body'])
        self.assertNotIn('页脚', result['body'])
        self.assertIn('2026年通知', result['body'])
        self.assertEqual(result['paragraphs'][:3], ['2026年通知', '第一段', '表后'])
        self.assertEqual([b['type'] for b in result['blocks'][:4]], ['paragraph', 'paragraph', 'table', 'paragraph'])
        self.assertEqual(result['tables'][0]['rows'][0][0]['rowspan'], '2')
        self.assertEqual(result['images'][0]['url'], 'https://jwc.xjtu.edu.cn/images/a.png')
        self.assertEqual(result['attachments'][0]['url'], 'https://jwc.xjtu.edu.cn/files/a.pdf')
        self.assertEqual(result['links'][0]['kind'], 'form')
        self.assertEqual(result['contentHash'], extract(cms_root(source, self.url), self.url)['contentHash'])
        self.assertNotEqual(result['contentHash'], extract(cms_root(source.replace('表后', '修订'), self.url), self.url)['contentHash'])

    def test_no_truncation(self):
        result = extract(Tree('<p>' + '正文' * 9000 + '</p>').root, self.url)
        self.assertEqual(result['bodyLen'], 18000)
        self.assertEqual(len(result['links']), 0)

    def test_cms_external_attachment_scope(self):
        source = """<nav><a href='/system/_content/download.jsp?id=other'>导航文件</a></nav>
        <form><div class='v_news_content'><p>通知</p></div><ul><li>附件【
        <a href='/system/_content/download.jsp?wbfileid=123'>名单.xlsx</a>】</li></ul></form>
        <footer>页脚</footer>"""
        result = extract(cms_root(source, self.url), self.url)
        self.assertEqual(result['body'], '通知')
        self.assertEqual(len(result['attachments']), 1)
        self.assertEqual(result['attachments'][0]['text'], '名单.xlsx')

    def test_statuses(self):
        notice = {'url': self.url, 'date': '2026-09-23', 'source': 'jwc'}
        cases = [('<div class="v_news_content"><p>短通知</p></div>', 'success', ''),
                 ('<div class="v_news_content"></div>', 'empty', 'empty_content'),
                 ('<nav>导航</nav><footer>页脚</footer>', 'failed', 'body_not_found')]
        for source, status, error in cases:
            with self.subTest(status=status), patch.object(crawl, 'fetch', return_value=source):
                result = crawl.crawl_one(notice)
                self.assertEqual(result['status'], status)
                self.assertIn(error, result['error'])
                self.assertEqual(result['date'], notice['date'])
                self.assertIn('+00:00', result['fetchedAt'])
        with patch.object(crawl, 'fetch', side_effect=TimeoutError('timeout')):
            self.assertEqual(crawl.crawl_one(notice)['status'], 'failed')

    def test_dynamic_adapter(self):
        notice = {'url': 'https://tuanwei.xjtu.edu.cn/passage?id=4760'}
        data = {'success': True, 'data': {'headline': '通知', 'publish': '2026-09-14', 'source': '团委',
                'content': '<p>报名</p><table><tr><td>安排</td></tr></table><img src="/a.png">',
                'attachments': [{'fileUrl': '/b.docx', 'fileName': '报名表'}]}}
        with patch.object(crawl, 'fetch', return_value=json.dumps(data)) as fetch:
            result = crawl.crawl_one(notice)
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['source'], '团委')
            self.assertEqual(len(result['tables']), 1)
            self.assertTrue(result['attachments'][0]['url'].endswith('/b.docx'))
            self.assertIn('/api/v1/article?articleId=4760', fetch.call_args.args[0])
        with patch.object(crawl, 'fetch') as fetch:
            result = crawl.crawl_one({'url': 'https://tuanwei.xjtu.edu.cn/passage'})
            self.assertIn('no_article_id', result['error'])
            fetch.assert_not_called()
        for payload, status in [({'success': False, 'message': '错误'}, 'failed'),
                                ({'success': True, 'data': {}}, 'empty'),
                                ({'success': True, 'data': []}, 'failed')]:
            with patch.object(crawl, 'fetch', return_value=json.dumps(payload)):
                self.assertEqual(crawl.crawl_one(notice)['status'], status)

    def test_build_join(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(build, 'SEED', tmp):
            record = {'url': self.url, 'status': 'success', 'excerpt': '正文摘要', 'contact': '张老师',
                      'body': '正文摘要\n报名：https://docs.qq.com/form/one\n联系人：张老师 电话：13800138000',
                      'phone': '12345678901', 'email': 'a@example.com',
                      'links': [{'url': 'https://docs.qq.com/form/one', 'text': '报名', 'kind': 'form'}]}
            Path(tmp, 'notice_bodies.json').write_text(json.dumps({'items': [record]}), encoding='utf-8')
            Path(tmp, 'notices.json').write_text(json.dumps({'items': [{'url': self.url, 'title': '竞赛报名通知',
                                                                      'date': '2026-09-23'}]}), encoding='utf-8')
            notices, _ = build.load_notices({})
            self.assertEqual(notices[0]['excerpt'], record['body'])
            self.assertEqual(notices[0]['fields']['contacts'][0]['name']['value'], '张老师')
            self.assertEqual(notices[0]['links'][0]['kind'], 'form')
            record.update(status='failed', error='timeout')
            Path(tmp, 'notice_bodies.json').write_text(json.dumps({'items': [record]}), encoding='utf-8')
            self.assertEqual(build.load_bodies(), {})

    def test_incremental_and_failed_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            notices = Path(tmp, 'notices.json')
            bodies = Path(tmp, 'bodies.json')
            notices.write_text(json.dumps({'items': [{'url': self.url, 'is_competition': True}]}), encoding='utf-8')
            with patch.object(crawl, 'NOTICES', str(notices)), patch.object(crawl, 'DST', str(bodies)), \
                 patch.object(crawl, 'DELAY', 0), contextlib.redirect_stdout(io.StringIO()):
                with patch.object(crawl, 'fetch', return_value='<div class="v_news_content"><p>原正文</p></div>'):
                    crawl.main([])
                with patch.object(crawl, 'fetch') as fetch:
                    crawl.main([])
                    fetch.assert_not_called()
                with patch.object(crawl, 'fetch', side_effect=TimeoutError('timeout')):
                    crawl.main(['--force'])
                result = json.loads(bodies.read_text(encoding='utf-8'))
                self.assertEqual(result['items'][0]['status'], 'failed')
                self.assertEqual(result['items'][0]['lastSuccess']['body'], '原正文')
                self.assertEqual(result['byStatus']['failed'], 1)
                with patch.object(crawl, 'fetch', return_value='<div class="v_news_content"><p>新正文</p></div>'):
                    crawl.main([])
                result = json.loads(bodies.read_text(encoding='utf-8'))
                self.assertEqual(result['items'][0]['status'], 'success')
                self.assertEqual(result['items'][0]['body'], '新正文')

    def test_downstream_does_not_parse_shell(self):
        import extract_deadlines as deadlines
        notice = {'url': self.url, 'title': '竞赛报名', 'date': '2026-09-01'}
        with patch.dict(deadlines.BODIES_CACHE, {self.url: {'status': 'failed', 'error': 'body_not_found'}}, clear=True), \
             patch.object(crawl, 'fetch') as fetch:
            self.assertEqual(deadlines.work(notice)['error'], 'body_not_found')
            fetch.assert_not_called()
        with patch.dict(deadlines.BODIES_CACHE, {self.url: {'status': 'success', 'body': '报名截止日期为2026年11月25日。',
                                                         'contentHash': 'testhash'}}, clear=True):
            result = deadlines.work(notice)
            self.assertEqual(result['deadline'], '2026-11-25')
            self.assertEqual(result['contentHash'], 'testhash')


if __name__ == '__main__':
    unittest.main()
