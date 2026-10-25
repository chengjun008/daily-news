import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import news_digest as n


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 25, 9, tzinfo=n.CST)

    def feed(self, date='Sun, 25 Oct 2026 00:00:00 GMT', link='https://example.com/news'):
        return f'''<rss><channel><item><title>测试新闻</title><link>{link}</link>
        <pubDate>{date}</pubDate><description>&lt;p&gt;第一句。第二句。第三句。&lt;/p&gt;</description>
        </item></channel></rss>'''.encode()

    def test_summary_and_timezone(self):
        rows = n.parse_feed(self.feed(), '国内', '测试', self.now)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['summary'], '第一句。第二句。…')

    def test_stale_future_invalid_date_excluded(self):
        for date in ['Fri, 23 Oct 2026 00:00:00 GMT', 'Mon, 26 Oct 2026 00:00:00 GMT', 'invalid']:
            self.assertEqual(n.parse_feed(self.feed(date), '国内', '测试', self.now), [])

    def test_unsafe_link_excluded(self):
        self.assertEqual(n.parse_feed(self.feed(link='javascript:alert(1)'), '国内', '测试', self.now), [])

    def test_deduplicate_and_limit(self):
        row = n.parse_feed(self.feed(), '国内', '测试', self.now)[0]
        self.assertEqual(len(n.select([row, dict(row)])), 1)
        self.assertEqual(len(n.select([dict(row, title=str(i)) for i in range(10)])), 6)

    def test_partial_failure_visible(self):
        body = n.render([], ['国际源暂不可用'], self.now)
        self.assertIn('国际源暂不可用', body)
        self.assertIn('暂无可核实', body)

    def test_submit_failure_does_not_mark_sent(self):
        row = n.parse_feed(self.feed(), '国内', '测试', self.now)[0]
        with tempfile.TemporaryDirectory() as tmp, patch.object(n, 'DATA', Path(tmp)), \
             patch.object(n, 'collect', return_value=([row], [])), \
             patch.object(n, 'get_key', return_value='SCTtest'), \
             patch.object(n, 'send', side_effect=RuntimeError('失败')):
            with self.assertRaises(RuntimeError):
                n.run()
            self.assertFalse((Path(tmp) / 'state.json').exists())
            self.assertFalse((Path(tmp) / 'run.lock').exists())

    def test_once_daily_and_preview_does_not_send(self):
        row = n.parse_feed(self.feed(), '国内', '测试', self.now)[0]
        with tempfile.TemporaryDirectory() as tmp, patch.object(n, 'DATA', Path(tmp)), \
             patch.object(n, 'collect', return_value=([row], [])), \
             patch.object(n, 'get_key', return_value='SCTtest'), \
             patch.object(n, 'send', return_value={'code': 0}) as send:
            n.run(preview=True)
            send.assert_not_called()
            n.run()
            n.run()
            self.assertEqual(send.call_count, 1)

    def test_empty_sources_never_send(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(n, 'DATA', Path(tmp)), \
             patch.object(n, 'collect', return_value=([], ['失败'])), \
             patch.object(n, 'get_key', return_value='SCTtest'), patch.object(n, 'send') as send:
            with self.assertRaises(RuntimeError):
                n.run()
            send.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'DPAPI 仅在 Windows 桌面版使用')
    def test_dpapi_round_trip(self):
        encoded = n.protect(b'SCTdummykey')
        self.assertNotIn(b'SCTdummykey', encoded)
        self.assertEqual(n.protect(encoded, decrypt=True), b'SCTdummykey')

    def test_environment_secret_on_linux_without_dpapi(self):
        with patch.dict(os.environ, {'SERVERCHAN_SENDKEY': 'SCTtest123'}), \
             patch.object(n, 'protect', side_effect=AssertionError('不应调用本机加密')):
            self.assertEqual(n.get_key(), 'SCTtest123')

    def test_missing_key_fails_before_news_fetch(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(n, 'DATA', Path(tmp)), \
             patch.dict(os.environ, {'SERVERCHAN_SENDKEY': ''}), patch.object(n, 'collect') as collect:
            with self.assertRaisesRegex(ValueError, 'SERVERCHAN_SENDKEY'):
                n.run()
            collect.assert_not_called()

    def test_cached_success_skips_send_and_fetch(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(n, 'DATA', Path(tmp)), \
             patch.object(n, 'collect') as collect, patch.object(n, 'send') as send:
            today = datetime.now(n.CST).date().isoformat()
            (Path(tmp) / 'state.json').write_text(json.dumps({'date': today, 'status': 'accepted'}), encoding='utf-8')
            self.assertIn('无需重复发送', n.run())
            collect.assert_not_called()
            send.assert_not_called()

    def test_network_error_cannot_print_secret(self):
        from urllib.error import URLError
        import io
        secret = 'SCTprivateTEST'
        with tempfile.TemporaryDirectory() as tmp, patch.object(n, 'DATA', Path(tmp)), \
             patch.object(n, 'run', side_effect=URLError('https://example.com/' + secret)), \
             patch('sys.argv', ['news_digest.py', '--send']), patch('sys.stderr', new_callable=io.StringIO) as output:
            with self.assertRaises(SystemExit):
                n.main()
            self.assertNotIn(secret, output.getvalue())
            self.assertNotIn(secret, (Path(tmp) / 'errors.log').read_text('utf-8'))


if __name__ == '__main__':
    unittest.main()
