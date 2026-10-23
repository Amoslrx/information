import unittest
from notice_display import prepare_display


def notice(url, date='2026-10-01', year=2027, track=None):
    return {'url': url, 'title': '2027年电赛报名通知', 'date': date, 'competition': '电赛', 'sourceLabel': url,
            'association': {'year': year, 'editionId': str(year), 'resultTrack': track}}


class DisplayTests(unittest.TestCase):
    def test_repost_preserves_sources(self):
        rows = [notice('a'), notice('b')]
        prepare_display(rows, [])
        self.assertEqual(rows[0]['displayGroupUrl'], rows[1]['displayGroupUrl'])
        self.assertEqual(len(rows[0]['repostSources']), 2)

    def test_different_year_track_and_unknown_stay_separate(self):
        for other in [notice('b', year=2026), notice('b', track='模拟'), notice('b', year=None), notice('b', date='2026-10-02')]:
            rows = [notice('a'), other]
            prepare_display(rows, [])
            self.assertNotEqual(rows[0]['displayGroupUrl'], rows[1]['displayGroupUrl'])

    def test_cross_date_requires_identical_body(self):
        rows = [notice('a'), notice('b', date='2026-10-02')]
        for n in rows:
            n['contentHash'] = 'identical'
        prepare_display(rows, [])
        self.assertEqual(rows[0]['displayGroupUrl'], rows[1]['displayGroupUrl'])

    def test_revision_keeps_original_link(self):
        rows = [notice('a'), notice('b')]
        rows[1]['title'] = '2027年电赛延期通知'
        prepare_display(rows, [{'editions': [{'changes': [{'new': {'noticeUrl': 'b'}, 'old': [{'noticeUrl': 'a'}], 'status': 'applied'}]}]}])
        self.assertEqual(rows[1]['revisionLinks'][0]['url'], 'a')


if __name__ == '__main__':
    unittest.main()
