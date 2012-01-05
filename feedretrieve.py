#!/usr/bin/env python3
#coding: utf-8

from __future__ import print_function


PROG_INFO = """
# feedretrieve.py - Retrieve feeds. (version 0.4.3 - 2012-01-05)

# Copyright (C) 2011 Marco Chieppa (aka crap0101)

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not see <http://www.gnu.org/licenses/>   
"""

import os
import os.path as osp
import sys
import re
import time
import calendar
import operator as op
import argparse
import logging
import logging.handlers
if sys.version_info[0] == 2:
    import ConfigParser as configparser
    import urllib as urlreq
    import urllib2 as urlerr
elif sys.version_info[0] == 3:
    import configparser
    import urllib.request as urlreq
    import urllib.error as urlerr
else:
    print("Unknow Python version: %s" % (sys.version_info,))
    sys.exit(1)
# non stdl:
import feedparser


# strings substitutions, regex pattern : sub
if sys.version_info[0] == 2:
    RE_SUBS = {unicode('[ ,/|:"‘’“”«″–′\']', 'utf-8'): '-',
               unicode('[()]', 'utf-8'): '_', }
else:
    RE_SUBS = {'[ ,/|:"‘’“”«″–′\']': '-',
               '[()]': '_', }


# default paths & constants
CONFIG_FILE = osp.join(osp.expanduser('~'), '.feedretrieve.cfg')
LOG_FILE = osp.join(osp.expanduser('~'), '.feedretrieve.log')
# plug-in directory, actually only for title formatting
PLUG_DIR = osp.join(osp.expanduser('~'), '.feedretrieve_plugins')


FEED_URL = 'feed_url'
SAVE_PATH = 'savepath'
LAST_UPDATE= 'last_update_time'
DELAY = 'delay'
PREFIX = 'prefix'
SUFFIX = 'suffix'
EXT = 'ext'

TIME_KEYS = frozenset(('updated_parsed', 'date_parsed', 'published_parsed'))


CONFIG_FILE_EXAMPLE = """
#-------------------------------------------------#
# example of config file.
#Put it in your $HOME/.feedretrieve.cfg
# or select the right path from the command line.

[DEFAULT]
delay = 3600
prefix = 
suffix = 
ext = html

[uaar]
savepath = /home/crap0101/feeds/uaarnews/
feed_url = http://feeds.feedburner.com/uaar-ultimissime
last_update_time = 0 # initial value

[comidad]
savepath = /home/crap0101/feeds/comidad/
feed_url = http://www.comidad.org/dblog/feedrss.asp
last_update_time = 1301529687  # after some time
prefix = xxx_
"""


#default function for filename's string substitutions
def _format_title(entry, cfg, section):
    """
    Returns the formatted title.
    *entry* if a FeedParserDict object,
    *cfg* a configparser.ConfigParser instance,
    *section* is the section relative to *entry*.
    """
    title = entry.title
    for pattern, sub in RE_SUBS.items():
        title = re.sub(pattern, sub, title, re.U)
    date = entry.updated_parsed
    prefix=cfg.get(section, PREFIX)
    suffix=cfg.get(section, SUFFIX)
    ext=cfg.get(section, EXT)
    return ("%s%s%s_%d%02d%02d.%s" %
            (prefix, title, suffix, date.tm_year,
             date.tm_mon, date.tm_mday, ext))


def check_time_attr (entry):
    if set(entry.keys()) & TIME_KEYS:
        return True
    logging.info("Can't save %s (no date fields)." % entry.url)
    return False


def get_arg_parser():
    """Command line parser."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=PROG_INFO,
        epilog=CONFIG_FILE_EXAMPLE)
    parser.add_argument('-c', '--config-file', metavar='FILEPATH',
                        dest='cfg', default=CONFIG_FILE,
                        help='path to the the config file to read from.')
    parser.add_argument('-f', '--format-func', dest='ffunc',
                        metavar='module.func',
                        help=("Use the *module*'s function *func* from"
                              " the plugin dir (%s) for title's formatting."
                              " function signature must be: %s" %
                              (PLUG_DIR, _format_title.__doc__)))
    parser.add_argument('-l', '--log-file', metavar='FILEPATH',
                        dest='log', default=LOG_FILE,
                        help='path to the the log file to write on.')
    parser.add_argument('-r', '--run-forever', dest='nonstop',
                        action='store_true', help='loop forever.')
    return parser


def get_format_func (path, module, func):
    sys.path.insert(0, path)
    m = __import__(module)
    return getattr(m, func)


def get_info(feed_url):
    """Returns the entries from the url *feed_url*."""
    return feedparser.parse(feed_url).entries


def get_time_attr (entry):
    for k in TIME_KEYS:
        if k in entry:
            return entry[k]


def is_old (entry, last_time):
    for k in TIME_KEYS:
        if k in entry:
            return getattr(entry,k) <= last_time


def read_config(file):
    """Returns a ConfigParser object from *file*."""
    config = configparser.ConfigParser()
    config.read(file)
    return config


def retrieve_news(entries, last_struct_time=time.gmtime(0)):
    """Yelds new feeds entry."""
    entries = filter(check_time_attr, entries)
    for e in sorted(entries, key=get_time_attr, reverse=True):
        if not is_old(e, last_struct_time):
            yield e


def run(config_file, format_title_func):
    """Start retrieving feeds rely upon the infos on *config_file*."""
    cfg = read_config(config_file)
    for section in cfg.sections():
        info = get_info(cfg.get(section, FEED_URL))
        if not info:
            continue
        entries = list(
            retrieve_news(info,
                          time_to_struct(float(cfg.get(section,LAST_UPDATE)))))
        if entries:
            logging.debug('start retrive pages from {0}'.format(section))
            for e in entries:
                save(e.links[0].href, cfg.get(section, SAVE_PATH),
                     format_title_func(e, cfg, section))
            write_config(config_file, section,
                         [(LAST_UPDATE,
                           str(struct_to_time(
                               max(e.updated_parsed for e in entries))))])


def save(url, basepath, title):
    """
    Save the content downloaded from *url* in the path *basepath*
    in a file named *title*.
    """
    if osp.exists(osp.join(basepath, title)):
        logging.info('* alredy saved: {0}'.format(
            osp.join(basepath.encode('utf-8'), title.encode('utf-8'))))
        return
    with open(osp.join(basepath, title), 'wb') as news:
        try:
            logging.debug('\tsaving {0}'.format(title.encode('utf-8')))
            data = urlreq.urlopen(url)
            news.write(data.read())
            logging.debug('\tdone.')
        except (IOError, urlerr.URLError, urlerr.HTTPError) as err:
            logging.warning('* {0}: {1}'.format(err, url))


def struct_to_time(struct_time):
    """Convert *struct_time* to calendar.timegm."""
    return calendar.timegm(struct_time)


def time_to_struct(seconds):
    """Convert *seconds* to time.gmtime."""
    return time.gmtime(seconds)


def write_config(file, section, pairs):
    """
    Write new *section* configuration key-value from the
    sequence *pairs* on *file*.
    """
    config = configparser.ConfigParser()
    config.read(file)
    with open(file, 'w') as config_file:
        for key, value in dict(pairs).items():
            config.set(section, key, str(value))
        config.write(config_file)



# MAIN #
def main(config_file, log_file, always_run, format_func):
    logging.basicConfig(format='%(levelname)s:%(message)s',
                        level=logging.DEBUG)
    logfile = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5000, backupCount=3)
    logfile.setFormatter(logging.Formatter('%(levelname)s:%(message)s'))
    logging.getLogger().addHandler(logfile)
    if always_run:
        while True:
            cfg = read_config(config_file)
            logging.info('start retrieving feeds {0}'.format(time.ctime()))
            run(config_file, format_func)
            delay = int(cfg['DEFAULT'].get(DELAY, 300))
            logging.info('sleep {0} (for {1} sec)'.format(time.ctime(), delay))
            time.sleep(delay)
    else:
        run(config_file, format_func)

if __name__ == '__main__':
    parser = get_arg_parser()
    args = parser.parse_args()
    if not os.path.exists(args.cfg):
        parser.error("Can't read from config file {0}".format(args.cfg))
    try:
        read_config(args.cfg)
    except configparser.Error as err:
        parser.error(str(err))
    if args.ffunc:
        module, func = args.ffunc.split('.')
        if not os.path.exists(os.path.join(PLUG_DIR, '%s.py' % module)):
            parser.error("Can't load plugin: {0}".format(args.ffunc))
        format_title = get_format_func(PLUG_DIR, module, func)
    else:
        format_title = _format_title
    main(args.cfg, args.log, args.nonstop, format_title)
