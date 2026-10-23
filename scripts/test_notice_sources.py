import unittest
from unittest.mock import patch
import crawl_xjtu_notices as crawl
from competition_sources import list_rows, article_date
from notice_content import Tree


class SourceTests(unittest.TestCase):
    def test_row_dates_do_not_leak_from_neighbor(self):
        src = {'key': 'test', 'site': '测试站', 'label': '测试栏目'}
        html = '<ul><li><a href="/info/1/1.htm">2027年竞赛报名通知</a><span>2026-09-18</span></li>' + \
               '<li><a href="/info/1/2.htm">没有日期的竞赛通知</a></li></ul>'
        rows = list_rows(html, 'https://test.edu/list.htm', src)
        self.assertEqual(rows[0]['date'], '2026-09-18')
        self.assertEqual(rows[1]['date'], '')

    def test_embedded_list_date_and_heading(self):
        src = {'key': 'test', 'site': '测试站', 'label': '测试栏目'}
        rows = list_rows('<a href="/info/1/1.htm"><h4>2027年竞赛报名通知</h4><span>2026-09-18</span></a>',
                         'https://test.edu/list.htm', src)
        self.assertEqual(rows[0]['title'], '2027年竞赛报名通知')
        self.assertEqual(rows[0]['date'], '2026-09-18')

    def test_deadline_is_not_publication_date(self):
        self.assertEqual(article_date(Tree('<p>报名截止2026-09-30</p>')), '')
        self.assertEqual(article_date(Tree('<meta name="ArticleDate" content="2026-09-18"><p>报名截止2026-09-30</p>')), '2026-09-18')

    def test_split_list_date_wins_over_dates_in_summary(self):
        src = {'key': 'test', 'site': '测试站', 'label': '测试栏目'}
        html = '<a href="/info/1/1.htm"><div class="tx-date"><span>07-29</span><b>2026</b></div>' + \
               '<h3>第十八届比赛结果</h3><p>比赛于2026年5月25日结束</p></a>'
        self.assertEqual(list_rows(html, 'https://test.edu/', src)[0]['date'], '2026-07-29')

    def test_real_pagination_order(self):
        page = '<a href="bks/4.htm">下页</a><a href="bks/1.htm">尾页</a>'
        self.assertEqual(crawl.next_page(page, 'https://ee.xjtu.edu.cn/jzxx/bks.htm'),
                         'https://ee.xjtu.edu.cn/jzxx/bks/4.htm')
        self.assertIsNone(crawl.next_page('<a href="https://other.test/">下页</a>', 'https://ee.xjtu.edu.cn/'))

    def test_crawl_follows_next_not_filename_number(self):
        src = next(s for s in crawl.SOURCES if s['key'] == 'ee_bks')
        item = '<a href="../info/1382/15736.htm"><span>2026-09-18</span><h3>2027年电赛招募通知</h3></a>'
        with patch.object(crawl, 'fetch', side_effect=[(200, item + '<a href="bks/4.htm">下页</a>'), (200, item)]) as fetch, patch.object(crawl.time, 'sleep'):
            rows = crawl.crawl_source(src, {})
        self.assertEqual(fetch.call_args_list[1].args[0], 'https://ee.xjtu.edu.cn/jzxx/bks/4.htm')
        self.assertEqual(rows[0]['url'], 'https://ee.xjtu.edu.cn/info/1382/15736.htm')

    def test_short_electronics_recruitment_name(self):
        title = '2027年电赛招募通知'
        self.assertTrue(crawl.is_competition_related(title))
        self.assertEqual(crawl.match_notice(title, [('电子设计竞赛', '全国大学生电子设计竞赛', '6')])[0],
                         '全国大学生电子设计竞赛')

    def test_specific_alias_before_generic_robot_name(self):
        idx = [('全国大学生机器人大赛', '全国大学生机器人大赛', '14'),
               ('Robomasters全国大学生机器人大赛', 'Robomasters全国大学生机器人大赛', '')]
        self.assertEqual(crawl.match_notice('RoboMasters2015全国大学生机器人大赛西北分区赛', idx)[0],
                         'Robomasters全国大学生机器人大赛')

    def test_sponsored_title_does_not_break_matching(self):
        idx = [('全国大学生节能减排社会实践与科技竞赛', '全国大学生节能减排社会实践与科技竞赛', '')]
        self.assertEqual(crawl.match_notice('关于开展西安交通大学2026年“格兰富杯”节能减排社会实践与科技竞赛的通知', idx)[0],
                         '全国大学生节能减排社会实践与科技竞赛')


if __name__ == '__main__':
    unittest.main()
