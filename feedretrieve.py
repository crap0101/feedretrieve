#!/usr/bin/env python3
#coding: utf-8

from __future__ import print_function


##############
# prog infos #
##############
_VERSION = '0.4.4'
_DATE = '2013-04-11'
_PROG_INFO = """
# feedretrieve.py - Retrieve feeds. (version {version} - {date})

# Copyright (C) 2011..2013 Marco Chieppa (aka crap0101)

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
""".format(version=_VERSION, date=_DATE)


import argparse
import atexit
import calendar
import itertools
import logging
import logging.handlers
import os
import re
import sys
import time
if sys.version_info.major == 2:
    import ConfigParser as configparser
    import urllib2 as urlreq
elif sys.version_info.major == 3:
    import configparser
    import urllib.request as urlreq
else:
    print("Unknow Python version: %s" % (sys.version_info,))
    sys.exit(1)
try:
    import importlib
    import_module = importlib.import_module
except:
    import_module = __import__

####################
# non stdl imports #
####################
import feedparser
try:
    # optional
    import magic
    def filetype (path, size=512):
        with open(path, 'rb') as f:
            return magic.from_buffer(f.read(size))
except ImportError:
    def filetype (path, size=512):
        return b'?'


#############################
# default paths & constants #
#############################
class Config:
    """Default configuration values.
    Fields contains other attributes, mostly used for
    accessing the configuration file's fields.
    """
    config_file = os.path.join(os.path.expanduser('~'), '.feedretrieve.cfg')
    log_file = os.path.join(os.path.expanduser('~'), '.feedretrieve.log')
    recovery_file = os.path.join(os.path.expanduser('~'), '.feedretrieve.failed')
    # plug-in directory, actually only for title formatting
    plugin_path = os.path.join(os.path.expanduser('~'), '.feedretrieve_plugins')
    user_agent = 'feedretrieve.py/{}'.format(_VERSION)
    delay = 0
    timeout = 0 # use default timeout
    # strings substitutions, regex pattern : sub #
    if sys.version_info.major == 2:
        re_subs = {unicode('[ ,/|:"‘’“”«″–′\']', 'utf-8'): '-',
                   unicode('[()]', 'utf-8'): '_', }
    else:
        re_subs = {'[ ,/|:"‘’“”«″–′\']': '-',
                   '[()]': '_', }
    class Fields:
        feed_url = 'feed_url'
        save_path = 'savepath'
        last_update = 'last_update_time'
        delay = 'delay'
        prefix = 'prefix'
        suffix = 'suffix'
        ext = 'ext'
        timeout = 'timeout'
        user_agent = 'user_agent'
        recovery_file = 'recovery_file'
        time_keys = ('updated_parsed', 'date_parsed', 'published_parsed')
        # entry key which will be added and used to compare date (got the values
        # of the first available keys of time_keys)
        compare_time = '__date'


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
timeout = 60
user_agent = {user_agent}
recovery_file = {rec_file}

[uaar]
savepath = /home/crap0101/feeds/uaarnews/
feed_url = http://feeds.feedburner.com/uaar-ultimissime
last_update_time = 0 # initial value

[comidad]
savepath = /home/crap0101/feeds/comidad/
feed_url = http://www.comidad.org/dblog/feedrss.asp
last_update_time = 1301529687  # after some time
prefix = xxx_

""".format(user_agent=Config.user_agent,
           rec_file=Config.recovery_file)

RECOVERY_FILE_EXAMPLE = """
#------------------------#
# recovery file example:
#------------------------#

url-1
destination-path-1

url-2
destination-path-2

"""

class SaveError (Exception):
    """Exception on saving"""
    pass

def positive_integer (arg):
    """Function for the -t/--timeout argument.
    Returns the converted arg or Raise
    argparse.ArgumentTypeError.
    """
    value = int(arg)
    if value < 0:
        raise argparse.ArgumentTypeError("Must be a positive integer")
    return value

#default function for filename's string formatting
def _format_title(entry, section_items):
    """
    entry => FeedParserDict object,
    section_items => mapping of key,value pairs from the
                     config file section for this entry
    Returns the formatted title.
    """
    title = entry.title
    for pattern, sub in Config.re_subs.items():
        title = re.sub(pattern, sub, title, re.U)
    date = entry.updated_parsed
    prefix = section_items[Config.Fields.prefix]
    suffix = section_items[Config.Fields.suffix]
    ext = section_items[Config.Fields.ext]
    return ("%s%s%s_%d%02d%02d.%s" %
            (prefix, title, suffix, date.tm_year,
             date.tm_mon, date.tm_mday, ext))

@atexit.register
def _atexit_log():
    """Log when exit"""
    logging.info('{} exit at {}'.format(sys.argv[0], time.ctime())) 

def add_headers(opener, headers):
    """Add headers to the default opener."""
    old = dict(opener.addheaders)
    old.update(headers)
    opener.addheaders = list(old.items())


def feeds_from_urls (urls, dest, timeout=None):
    for url in urls:
        logging.info('start retrive pages from {}'.format(url))
        entries = get_entries(url)
        if not entries:
            logging.info('no entries from {}'.format(url))
        for e in entries:
            logging.info('saving {title} [{type}]'.format(
                    title=e.title,
                    type=e.links[0].type))
            try:
                save(e.link, os.path.join(dest, e.title), timeout)
            except SaveError as err:
                pass


def get_arg_parser():
    """Command line parser."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=_PROG_INFO,
        epilog='\n'.join((CONFIG_FILE_EXAMPLE,RECOVERY_FILE_EXAMPLE)))
    parser.add_argument('-c', '--config-file',
                        dest='cfg', default=Config.config_file, metavar='FILEPATH',
                        help='''path to the the config file to read from,
                              default to %(default)s''')
    parser.add_argument('-d', '--destination',
                        dest='dest', default='', metavar='PATH',
                        help='''set %(metavar)s to the directory for the
                               files downloaded with the -u/-U options
                               (must exists, default to the current dir)''')
    parser.add_argument('-f', '--format-func',
                        dest='ffunc', metavar='module.func',
                        help='''"Use the module's function func from the plugin
                             dir (%s) for title's formatting. Arguments passed
                             to custom functions are a FeedParserDict object and
                             a mapping of key,value configuration items from
                             the relative section. The function must returns
                             the formatted title'''.format(Config.plugin_path))
    parser.add_argument('-l', '--log-file',
                        dest='log', metavar='FILEPATH', default=Config.log_file,
                        help='path to the the log file to write on')
    parser.add_argument('-L', '--loglevel',
                        dest='loglevel', metavar='LEVEL', default='INFO',
                        choices=('DEBUG', 'INFO', 'WARNING', 'ERROR'),
                        help='''set the log level. %(metavar)s can be one
                              of %(choices)s. Default: %(default)s''')
    parser.add_argument('-r', '--run-forever',
                        dest='nonstop', action='store_true',
                        help='run forever.')
    parser.add_argument('-R', '--recovery-file',
                        dest='recovery_file', default='',
                        help='''read and write recovery informations 
                             from/to this file (usually use the config file
                             value recovery_file, if present, otherwise
                             fall back to the default one: %s).
                             '''.format(Config.recovery_file))
    parser.add_argument('-s', '--sections',
                        dest='sections', default=(), nargs='+',
                        metavar='SECTIONS', help='''retrieve feeds only from
                        the given %(metavar)s from the config file''')
    parser.add_argument('-S', '--list-sections',
                        dest='list_sections', action='store_true',
                        help="list sections from the config file and exit")
    parser.add_argument('-t', '--timeout',
                        dest='timeout', default=0, type=positive_integer,
                        help='''set the timeout, must be a positive integer.
                             Zero means to use the default timeout''')
    parser.add_argument('--user-agent',
                        dest='user_agent', default='', metavar='UA',
                        help='''set the user agent to %(metavar)s, otherwise
                             read the user_agent value from the config file
                             (if present) or fall back to the default
                             one: {}'''.format(Config.user_agent))
    from_url = parser.add_mutually_exclusive_group()
    from_url.add_argument('-u', '--from-url',
                          dest='from_urls', nargs='+', metavar='URL',
                          help='''download feeds only for %(metavar)s (i.e.
                                 doesn't check the config file). See the
                                 -d/--destination option for the places
                                 to which save files. NOTE: with the -u/-U
                                 options are used, the given failed tries
                                 will not be written in the recovery file''')
    from_url.add_argument('-U', '--also-from-url',
                          dest='also_from_urls', nargs='+', metavar='URL',
                          help="like -u but read the config file too")
    return parser


def get_format_func (path, module, func):
    """Returns the attribute func from the module at path"""
    sys.path.insert(0, path)
    m = import_module(module)
    return getattr(m, func)


def get_entries(url):
    """Returns the entries from the given url."""
    return feedparser.parse(url).entries


def read_config(filepath):
    """Returns a ConfigParser object from filepath."""
    config = configparser.ConfigParser()
    config.read(filepath)
    return config


def read_recovery(recfile):
    """Returns a sequence of (url,path) pairs from recfile."""
    to_rec = []
    with open(recfile, 'rb') as f:
        for k, g in itertools.groupby(f, lambda x: not x.strip()):
            group = list(x.decode("utf-8") for x in g)
            if ''.join(group).strip():
                to_rec.append([x.strip() for x in group])
    return to_rec


def retrieve_news(entries, last_struct_time=time.gmtime(0)):
    """Yelds new feed entries."""
    def check_time_attr (entry):
        if set(entry.keys()) & set(Config.Fields.time_keys):
            return True
        logging.info("Can't save %s (no date fields)." % entry.link)
        return False
    def is_new (entry, last_time):
        return entry[Config.Fields.compare_time] > last_time
    entries = list(filter(check_time_attr, entries))
    for e in entries:
        for k in Config.Fields.time_keys:
            if k in e:
                e[Config.Fields.compare_time] = e[k]
                break
    for e in entries:
        if is_new(e, last_struct_time):
            yield e


def run(config_file, recfile, format_title_func, sections=(), timeout=None):
    """Retrieve feeds from each sections in config *config_file*.
    section => a sequence of strings, cfg section's names.
               If False, retrive all found sections.
    """
    cfg = read_config(config_file)
    if not sections:
        sections = list(cfg.sections())
    for section in set(cfg.sections()).intersection(sections):
        url = cfg.get(section, Config.Fields.feed_url)
        info = get_entries(url)
        if not info:
            logging.info('no entries from {}'.format(url))
            continue
        entries = list(
            retrieve_news(info,
                          time_to_struct(float(cfg.get(section,Config.Fields.last_update)))))
        if entries:
            logging.info('start retrive pages from {}'.format(section))
            for e in entries:
                logging.info('saving {title} [{type}]'.format(
                        title=e.title,
                        type=e.links[0].type))
                try:
                    save(e.link,
                         os.path.join(cfg.get(section, Config.Fields.save_path),
                                      format_title_func(e, dict(cfg.items(section)))),
                         timeout)
                except SaveError as err:
                    write_recovery_entry(recfile,
                                         e.link,
                                         os.path.join(cfg.get(section, Config.Fields.save_path),
                                                      format_title_func(e, dict(cfg.items(section)))))
            write_config(config_file, section,
                         [(Config.Fields.last_update,
                           str(struct_to_time(
                               max(e.updated_parsed for e in entries))))])

def struct_to_time(struct_time):
    """Convert *struct_time* to calendar.timegm."""
    return calendar.timegm(struct_time)


def save(url, dest, timeout=None):
    """
    Save the content downloaded from *url* in the path *basepath*
    in a file named *title*.
    optional timeout is the used as argument for urlopen (must be a
    positive integer or None, which means to use the default timeout).
    """
    if os.path.exists(dest):
        logging.info('* alredy saved: {}'.format(dest))
        return
    with open(dest, 'wb') as news:
        try:
            logging.debug("from url {}".format(url))
            data = urlreq.urlopen(url, timeout=timeout)
            news.write(data.read())
            logging.debug("Saved file: {} [{}]".format(
                    dest, filetype(dest).decode('utf-8')))
        except IOError as err:
            logging.error('** {}: {}'.format(err, url))
            # if destination file has been opened but an error occours,
            # remove the created (invalid or possibly empty) file
            try:
                os.remove(dest)
            except OSError:
                pass # no dest file was even created
            raise SaveError(err)


def save_from_recovery (recfile, timeout=None):
    """Save uris stored in the recovery file."""
    if not os.path.exists(recfile):
        logging.info("No recovery file found, skip...")
        return
    try:
        data = read_recovery(recfile)
        os.remove(recfile)
    except IOError as e:
        logging.info("Error while reading recovery file {}, skip...".format(e))
        return
    logging.info("Start retrieve urls to be recovered...")
    for url, path in data:
        try:
            save(url, path, timeout)
        except SaveError as err:
            write_recovery_entry(recfile, url, path)


def set_headers(headers):
    opener = urlreq.build_opener()
    add_headers(opener, headers)
    urlreq.install_opener(opener)


def set_logger (filepath, level):
    """Set the logging system.
    filepath => where to store the logging infos
    level    => logging level.
    """
    logging.basicConfig(format='%(levelname)s:%(message)s', level=level)
    logfile = logging.handlers.RotatingFileHandler(
        filepath, maxBytes=5000, backupCount=3)
    logfile.setFormatter(logging.Formatter('%(levelname)s:%(message)s'))
    logging.getLogger().addHandler(logfile)


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

def write_recovery_entry (recovery_path, url, destination):
    with open(recovery_path, 'a+b') as rec:
        rec.write("{}\n{}\n\n".format(url, destination).encode("utf-8"))


########
# MAIN #
########
def main(config_file, recfile, always_run, format_func, sections, timeout=None):
    cfg = read_config(config_file)
    recfile = (recfile
               or cfg.defaults().get(Config.Fields.recovery_file, Config.recovery_file)
               or Config.recovery_file)
    if always_run:
        while True:
            cfg = read_config(config_file)
            logging.info('{} start retrieving feeds'.format(time.ctime()))
            run(config_file, recfile, format_func, sections, timeout)
            delay = int(cfg.defaults().get(Config.Fields.delay, Config.delay)
                        or Config.delay)
            logging.info('{} sleeping for {} sec'.format(time.ctime(), delay))
            time.sleep(delay)
    else:
        run(config_file, recfile, format_func, sections, timeout)


if __name__ == '__main__':
    parser = get_arg_parser()
    args = parser.parse_args()

    cfg = read_config(args.cfg)
    user_agent = args.user_agent or (
        cfg.defaults().get(Config.Fields.user_agent, Config.user_agent)
        or Config.user_agent)
    set_headers({'User-agent':user_agent})
    timeout = (args.timeout
               or int(cfg.defaults().get(Config.Fields.timeout, Config.timeout)
               or Config.timeout))

    set_logger(args.log, args.loglevel)
    logging.info('{} start at {}'.format(sys.argv[0], time.ctime()))

    if args.list_sections:
        print("\n".join(cfg.sections()))
        sys.exit(0)

    recfile = (args.recovery_file
               or cfg.defaults().get(Config.Fields.recovery_file, Config.recovery_file)
               or Config.recovery_file)
    save_from_recovery(recfile, timeout)

    if args.from_urls:
        feeds_from_urls(args.from_urls, args.dest or os.getcwd(), timeout)
        sys.exit(0)
    if args.also_from_urls:
        feeds_from_urls(args.also_from_urls, args.dest or os.getcwd(), timeout)
    if args.ffunc:
        module, func = args.ffunc.split('.')
        try:
            format_title = get_format_func(Config.plugin_path, module, func)
        except Exception as err:
            logging.error(err)
            parser.error("Can't load plugin {}: {}".format(args.ffunc, err))
    else:
        format_title = _format_title
    main(args.cfg, args.recovery_file, args.nonstop, format_title, args.sections, timeout)
