#coding: utf-8


from __future__ import print_function

import argparse
from collections import defaultdict
from contextlib import closing
import datetime
import io
import logging
import os
import random
import shutil
import string
import sys
import threading
import tempfile
import time
import unittest


if sys.version_info.major == 2:
    import ConfigParser as configparser
    from BaseHTTPServer import HTTPServer as Server
    from SimpleHTTPServer import SimpleHTTPRequestHandler as Handler
elif sys.version_info.major == 3:
    import configparser
    from http.server import HTTPServer as Server
    from http.server import SimpleHTTPRequestHandler as Handler
else:
    raise RuntimeError("Unknown python version: {}".format(sys.version_info))

class NoLogHandler(Handler):
    def log_message(self, *a, **k):
        pass

FAKE_CONFIGS = (
    ("""[DEFAULT]
foo = foo
bar =
baz = 2
""", {'DEFAULT': {'foo':'foo','bar':'', 'baz':'2'}}),
    ("""[SPAM]
spam = yes
eggs = no

[EGGS]
eggs = yes
spam = no
""", {'SPAM':{'spam':'yes', 'eggs':'no'}, 'EGGS':{'spam':'no', 'eggs':'yes'}})
)


FAKE_REC_OK = ( # pairs of (fake_rec, entries)
    (b'''url1
path1

url11
path11

url111
path111

url1111
path1111

''', 4),
    (b'''
url1
path1


url1x
path1x



url1xx
path1xx

url1xxx
path1xxx
''', 4),
    (b'a\nb\n\nc\nd\n\ne\nf', 3))

FAKE_REC_FAIL = ( # triplets of (fake_rec, entries, errors)
    (b'''1
2
3

1
2

1
2
3
4

1
2

1
2
''', 5, 2),
    (b'''
1

2

3

4

5''', 5, 5),
    (b'1\n2\n\n3\n4\n5\n', 2, 1))


class ServerControl:
    def __init__(self, server_cls, host, port, handler):
        self.server = server_cls((host, port), handler)
        self._host = host
        self._port = port
        self._running = False
    @property
    def host (self):
        return self._host
    @property
    def port (self):
        return self._port
    @property
    def running (self):
        return self._running
    @property
    def timeout (self):
        return self.server.timeout
    @timeout.setter
    def timeout (self, n):
        self.server.timeout = n        
    def stop(self):
        self.server.shutdown()
        self._running = False
    def start(self):
        self._running = True
        self.server.serve_forever()


def random_string(n):
    s = string.ascii_letters
    return ''.join(random.choice(s) for _ in range(n))


class TestNumbersAndDate(unittest.TestCase):
    def testPositiveInteger (self):
        must_fail = map(str, range(-10, 0, 1))
        must_pass = map(str, range(0, 1000))
        for arg in must_fail:
            self.assertRaises(argparse.ArgumentTypeError, 
                              feedretrieve.positive_integer,
                              arg)
        for arg in must_pass:
            res, expected = feedretrieve.positive_integer(arg), int(arg)
            self.assertEqual(res, expected, "{} != {}".format(res, expected))

    def testTime (self):
        r = random.randint
        year, month, day = r(1,2022), r(1,12), r(1,25) 
        date = datetime.datetime(year, month, day)
        for _ in range(100):
            delta = datetime.timedelta(days=r(-10000,1000))
            struct = (date - delta).timetuple()
            ret = feedretrieve.time_to_struct(
                feedretrieve.struct_to_time(struct))
            # NOTE: struct_time[:-1] for avoid f***ing tm_isdst
            self.assertEqual(struct[:-1], ret[:-1])


class TestHeaders(unittest.TestCase):

    def random_headers(self):
        headers = {}
        for i in range(50):
            l1,l2 = random.randint(5,20), random.randint(5,20)
            headers[random_string(l1)] = random_string(l2)
        return headers

    def testAddHeaders(self):
        for _ in range(50):
            headers = self.random_headers()
            opener = feedretrieve.urlreq.build_opener()
            opener.addheaders = []
            feedretrieve.add_headers(opener, headers)
            self.assertEqual(list(sorted(headers.items())),
                             list(sorted(opener.addheaders)))

    def _testSetHeaders(self, server):
        self.maxDiff = None
        t = threading.Thread(target=server.start)
        t.start()
        with closing(feedretrieve.urlreq.urlopen(
            'http://{}:{}'.format(server.host,server.port))):
            for _ in range(50):
                headers = self.random_headers()
                feedretrieve.set_headers(headers)
                self.assertEqual(
                    list(sorted(feedretrieve.urlreq._opener.addheaders)),
                    list(sorted(headers.items())))
        server.stop()
        t.join()
    def testSetHeaders(self):
        host = '127.0.0.1'
        port = 9999
        server = ServerControl(Server, host, port, handler=NoLogHandler)
        try:
            self._testSetHeaders(server)
        finally:
            if server.running:
                server.stop()


class TestRecovery(unittest.TestCase):

    def testWriteRecoveryEntries(self):
        r = random.randint
        for _ in range(50):
            data = [(random_string(r(2,10)), random_string(r(2,10)))
                    for i in range(r(1,20))]
            with tempfile.NamedTemporaryFile(delete=False) as out:
                pass
            for url, destination in data:
                feedretrieve.write_recovery_entry(out.name, url, destination)
            data_back, errors = feedretrieve.read_recovery(out.name)
            self.assertFalse(errors)
            self.assertEqual(len(data), len(data_back))
            for p1, p2 in zip(data, data_back):
                self.assertEqual(p1, p2)
            os.remove(out.name)

    def _testReadRecoveryEntries(self):
        for s, n in FAKE_REC_OK:
            with tempfile.NamedTemporaryFile(delete=False) as out:
                out.write(s)
            data, errors = feedretrieve.read_recovery(out.name)
            self.assertFalse(errors)
            self.assertEqual(len(data), n)
            os.remove(out.name)
        for s, n, e in FAKE_REC_FAIL:
            with tempfile.NamedTemporaryFile(delete=False) as out:
                out.write(s)
            data, errors = feedretrieve.read_recovery(out.name)
            self.assertTrue(errors)
            self.assertEqual(len(errors), e)
            self.assertEqual(len(errors) + len(data), n)
            os.remove(out.name)
    def testReadRecoveryEntries(self):
        logging.disable(logging.WARNING)
        try:
            self._testReadRecoveryEntries()
        finally:
            logging.getLogger().setLevel(logging.WARNING)


class TestPlugin(unittest.TestCase):
    def testImportPlugin(self):
        body = '''def {0}(): return "{0}"'''
        for i in range(20):
            tmpdir = tempfile.mkdtemp()
            func_name = random_string(random.randint(3,11))
            with tempfile.NamedTemporaryFile(
                dir=tmpdir, delete=False, suffix='.py') as out:
                out.write(body.format(func_name).encode('utf-8'))
            sys_path = sys.path
            func = feedretrieve.get_format_func(
                tmpdir,
                os.path.splitext(os.path.basename(out.name))[0],
                func_name)
            sys.path = sys_path
            self.assertEqual(func(), func_name)
            shutil.rmtree(tmpdir)


class TestConfig(unittest.TestCase):

    def testReadConfig(self):
        for config, dicts in FAKE_CONFIGS:
            with tempfile.NamedTemporaryFile(delete=False) as out:
                out.write(config.encode('utf-8'))
            cfg = feedretrieve.read_config(out.name)
            for section, values in dicts.items():
                for k, v in values.items():
                    self.assertEqual(cfg.get(section, k), v)
            os.remove(out.name)

    def testWriteConfig(self):
        r = random.randint
        for _ in range(20):
            config_data = defaultdict(dict)
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as out:
                cfg = configparser.ConfigParser()
                for _ in range(r(1,10)):
                    section = random_string(r(2,20))
                    cfg.add_section(section)
                    for _ in range(r(2,7)):
                        key = random_string(r(2,15))
                        val = random_string(r(2,15))
                        config_data[section][key] = val
                        cfg.set(section, key, 'NotSet')
                cfg.write(out)
            for section, pairs in config_data.items():
                feedretrieve.write_config(out.name, section, pairs)
            cfg = feedretrieve.read_config(out.name)
            for section, pairs in config_data.items():
                for key, value in pairs.items():
                    self.assertEqual(cfg.get(section, key), value)
            os.remove(out.name)



if __name__ == '__main__':
    try:
        import feedretrieve
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
        import feedretrieve
    unittest.main()
