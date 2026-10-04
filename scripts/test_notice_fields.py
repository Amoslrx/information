import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from notice_fields import rules, safe_deadline, validate_model, validate_shape, check_evidence, all_facts
from extract_notice_fields import with_model


def article(body, **kwargs):
    return {'url': 'https://example.edu/notice/1', 'title': '关于第十三届物理竞赛的通知',
            'date': '2026-09-15', 'body': body, 'status': 'success', 'contentHash': 'hash-a', **kwargs}


class FieldTests(unittest.TestCase):
    def test_types_and_time(self):
        rec = article('报名开始：2026年9月16日9:30；校内报名截止：2026年9月20日18点；'
                      '官方报名截止：2026年9月22日24点，作品提交截止：2026年11月4日18点，决赛：2026年11月20日-11月22日。')
        fields = rules(rec)
        types = [e['kind'] for e in fields['timeline']]
        self.assertEqual(types[:5], ['registration_start', 'campus_deadline', 'official_deadline', 'submission', 'competition'])
        self.assertEqual(fields['timeline'][0]['time'], '09:30')
        self.assertEqual(fields['timeline'][2]['time'], '24:00')
        self.assertEqual(fields['timeline'][4]['endDate'], '2026-11-22')
        self.assertIsNone(safe_deadline(fields))  # Multiple distinct registration deadlines.

    def test_submission_and_competition_are_never_registration(self):
        for body in ('作品提交截止：2026年11月25日。', '比赛日期：2026年11月25日。',
                     '报名后于2026年11月25日前提交作品。', '报名选手参加2026年11月25日的决赛。'):
            with self.subTest(body=body):
                self.assertIsNone(safe_deadline(rules(article(body))))

    def test_explicit_registration_deadline(self):
        event = safe_deadline(rules(article('报名截止：2026年11月25日下午3点30分。')))
        self.assertEqual(event['value'], '2026-11-25')
        self.assertEqual(event['time'], '15:30')

    def test_missing_year_and_cross_year(self):
        fields = rules(article('报名截止：1月5日。', date='2026-12-10'))
        event = fields['timeline'][0]
        self.assertIn('missing_year', event['flags'])
        self.assertIn('possible_cross_year', event['flags'])
        self.assertIsNone(safe_deadline(fields))
        fields = rules(article('报名时间：2026年12月25日至1月5日。', date='2026-12-10'))
        self.assertEqual(fields['timeline'][1]['value'], '2027-01-05')
        self.assertIn('cross_year', fields['timeline'][1]['flags'])

    def test_invalid_calendar_and_clock(self):
        for text, flag in [('报名截止2026年2月30日。', 'invalid_date'), ('报名截止2026年11月25日25:61。', 'invalid_time')]:
            fields = rules(article(text, date='2026-01-01'))
            self.assertIn(flag, fields['timeline'][0]['flags'])
            self.assertIsNone(safe_deadline(fields))

    def test_postponement_and_conflicts(self):
        fields = rules(article('报名截止：2026年11月20日。报名截止延期至2026年11月25日。'))
        self.assertIsNone(safe_deadline(fields))
        self.assertTrue(fields['timeline'][0]['superseded'])
        self.assertTrue(all('conflict' in e['flags'] for e in fields['timeline']))
        fields = rules(article('报名截止2026年11月20日，现延期至2026年11月25日。'))
        self.assertEqual(fields['timeline'][1]['kind'], 'registration_deadline')
        self.assertIn('conflict', fields['timeline'][1]['flags'])
        self.assertTrue(fields['timeline'][0]['superseded'])
        self.assertFalse(fields['timeline'][1]['superseded'])

    def test_numeric_counts_not_dates(self):
        fields = rules(article('选出2-4支队伍。2026.10-11月准备作品。'))
        self.assertEqual(len(fields['timeline']), 1)
        self.assertIsNone(fields['timeline'][0]['value'])
        self.assertIn('month_precision', fields['timeline'][0]['flags'])

    def test_month_only_cross_year_preserved(self):
        event = rules(article('比赛安排：2026年12月-2027年2月。'))['timeline'][0]
        self.assertIsNone(event['value'])
        self.assertIn('cross_year', event['flags'])

    def test_range_year_follows_explicit_start(self):
        fields = rules(article('报名时间：2027年1月1日至1月5日。'))
        self.assertEqual(fields['timeline'][1]['value'], '2027-01-05')

    def test_joint_names_do_not_guess_phone_owner(self):
        fields = rules(article('联系人：张三、李四 电话：13800138000'))
        self.assertEqual([p['name']['value'] for p in fields['contacts'] if p['name']], ['张三', '李四'])
        self.assertTrue(all(not p['phones'] for p in fields['contacts'] if p['name']))
        self.assertEqual(fields['contacts'][-1]['phones'][0]['verification'], 'needs_review')

    def test_table_contact_rows(self):
        fields = rules(article('张三 13800138000 zhang@example.com\n李四 029-82661234 li@example.com'))
        self.assertEqual(fields['contacts'][0]['name']['value'], '张三')
        self.assertEqual(fields['contacts'][1]['name']['value'], '李四')
        self.assertEqual(fields['contacts'][1]['phones'][0]['value'], '029-82661234')

    def test_multiple_contacts_and_qq(self):
        fields = rules(article('联系人：张三 电话：13800138000 邮箱：zhang@example.com；'
                               '联系人：李四 电话：13900139000 邮箱：li@example.com\n联系QQ：12345678\nQQ交流群：87654321'))
        self.assertEqual(len(fields['contacts']), 2)
        a, b = fields['contacts']
        self.assertEqual(a['name']['value'], '张三')
        self.assertEqual(a['phones'][0]['value'], '13800138000')
        self.assertEqual(a['emails'][0]['value'], 'zhang@example.com')
        self.assertEqual(b['name']['value'], '李四')
        self.assertEqual(b['phones'][0]['value'], '13900139000')
        self.assertEqual(b['qq'][0]['value'], '12345678')
        self.assertEqual(fields['groups'][0]['number']['value'], '87654321')

    def test_tracks_keep_groups_separate(self):
        fields = rules(article('一、创新赛道\n联系人：张三 电话：13800138000\nQQ群：12345678\n'
                               '二、创业赛道\n联系人：李四 电话：13900139000\nQQ群：87654321'))
        self.assertEqual(len(fields['tracks']), 2)
        self.assertEqual(fields['groups'][0]['trackId'], fields['contacts'][0]['trackId'])
        self.assertNotEqual(fields['groups'][0]['trackId'], fields['groups'][1]['trackId'])

    def test_explicit_single_title_track(self):
        fields = rules(article('联系人：陈伟老师 邮箱：chw@example.com\nQQ群：12345678',
                               title='关于嵌入式竞赛FPGA创新设计赛道报名的通知'))
        self.assertEqual(fields['tracks'][0]['value'], 'FPGA创新设计赛道')
        self.assertEqual(fields['contacts'][0]['trackId'], fields['tracks'][0]['id'])
        self.assertEqual(fields['groups'][0]['trackId'], fields['tracks'][0]['id'])

    def test_links_materials_and_images(self):
        rec = article('一、创新赛道\n报名网址：www.example.com/register\n需提交报名表和身份证证明。\n创新赛道QQ群二维码',
                      images=[{'url': 'https://example.edu/qr.png', 'context': '创新赛道QQ群二维码', 'alt': ''}])
        fields = rules(rec)
        self.assertEqual(fields['registrationLinks'][0]['value'], 'https://www.example.com/register')
        self.assertTrue(fields['requiredMaterials'])
        self.assertEqual(fields['groups'][0]['trackId'], fields['tracks'][0]['id'])
        self.assertIsNone(fields['groups'][0]['number'])
        self.assertEqual(fields['groups'][0]['images'][0]['verification'], 'needs_review')

    def test_website_not_automatically_entry(self):
        fields = rules(article('竞赛网站：https://example.com。'))
        self.assertEqual(fields['registrationLinks'], [])

    def test_evidence_and_missing_values(self):
        rec = article('报名截止2026年11月25日。')
        fields = rules(rec)
        validate_shape(fields)
        for field in all_facts(fields):
            check_evidence(field, rec)
        self.assertEqual(fields['contacts'], [])
        self.assertEqual(fields['audiences'], [])


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.record = article('联系人：张三 电话：13800138000；联系人：李四 电话：13900139000。'
                              '报名截止2026年11月25日。作品提交2026年11月30日。')
        self.base = rules(self.record)

    def test_bad_quote_rejected(self):
        candidate = copy.deepcopy(self.base)
        candidate['timeline'][0]['raw'] = '凭空发明的报名截止日期'
        with self.assertRaises(ValueError):
            validate_model(candidate, self.record)

    def test_unknown_properties_and_types_rejected(self):
        for mutate in [lambda c: c.update(extra='guess'), lambda c: c['contacts'][0].update(phones='13900139000'),
                       lambda c: c['timeline'][0].update(time=123), lambda c: c['timeline'][0].update(verification='verified'),
                       lambda c: c.update(schemaVersion=True)]:
            candidate = copy.deepcopy(self.base)
            mutate(candidate)
            with self.assertRaises(ValueError):
                validate_model(candidate, self.record)

    def test_wrong_date_type_not_promoted(self):
        candidate = copy.deepcopy(self.base)
        candidate['timeline'][1]['kind'] = 'registration_deadline'
        result = validate_model(candidate, self.record)
        self.assertEqual(result['timeline'][1]['verification'], 'needs_review')

    def test_swapped_contacts_not_promoted(self):
        candidate = copy.deepcopy(self.base)
        candidate['contacts'][0]['phones'], candidate['contacts'][1]['phones'] = candidate['contacts'][1]['phones'], candidate['contacts'][0]['phones']
        result = validate_model(candidate, self.record)
        self.assertEqual(result['contacts'][0]['phones'][0]['verification'], 'needs_review')

    def test_cache_and_hash_invalidation(self):
        calls = []
        def run(*args, **kwargs):
            calls.append(args)
            return SimpleNamespace(stdout=json.dumps(self.base))
        with tempfile.TemporaryDirectory() as tmp:
            first = with_model(self.record, self.base, ['adapter'], tmp, runner=run)
            second = with_model(self.record, self.base, ['adapter'], tmp, runner=run)
            self.assertEqual(first['model']['status'], 'accepted')
            self.assertEqual(second['model']['status'], 'cached')
            self.assertEqual(len(calls), 1)
            changed = {**self.record, 'contentHash': 'hash-b'}
            with_model(changed, rules(changed), ['adapter'], tmp, runner=run)
            self.assertEqual(len(calls), 2)

    def test_invalid_model_and_timeout_fallback(self):
        for runner in [lambda *a, **k: SimpleNamespace(stdout='not json'),
                       lambda *a, **k: SimpleNamespace(stdout='{}'),
                       lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired('adapter', 90))]:
            with tempfile.TemporaryDirectory() as tmp:
                result = with_model(self.record, self.base, ['adapter'], tmp, runner=runner)
                self.assertEqual(result['timeline'], self.base['timeline'])
                self.assertEqual(result['contacts'], self.base['contacts'])
                self.assertEqual(result['model']['status'], 'failed')

    def test_real_subprocess_contract(self):
        command = [sys.executable, '-c', 'import json,sys; r=json.load(sys.stdin); print(json.dumps(r["ruleResult"]))']
        with tempfile.TemporaryDirectory() as tmp:
            result = with_model(self.record, self.base, command, tmp)
            self.assertEqual(result['model']['status'], 'accepted')
            self.assertEqual(result['contacts'], self.base['contacts'])

    def test_unsupported_model_date_cannot_change_rule_deadline(self):
        candidate = copy.deepcopy(self.base)
        candidate['timeline'][1]['kind'] = 'registration_deadline'
        candidate['timeline'][1]['method'] = 'model'
        with tempfile.TemporaryDirectory() as tmp:
            result = with_model(self.record, self.base, ['adapter'], tmp,
                                runner=lambda *a, **k: SimpleNamespace(stdout=json.dumps(candidate)))
            self.assertEqual(safe_deadline(result)['value'], safe_deadline(self.base)['value'])


if __name__ == '__main__':
    unittest.main()
