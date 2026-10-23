import unittest
from wechat_articles import canonical_url, parse_article


class WechatTests(unittest.TestCase):
    def test_urls(self):
        self.assertEqual(canonical_url('https://mp.weixin.qq.com/s/abc?scene=1'), 'https://mp.weixin.qq.com/s/abc')
        for url in ['https://evil.test/s/abc', 'https://mp.weixin.qq.com.evil.test/s/abc', 'https://mp.weixin.qq.com/profile_ext']:
            with self.assertRaises(ValueError):
                canonical_url(url)

    def test_metadata(self):
        result = parse_article('<h1 id="activity-name">竞赛</h1><span id="js_name">账号</span><span id="publish_time">2026年10月23日</span><div id="js_content"><p>报名通知</p></div>', 'https://mp.weixin.qq.com/s/abc')
        self.assertEqual(result['date'], '2026-10-23')
        self.assertEqual(result['account'], '账号')
        self.assertEqual(result['body'], '报名通知')

    def test_missing_date_and_image(self):
        r = parse_article('<div id="js_content"><img data-src="https://example.org/poster.png"></div>', 'https://mp.weixin.qq.com/s/abc')
        self.assertEqual(r['date'], '')
        self.assertEqual(len(r['images']), 1)
        self.assertEqual(r['metadataStatus'], 'incomplete')

    def test_blocked(self):
        for source in ['<p>环境异常，请验证</p>', '<p>内容已被删除</p>', '<div id="js_content"></div>']:
            with self.assertRaises(ValueError):
                parse_article(source, 'https://mp.weixin.qq.com/s/abc')


if __name__ == '__main__':
    unittest.main()
