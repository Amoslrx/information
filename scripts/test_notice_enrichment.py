"""Second-batch regressions: crawling, edition evidence and unseen assets."""
import unittest
from unittest.mock import patch

from crawl_notice_bodies import crawl_paced, priority_candidates
from notice_editions import associate
from notice_fields import rules, safe_deadline, check_evidence, all_facts, fact
from notice_hints import resource_hints


def article(body='', title='2026年第八届测试竞赛报名通知', **kwargs):
    return {'url': 'https://example.edu/notice/1', 'title': title, 'competition': '测试竞赛',
            'date': '2026-04-01', 'body': body, 'status': 'success', 'fetchStatus': 'success', **kwargs}


def competition(*notices):
    comps = [{'name': '测试竞赛', 'alias': ''}]
    associate(list(notices), comps, '2026-10-04T12:00:00')
    return comps[0]


class EnrichmentTests(unittest.TestCase):
    def test_publication_year_ranks_crawl_without_proving_identity(self):
        n = article(title='测试竞赛报名通知')
        selected = priority_candidates([n], [{'name': '测试竞赛', 'alias': ''}], 2026, '2025-10-04')
        self.assertEqual(selected[0]['crawlPriority'], 0)
        self.assertFalse(competition(n)['diagnostics']['hasCurrentNotice'])

    def test_retry_only_transient_failures_and_bound_attempts(self):
        failed = {'status': 'failed', 'error': 'TimeoutError: timed out', 'fetchedAt': 'now'}
        ok = {**failed, 'status': 'success', 'error': ''}
        with patch('crawl_notice_bodies.crawl_one', side_effect=[failed.copy(), ok.copy()]) as crawl, patch('crawl_notice_bodies.time.sleep'):
            self.assertEqual(crawl_paced({}, 2)['attempts'], 2)
            self.assertEqual(crawl.call_count, 2)
        with patch('crawl_notice_bodies.crawl_one', return_value=failed.copy()), patch('crawl_notice_bodies.time.sleep'):
            self.assertEqual(crawl_paced({}, 2)['attempts'], 3)
        with patch('crawl_notice_bodies.crawl_one', return_value={**failed, 'error': 'body_not_found'}), patch('crawl_notice_bodies.time.sleep'):
            self.assertEqual(crawl_paced({}, 2)['attempts'], 1)

    def test_body_proves_year_and_parenthesized_title_year(self):
        for n in [article('现举办2026年第八届测试竞赛。', title='第八届测试竞赛报名'),
                  article(title='第八届测试竞赛（2026）报名')]:
            self.assertTrue(competition(n)['diagnostics']['hasCurrentNotice'])

    def test_deadline_and_historical_reference_do_not_supply_edition_year(self):
        n = article('报名截止2026年11月20日。往届2026年第八届测试竞赛共有200人。', title='第八届测试竞赛报名')
        self.assertFalse(competition(n)['diagnostics']['hasCurrentNotice'])
        old = article('报名截止2026年1月5日。', title='2025年第八届测试竞赛报名')
        self.assertFalse(competition(old)['diagnostics']['hasCurrentNotice'])

    def test_title_body_identity_conflict_is_not_current(self):
        n = article('2025年第七届测试竞赛接受报名。')
        c = competition(n)
        self.assertFalse(c['diagnostics']['hasCurrentNotice'])
        self.assertTrue(c['diagnostics']['notices'][0]['identityConflicts'])

    def test_explicit_reference_carries_year_with_evidence(self):
        anchor = article()
        n = article(title='测试竞赛延期通知', url='https://example.edu/notice/2')
        raw = '根据本届报名通知，现延期。'
        n['body'] = raw
        n['noticeReferences'] = [fact(anchor['url'], raw, n, {'type': 'body', 'start': 0, 'end': len(raw)})]
        comps = [{'name': '测试竞赛', 'alias': ''}]
        linked = next(x for x in associate([anchor, n], comps, '2026-10-04T12:00:00')['测试竞赛'] if x['url'] == n['url'])['association']
        self.assertEqual(linked['identityMethod'], 'explicit_reference')
        self.assertEqual(linked['year'], 2026)
        self.assertEqual(linked['referenceEvidence']['raw'], raw)

    def test_registration_range_and_submission_are_distinct(self):
        n = article('报名时间：2026年3月25日至4月22日。作品提交截止2026年5月10日。')
        fields = rules(n)
        self.assertEqual([x['kind'] for x in fields['timeline']], ['registration_start', 'registration_deadline', 'submission'])
        self.assertEqual(safe_deadline(fields)['value'], '2026-04-22')
        for f in all_facts(fields):
            check_evidence(f, n)

    def test_tentative_deadline_needs_review(self):
        fields = rules(article('报名截止初定2026年5月15日23:59。'))
        self.assertIsNone(safe_deadline(fields))
        self.assertEqual(fields['timeline'][0]['verification'], 'needs_review')

    def test_contact_names_are_people_and_short_phone_is_not_group(self):
        n = article('请体现指导组具体老师姓名，并联系指导组老师邮箱cnsoftbei@qq.com。\n'
                    '校内联系人及联系方式：田老师13227767812，李老师电话82668901。\n'
                    '【大赛官方QQ群】\n一群：730549279，二群：868384661')
        fields = rules(n)
        self.assertEqual([c['name']['value'] for c in fields['contacts'] if c['name']], ['田老师', '李老师'])
        self.assertEqual([[p['value'] for p in c['phones']] for c in fields['contacts']], [['13227767812'], ['82668901']])
        self.assertEqual([g['number']['value'] for g in fields['groups']], ['730549279', '868384661'])

    def test_unread_attachment_explains_deadline_gap(self):
        n = article('报名时间安排详见附件。', attachments=[{'url': 'https://example.edu/a.pdf', 'text': '报名安排.pdf'}])
        n['fields'] = rules(n)
        n['resourceHints'] = resource_hints(n)
        g = competition(n)['editions'][0]
        self.assertEqual(g['registration']['deadlineState'], 'resource_pending')
        self.assertEqual(n['resourceHints'][0]['url'], 'https://example.edu/a.pdf')
        check_evidence(n['resourceHints'][1]['evidence'], n)

    def test_missing_image_still_has_original_page_entry(self):
        n = article('扫码报名，请查看报名二维码。')
        hint = resource_hints(n)[0]
        self.assertEqual(hint['state'], 'resource_pending')
        self.assertEqual(hint['url'], n['url'])
        self.assertEqual(hint['error'], 'referenced_asset_not_collected')

    def test_failed_and_empty_ocr_do_not_claim_no_information(self):
        for status, state in [('failed', 'resource_failed'), ('empty', 'resource_pending')]:
            n = article('扫码进群。', images=[{'url': 'https://example.edu/qr.png', 'context': '交流群二维码'}],
                        resources=[{'url': 'https://example.edu/qr.png', 'status': status, 'chunks': [], 'error': 'decode_failed'}])
            hints = resource_hints(n)
            self.assertEqual(hints[0]['state'], state)
            self.assertIn('groups', hints[0]['fieldKeys'])
            self.assertEqual(hints[0]['error'], 'decode_failed')


if __name__ == '__main__':
    unittest.main()
