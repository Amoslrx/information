import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from classify_competition_notice import classify
from notice_fields import rules
from extract_notice_fields import with_model
from model_http_adapter import model_request, model_response


def article(title, body='报名截止时间为2026年11月1日。'):
    return {'url': 'https://example.org/1', 'title': title, 'body': body, 'status': 'success', 'contentHash': 'test'}


class ClassificationTests(unittest.TestCase):
    def test_recruitment(self):
        r = classify(article('2027年电赛招募通知'))
        self.assertEqual(r['state'], 'target')
        self.assertEqual(r['primaryType'], 'recruitment')
        self.assertTrue(r['eligibleForSignup'])

    def test_robot_distinction(self):
        for name in ['RoboMaster', 'ROBOCON', 'RoboCup']:
            r = classify(article(name + '招募通知'))
            self.assertEqual(len(r['matches']), 1)
            self.assertEqual(r['state'], 'target')

    def test_award_not_registration(self):
        for title in ['电赛获奖喜报及报名回顾', '电赛获奖名单延期公布']:
            self.assertFalse(classify(article(title))['eligibleForSignup'])

    def test_ambiguous_and_irrelevant(self):
        self.assertEqual(classify(article('挑战杯报名通知'))['state'], 'review')
        self.assertEqual(classify(article('停水通知', '今日停水。'))['state'], 'excluded')
        self.assertEqual(classify(article('电赛及数学建模国赛报名'))['state'], 'review')

    def test_c_track(self):
        self.assertEqual(classify(article('蓝桥杯报名'))['state'], 'review')
        self.assertEqual(classify(article('蓝桥杯智能装备数字化建模大赛报名'))['state'], 'target')

    def test_failed_body_not_excluded(self):
        self.assertEqual(classify({'title': '', 'status': 'failed'})['state'], 'review')

    def test_model_failure_retains_rules(self):
        r = article('电赛报名通知')
        baseline = rules(r)
        def broken(*args, **kwargs):
            raise subprocess.TimeoutExpired('adapter', 90)
        with tempfile.TemporaryDirectory() as cache:
            out = with_model(r, baseline, ['adapter'], cache, runner=broken)
        self.assertEqual(out['timeline'], baseline['timeline'])
        self.assertEqual(out['model']['status'], 'failed')

    def test_chat_contract(self):
        with patch.dict(os.environ, {'NOTICE_MODEL_PROTOCOL': 'chat', 'NOTICE_MODEL_NAME': 'test-model'}):
            req = model_request({'instructions': 'extract', 'article': {}})
            self.assertEqual(req['model'], 'test-model')
            self.assertEqual(model_response({'choices': [{'message': {'content': '{"timeline": []}'}}]}), {'timeline': []})
            with self.assertRaises(ValueError):
                model_response({'choices': [{'message': {'content': 'not json'}}]})


if __name__ == '__main__':
    unittest.main()
