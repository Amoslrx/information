import unittest

from notice_editions import associate
from notice_diagnostics import report
from notice_fields import rules


def item(title='2026年测试竞赛报名', status='pending', body='', error='', parsed=False):
    n = {'title': title, 'date': '2026-09-01', 'url': 'https://example.edu/' + title,
         'competition': '测试竞赛', 'fetchStatus': status, 'fetchError': error, 'body': body}
    if parsed:
        n['fields'] = rules({**n, 'status': 'success'})
    return n


def build(items):
    comps = [{'name': '测试竞赛', 'alias': ''}]
    associate(items, comps, '2026-10-04T12:00:00')
    return comps[0]


class DiagnosticsTests(unittest.TestCase):
    def test_no_notice_is_a_collection_gap(self):
        c = build([])
        self.assertEqual(c['diagnostics']['primary'], 'no_notices')
        self.assertFalse(c['diagnostics']['hasCurrentNotice'])

    def test_old_and_unknown_notices_do_not_become_current(self):
        for title in ('2025年测试竞赛报名', '测试竞赛报名'):
            c = build([item(title)])
            self.assertEqual(c['diagnostics']['primary'], 'no_current_notice')
            self.assertEqual(c['diagnostics']['currentNoticeCount'], 0)
            self.assertEqual(c['diagnostics']['noticeCounts'], {'body_pending': 1})
        self.assertIn('identity_unknown', c['diagnostics']['reasons'])

    def test_pending_body_is_distinct_from_failed_empty_and_unparsed(self):
        for status, state in [('pending', 'body_pending'), ('failed', 'fetch_failed'),
                              ('empty', 'body_empty'), ('success', 'fields_pending')]:
            c = build([item(status=status, error='timeout' if status == 'failed' else '')])
            self.assertEqual(c['diagnostics']['primary'], state)
            g = c['editions'][0]
            self.assertEqual(g['fieldStates']['audiences'], state)
            self.assertEqual(g['registration']['deadlineState'], state)
            self.assertEqual(g['diagnostics']['notices'][0]['error'], 'timeout' if status == 'failed' else '')

    def test_empty_reason_does_not_turn_empty_into_failure(self):
        c = build([item(status='empty', error='empty_content')])
        self.assertEqual(c['diagnostics']['primary'], 'body_empty')

    def test_complete_rule_run_does_not_claim_source_omission(self):
        c = build([item(status='success', body='欢迎参加。', parsed=True)])
        self.assertEqual(c['editions'][0]['fieldStates']['audiences'], 'not_extracted')
        self.assertEqual(c['diagnostics']['primary'], 'not_extracted')
        self.assertNotIn('not_mentioned', str(c['editions'][0]['diagnostics']))

    def test_partial_coverage_keeps_valid_facts_and_explains_gaps(self):
        c = build([item(status='success', body='参赛对象：在校本科生。报名截止2026年11月20日。', parsed=True),
                   item('2026年测试竞赛补充通知', status='failed', error='body_not_found')])
        g = c['editions'][0]
        self.assertEqual(g['fieldStates']['audiences'], 'confirmed')
        self.assertEqual(g['registration']['deadlineState'], 'confirmed')
        self.assertEqual(g['fieldStates']['contacts'], 'fetch_failed')
        self.assertTrue(g['diagnostics']['partial'])
        self.assertEqual(c['registration']['status'], 'open')

    def test_conflict_and_review_are_evidence_states_not_fetch_states(self):
        c = build([item(status='success', body='报名截止2026年11月20日。', parsed=True),
                   item('2026年测试竞赛补充通知', status='success', body='报名截止2026年11月25日。', parsed=True)])
        self.assertEqual(c['diagnostics']['primary'], 'conflict')
        self.assertEqual(c['editions'][0]['registration']['deadlineState'], 'conflict')
        c = build([item(status='success', body='报名截止11月20日。', parsed=True)])
        self.assertEqual(c['editions'][0]['registration']['deadlineState'], 'needs_review')

    def test_submission_and_competition_dates_do_not_supply_deadline(self):
        c = build([item(status='success', body='作品提交2026年11月20日，比赛时间2026年11月25日。', parsed=True)])
        self.assertEqual(c['editions'][0]['registration']['deadlineState'], 'not_extracted')
        self.assertIsNone(c['registration']['nextDeadline'])

    def test_report_counts_primary_once_and_separates_coverage_scopes(self):
        c = build([item(status='failed', error='timeout'), item('2025年测试竞赛报名', status='success', parsed=True)])
        r = report([c, build([])], 2026)
        self.assertEqual(sum(r['primaryCounts'].values()), 2)
        self.assertEqual(r['relatedCoverage']['total'], 2)
        self.assertEqual(r['relatedCoverage']['success'], 1)
        self.assertEqual(r['currentCoverage']['total'], 1)
        self.assertEqual(r['currentCoverage']['success'], 0)
        self.assertEqual(r['competitions'][0]['notices'][0]['error'], 'timeout')


if __name__ == '__main__':
    unittest.main()
