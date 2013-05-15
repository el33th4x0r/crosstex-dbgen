import collections
import datetime
import errno
import itertools
import os
import os.path
import re
import string
import sys
import datetime

import lxml.etree

import parentheticals
import overrides
from locations import LOCATION_AMBIGUITIES
from locations import LOCATION_ALIASES
from locations import LOCATIONS
from locations import MANUAL_LOCATIONS


MONTHS = {'January': 'jan',
          'February': 'feb',
          'March': 'mar',
          'April': 'apr',
          'May': 'may',
          'June': 'jun',
          'July': 'jul',
          'August': 'aug',
          'September': 'sep',
          'October': 'oct',
          'November': 'nov',
          'December': 'dec'}


numbered_author_re = re.compile(r' [0-9]{4}$')
page_range_re = re.compile(r'(?P<start>[0-9]+)[^0-9]+(?P<end>[0-9]+)')
page_re = re.compile(r'(?P<page>[0-9]+)')
algorithm_re = re.compile(r'[aA]lgorithm\s+[0-9]+')


class CitationContainer:

    def _normalize_author(self, author):
        if numbered_author_re.search(author):
            author = author[:-5]
        return author

    def _normalize_title(self, citekey, citeattrs):
        title = citeattrs['title']
        stack = []
        openparen = title.find('(')
        equation = None
        if openparen >= 0:
            stack.append(openparen)
            ptr = openparen + 1
            if openparen > 0 and \
               title[openparen - 1] not in string.whitespace and \
               equation is None:
                equation = openparen
        while stack:
            openparen = title.find('(', ptr)
            openparen = openparen if openparen >= 0 else len(title)
            closeparen = title.find(')', ptr)
            closeparen = closeparen if closeparen >= 0 else len(title)
            if openparen == closeparen:
                stack = []
            elif openparen < closeparen:
                stack.append(openparen)
                ptr = openparen + 1
                if openparen > 0 and \
                   title[openparen - 1] not in string.whitespace and \
                   equation is None:
                    equation = openparen
            elif openparen > closeparen:
                substr = title[stack[-1] + 1:closeparen]
                if substr.lower() in parentheticals.BLACKLIST:
                    prefix = title[:stack[-1]].strip(' ')
                    suffix = title[closeparen + 1:].strip(' ')
                    title = prefix + ' ' + suffix
                    if equation == stack[-1]:
                        equation = None
                    stack.pop()
                    if stack:
                        ptr = stack[-1] + 1
                elif substr.lower() in parentheticals.WHITELIST:
                    ptr = closeparen + 1
                    if equation == stack[-1]:
                        equation = None
                    stack.pop()
                elif substr in parentheticals.TRANSLATE:
                    replace = parentheticals.TRANSLATE[substr]
                    title = title[:stack[-1] + 1] + replace + title[closeparen:]
                    ptr = stack[-1] + len(replace) + 2
                    if equation == stack[-1]:
                        equation = None
                    stack.pop()
                elif equation is not None:
                    if equation == stack[-1]:
                        equation = None
                    ptr = closeparen + 1
                    stack.pop()
                else:
                    # See if the words leading up to the parenthetical could be
                    # made into an acronym that fits the parenthetical.
                    words = title[:stack[-1]].replace('-', ' ').split(' ')
                    words = [w for w in words if w]
                    acronym = ''.join([w[0] for w in words[-len(substr):]]).lower()
                    if algorithm_re.search(substr) is not None:
                        acronym = substr # To make the next conditional always fail
                    if acronym.lower() != substr.lower():
                        print 'WARNING:  unhandled parenthetical %s in title for "%s"' % (repr(substr), citekey), citeattrs
                    ptr = closeparen + 1
                    if equation == stack[-1]:
                        equation = None
                    stack.pop()
        return self._caps_stuff(title.strip(' .'))

    def _normalize_pages(self, p):
        pagesrt = (-1, '')
        pages   = ''
        if p is None:
            return pagesrt, pages
        match = page_range_re.search(p)
        if match:
            start = int(match.groupdict()['start'])
            end = int(match.groupdict()['end'])
            pagesrt = (start, end)
            pages = '  pages     = {%i-%i},\n' % pagesrt
        else:
            match = page_re.search(p)
            if match:
                pagesrt = (int(match.groupdict()['page']),
                           int(match.groupdict()['page']))
                pages = '  pages     = {%i},\n' % pagesrt[0]
            else:
                if not set(p) - set(['v', 'i', 'x', '-']):
                    pagesrt = (-1, p)
                    pages = '  pages     = {%s},\n' % pagesrt[1]
                else:
                    print 'ERROR:  corrupt "pages" %r' % p
        return pagesrt, pages

    def _to_upper_quoted(self, s):
        s = s.group()
        ns = s.strip(' \t\n')
        if ns.upper not in ('A',):
            if s.startswith(ns):
                return '{' + ns + '}'
            else:
                return ' {' + ns + '}'
        else:
            return s

    _caps_re = re.compile(r"(\s|\A)*[a-zA-Z][-a-z_]*[A-Z][-a-zA-Z_]*(?:'s)?(?=(\s|\Z))")

    def _caps_stuff(self, s):
        return self._caps_re.sub(self._to_upper_quoted, s)


class Conference(CitationContainer):

    def __init__(self, output, slug, shortname, longname, citetype='conference'):
        self._slug = slug
        self._shortname = shortname
        self._longname = longname
        self._years = {}
        self._out = open(output, 'w+')
        self._citetype = citetype

    def add_proc(self, citekey, citeattrs):
        year = self._extract_year(citekey, citeattrs)
        addr = self._extract_location(citekey, citeattrs)
        mon = self._extract_month(citekey, citeattrs)
        self._years[year] = (addr, mon)

    def add_inproc(self, citetype, citekey, citeattrs):
        if 'author' not in citeattrs:
            print 'ERROR:  key "%s" has no attribute "author"' % citekey
            return
        if 'title' not in citeattrs:
            print 'ERROR:  key "%s" has no attribute "title"' % citekey
            return
        if 'booktitle' not in citeattrs:
            print 'ERROR:  key "%s" has no attribute "booktitle"' % citekey
            return
        if 'year' not in citeattrs:
            print 'ERROR:  key "%s" has no attribute "year"' % citekey
            return
        if 'pages' not in citeattrs:
            print 'INFO:  key "%s" has no attribute "pages"' % citekey
        try:
            citeattrs['year'] = int(citeattrs['year'])
        except ValueError:
            print 'ERROR:  key "%s" has non-integer "year"' % citekey
            return
        templ = '''\n@inproceedings{DBLP:%s,
  author    = {%s},
  title     = {%s},
  booktitle = %s,
  year      = %i,
%s}\n'''
        pagesrt, pages = self._normalize_pages(citeattrs.get('pages', None))
        authors = ' and\n               '.join([self._normalize_author(a) for a in citeattrs['author']])
        if citekey in overrides.TITLE:
            title = overrides.TITLE[citekey]
        else:
            title = self._normalize_title(citekey, citeattrs)
        bibtex = templ % (citekey, authors, title, self._slug,
                          citeattrs['year'], pages)
        if citeattrs['year'] not in self._years:
            self._years[citeattrs['year']] = None, None
        self._out.write(repr((0 - citeattrs['year'], pagesrt, citekey, bibtex)) + '\n')

    def post_process(self):
        self._out.seek(0)
        tmp = [eval(line[:-1]) for line in self._out]
        self._out.seek(0)
        self._out.truncate(0)
        self._out.write('@include conferences-cs\n')
        for year, pages, citekey, bibtex in sorted(tmp):
            self._out.write(bibtex.encode('utf8'))
        self._out.flush()

    def write_citation(self, fout):
        years = self._years.copy()
        years.update(overrides.CONFERENCE_LOCATIONS.get(self._slug, {}))
        yearsstr = ''
        for year, (addr, mon) in reversed(sorted(years.items())):
            if addr is None or mon is None:
                print 'WARNING:  conference "%s" missing information for year %i' % (self._slug, year)
            else:
                yearsstr += '  [year=%04i] address=%s, month=%s,\n' % (year, addr, mon)
        if self._shortname == self._longname:
            templ = '''\n@%s{%s,
  name = "%s",
%s}\n'''
            citation = templ % (self._citetype, self._slug, self._shortname, yearsstr)
        else:
            templ = '''\n@%s{%s,
  shortname = "%s",
  longname  = "%s",
%s}\n'''
            citation = templ % (self._citetype, self._slug, self._shortname, self._longname, yearsstr)
        fout.write(citation.encode('utf8'))

    def _extract_year(self, citekey, citeattrs):
        if 'year' in citeattrs:
            try:
                return int(citeattrs['year'])
            except ValueError as e:
                print 'WARNING:  key "%s" has non-numeric year' % citekey
        else:
            print 'WARNING:  no year for "%s"' % citekey

    def _extract_location(self, citekey, citeattrs):
        if citekey in MANUAL_LOCATIONS:
            return MANUAL_LOCATIONS[citekey]
        possible = re.split('[,?]', citeattrs.get('title', ''))
        #possible = citeattrs.get('title', '').split(',')
        possible = [x.replace(' ', '').replace('.', '').replace("'", '') for x in possible]
        for p in possible:
            if p in LOCATION_AMBIGUITIES:
                count = 0
                loc = None
                for x in possible:
                    if x in LOCATION_AMBIGUITIES[p]:
                        count += 1
                        loc = LOCATION_AMBIGUITIES[p][x]
                if count == 1:
                    return loc
                print 'WARNING:  "%s" resolves to ambiguous location' % citekey, citeattrs
                return
            if p in LOCATIONS:
                return p
            if p in LOCATION_ALIASES:
                return LOCATION_ALIASES[p]
        print 'WARNING:  no location for "%s"' % citekey, citeattrs

    def _extract_month(self, citekey, citeattrs):
        possible = citeattrs.get('title', '').split(' ')
        for p in possible:
            if p in MONTHS:
                return MONTHS[p]
        for month, abbrev in MONTHS.iteritems():
            if month in citeattrs.get('title', ''):
                return abbrev
        try:
            year = int(citeattrs['year'])
            if self._slug in overrides.CONFERENCE_LOCATIONS and \
               year in overrides.CONFERENCE_LOCATIONS[self._slug]:
                return overrides.CONFERENCE_LOCATIONS[self._slug][year][1]
        except ValueError:
            pass
        print 'WARNING:  no month for "%s"' % citekey, citeattrs


class Journal(CitationContainer):

    def __init__(self, output, slug, shortname, longname):
        self._slug = slug
        self._shortname = shortname
        self._longname = longname
        self._out = open(output, 'w+')

    def add_article(self, citetype, citekey, citeattrs):
        if 'author' not in citeattrs:
            print 'ERROR:  key "%s" has no attribute "author"' % citekey
            return
        if 'title' not in citeattrs:
            print 'ERROR:  key "%s" has no attribute "title"' % citekey
            return
        if 'journal' not in citeattrs:
            print 'ERROR:  key "%s" has no attribute "journal"' % citekey
            return
        if 'volume' not in citeattrs:
            print 'WARNING:  key "%s" has no attribute "volume"' % citekey
        if 'number' not in citeattrs and citekey not in overrides.JOURNAL_NUMBERS:
            print 'WARNING:  key "%s" has no attribute "number"' % citekey
        if 'year' not in citeattrs:
            print 'ERROR:  key "%s" has no attribute "year"' % citekey
            return
        if 'pages' not in citeattrs:
            pass
            #print 'INFO:  key "%s" has no attribute "pages"' % citekey
        try:
            citeattrs['year'] = int(citeattrs['year'])
        except ValueError:
            print 'ERROR:  key "%s" has non-integer "year"' % citekey
            return
        templ = '''\n@article{DBLP:%s,
  author    = {%s},
  title     = {%s},
  journal   = %s,
%s%s  year      = %i,
%s}\n'''
        volume = citeattrs.get('volume', '')
        number = citeattrs.get('number', '')
        if citekey in overrides.JOURNAL_NUMBERS:
            number = str(overrides.JOURNAL_NUMBERS[citekey])
        volume = volume and '  volume    = {%s},\n' % volume
        number = number and '  number    = {%s},\n' % number
        pagesrt, pages = self._normalize_pages(citeattrs.get('pages', None))
        authors = ' and\n               '.join([self._normalize_author(a) for a in citeattrs['author']])
        if citekey in overrides.TITLE:
            title = overrides.TITLE[citekey]
        else:
            title = self._normalize_title(citekey, citeattrs)
        bibtex = templ % (citekey, authors, title, self._slug,
                          volume, number, citeattrs['year'], pages)
        self._out.write(repr((0 - citeattrs['year'], pagesrt, citekey, bibtex)) + '\n')

    def post_process(self):
        self._out.seek(0)
        tmp = [eval(line[:-1]) for line in self._out]
        self._out.seek(0)
        self._out.truncate(0)
        self._out.write('@include journals-cs\n')
        for year, pages, citekey, bibtex in sorted(tmp):
            self._out.write(bibtex.encode('utf8'))
        self._out.flush()

    def write_citation(self, fout):
        if self._shortname == self._longname:
            templ = '''@journal{%s, name = "%s"}\n'''
            citation = templ % (self._slug, self._shortname)
        else:
            templ = '''@journal{%s, shortname = "%s", longname  = "%s"}\n'''
            citation = templ % (self._slug, self._shortname, self._longname)
        fout.write(citation.encode('utf8'))


class DBLPProcessor:

    # infilename is the input, typically in the format of dblp.xml
    # cachefilename is a file that's used to cache relevant info and avoid
    #       expensive multi-pass computation over the full input
    # outdir is a directory in which the output is stored
    def __init__(self, infilename, cachefilename, outdir):
        self._infilename = infilename
        self._cachefilename = cachefilename
        self._outdir = outdir
        # keep slugs, names, and booktitles unique
        self._slugs = {}
        self._shortnames = {}
        self._longnames = {}
        self._names = {}
        self._prefixes = collections.defaultdict(list)
        # for generating meta files; one per add_*
        self._conferences = []
        self._journals = []
        self._workshops = []

    def add_conference(self, slug, shortname, longname=None,
                             prefixes=(), names=()):
        longname = longname or shortname
        assert slug not in self._slugs
        assert shortname not in self._shortnames
        assert longname not in self._longnames
        assert isinstance(prefixes, tuple)
        assert isinstance(names, tuple)
        assert len(set(names) & set(self._names.keys())) == 0

        out = os.path.join(self._outdir, slug + '.xtx')
        conf = Conference(out, slug, shortname, longname, citetype='conference')
        self._slugs[slug]           = conf
        self._shortnames[shortname] = conf
        self._longnames[longname]   = conf
        for prefix in prefixes:
            self._prefixes[prefix].append(conf)
        for name in names:
            self._names[name]       = conf
        self._conferences.append((slug, conf))

    def add_journal(self, slug, shortname, longname=None,
                          prefixes=(), names=()):
        longname = longname or shortname
        assert slug not in self._slugs
        assert shortname not in self._shortnames
        assert longname not in self._longnames
        assert isinstance(prefixes, tuple)
        assert isinstance(names, tuple)
        assert len(set(names) & set(self._names.keys())) == 0

        out = os.path.join(self._outdir, slug + '.xtx')
        jo = Journal(out, slug, shortname, longname)
        self._slugs[slug]           = jo
        self._shortnames[shortname] = jo
        self._longnames[longname]   = jo
        for prefix in prefixes:
            self._prefixes[prefix].append(jo)
        for name in names:
            self._names[name]       = jo
        self._journals.append((slug, jo))

    def add_workshop(self, slug, shortname, longname=None,
                           prefixes=(), names=()):
        longname = longname or shortname
        assert slug not in self._slugs
        assert shortname not in self._shortnames
        assert longname not in self._longnames
        assert isinstance(prefixes, tuple)
        assert isinstance(names, tuple)
        assert len(set(names) & set(self._names.keys())) == 0

        out = os.path.join(self._outdir, slug + '.xtx')
        conf = Conference(out, slug, shortname, longname, citetype='workshop')
        self._slugs[slug]           = conf
        self._shortnames[shortname] = conf
        self._longnames[longname]   = conf
        for prefix in prefixes:
            self._prefixes[prefix].append(conf)
        for name in names:
            self._names[name]       = conf
        self._workshops.append((slug, conf))

    def process(self):
        self._conditional_preprocess()
        containers = {} # a dictionary from key->object for containers
        for citetype, citekey, citeattrs in self._iterate():
            if citetype == 'proceedings':
                booktitle = citeattrs.get('booktitle', None)
                if booktitle is None and 'title' in citeattrs:
                    booktitle = citeattrs['title']
                    citeattrs['booktitle'] = citeattrs['title']
                obj = self._lookup_container_by_name(booktitle)
                if not obj:
                    continue
                containers[citekey] = obj
                obj.add_proc(citekey, citeattrs)
        for citetype, citekey, citeattrs in self._iterate():
            crossref = citeattrs.get('crossref', None)
            # Short-circuit, easy case!
            if crossref in containers:
                containers[crossref].add_inproc(citetype, citekey, citeattrs)
            # Otherwise we need to guess
            elif citetype == 'inproceedings' and crossref is None:
                booktitle = citeattrs.get('booktitle', None)
                conf = self._lookup_container_by_name(booktitle)
                if conf and hasattr(conf, 'add_inproc'):
                    conf.add_inproc(citetype, citekey, citeattrs)
            elif citetype == 'article' and crossref is None:
                journal = citeattrs.get('journal', None)
                j = self._lookup_container_by_name(journal)
                if j and hasattr(j, 'add_article'):
                    j.add_article(citetype, citekey, citeattrs)
        with open(os.path.join(self._outdir, 'conferences-cs.xtx'), 'w') as fout:
            fout.write('@include dates\n@include locations\n@include conferences-cs-todo\n')
            for key, conf in self._conferences:
                conf.post_process()
                conf.write_citation(fout)
        with open(os.path.join(self._outdir, 'workshops-cs.xtx'), 'w') as fout:
            fout.write('@include conferences-cs\n@include workshops-cs-todo\n')
            for key, conf in self._workshops:
                conf.post_process()
                conf.write_citation(fout)
        with open(os.path.join(self._outdir, 'journals-cs.xtx'), 'w') as fout:
            for key, jo in self._journals:
                jo.post_process()
                jo.write_citation(fout)
        with open(os.path.join(self._outdir, 'TIMESTAMP'), 'w') as fout:
            fout.write(str(datetime.datetime.now()) + '\n')

    def _lookup_container_by_name(self, name):
        container = self._shortnames.get(name, None)
        container = container or self._longnames.get(name, None)
        container = container or self._names.get(name, None)
        if container is not None:
            return container
        names = itertools.chain(self._names.iteritems(),
                                self._longnames.iteritems(),
                                self._shortnames.iteritems())
        for n, container in names:
            if n in name:
                return container

    def _preprocess(self):
        prefixes = set(self._prefixes.keys())
        for slug in self._slugs:
            prefixes.add('conf/' + slug)
            prefixes.add('journals/' + slug)
        # Parse the XML into Python dictionaries, one per line
        # This is then filtered to a superset of the documents we need, but it's
        # a much smaller superset than the whole DBLP XML file.  Plus, being
        # line-oriented, parsing is much faster
        with open(self._cachefilename, 'w') as fout:
            e = lxml.etree.iterparse(self._infilename, events=('start', 'end'),
                                     dtd_validation=True, load_dtd=True)
            event, element = e.next()
            assert event == 'start'
            assert element.tag == 'dblp'

            for event, element in e:
                if event == 'end' and element.tag == 'dblp':
                    break
                citetype = element.tag
                citekey = element.attrib.get('key', None)
                select = '/'.join(citekey.split('/')[:2]) in prefixes
                citeattrs = {'author': []}
                count = 0
                while True:
                    event, element = e.next()
                    if event == 'end' and element.tag == citetype and count == 0:
                        break
                    elif event == 'end' and element.tag == citetype:
                        count -= 1
                    elif event == 'start' and element.tag == citetype:
                        count += 1
                    elif select and (event == 'start' or event == 'end'):
                        if element.tag == 'title' and event == 'start':
                            citeattrs['title'] = ''.join([x for x in element.itertext()])
                        elif element.tag == 'title' and event == 'end' and not citeattrs['title']:
                            citeattrs['title'] = ''.join([x for x in element.itertext()])
                        elif element.text is not None:
                            if element.tag == 'author':
                                if element.text not in citeattrs['author']:
                                    citeattrs['author'].append(element.text)
                            elif citeattrs.get(element.tag, None) is None:
                                citeattrs[element.tag] = element.text
                if select:
                    if 'cite' in citeattrs:
                        del citeattrs['cite']
                    fout.write(('%s\n' % repr((citetype, citekey, citeattrs))))
                element.clear()
                while element.getprevious() is not None:
                    del element.getparent()[0]
                del element
            assert event == 'end'
            assert element.tag == 'dblp'
            del e

    def _conditional_preprocess(self):
        if os.path.exists(self._cachefilename) and \
                os.stat(self._infilename).st_ctime < os.stat(self._cachefilename).st_ctime:
            return
        self._preprocess()

    def _iterate(self):
        with open(self._cachefilename, 'r') as fin:
            for line in fin:
                yield eval(line[:-1])


d = DBLPProcessor(infilename='dblp.xml', cachefilename='dblp.xml.pp', outdir='xtx')
d.add_conference('cikm',        'CIKM', 'International Conference on Information and Knowledge Management')
d.add_conference('eurosys',     'EuroSys', 'European Conference on Computer Systems')
d.add_conference('focs',        'FOCS', 'Symposium on Foundations of Computer Science')
d.add_conference('fast',        'FAST', 'Conference on File and Storage Technologies')
d.add_conference('hicss',       'HICSS', 'Hawaii International International Conference on Systems')
d.add_conference('icdcs',       'ICDCS', 'International Conference on Distributed Computing Systems')
d.add_conference('imc',         'IMC', 'Internet Measurement Conference')
d.add_conference('infocom',     'INFOCOM', 'IEEE International Conference on Computer Communications')
d.add_conference('ipdps',       'IPDPS', 'International Parallel and Distributed Processing Symposium', prefixes=('conf/ipps',), names=('IPDPS',))
d.add_conference('ipps',        'IPPS', 'International Parallel Processing Symposium', prefixes=('conf/ipps',))
d.add_conference('mobicom',     'MOBICOM', 'International Conference on Mobile Computing and Networking')
d.add_conference('nsdi',        'NSDI', 'Symposium on Networked System Design and Implementation')
d.add_conference('osdi',        'OSDI', 'Symposium on Operating System Design and Implementation')
d.add_conference('pldi',        'PLDI', 'SIGPLAN Conference on Programming Language Design and Implementation')
d.add_conference('podc',        'PODC', 'ACM Symposium on Principles of Distributed Computing')
d.add_conference('pods',        'PODS', 'Symposium on Principles of Database Systems')
d.add_conference('popl',        'POPL', 'Symposium on Principles of Programming Languages')
d.add_conference('sigcomm',     'SIGCOMM', 'SIGCOMM Conference')
d.add_conference('sigmod',      'SIGMOD', 'SIGMOD International Conference on Management of Data', names=('SIGMOD Conference',))
d.add_conference('socc',        'SoCC', 'Symposium on Cloud Computing', prefixes=('conf/ipps',))
d.add_conference('soda',        'SODA', 'Symposium on Discrete Algorithms')
d.add_conference('sosp',        'SOSP', 'Symposium on Operating Systems Principles')
d.add_conference('stoc',        'STOC', 'ACM Symposium on Theory of Computing')
d.add_conference('sacmat',      'SACMAT', 'ACM Symposium on Access Control Models and Technologies')
d.add_conference('saint',       'SAINT', 'International Symposium on Applications and the Internet')
d.add_conference('wwca',        'WWCA', 'Worldwide Computing and its Applications')
d.add_conference('cidr',        'CIDR', 'Conference on Innovative Data Systems Research')
d.add_conference('vldb',        'VLDB', 'International Conference on Very Large Data Bases')
d.add_workshop('esigops',       'ESIGOPS Workshop', 'European SIGOPS Workshop', prefixes=('conf/sigopsE',), names=('ACM SIGOPS European Workshop',))
d.add_workshop('grid',          'GRID Workshop', 'International Workshop on Grid Computing', names=('GRID',))
d.add_workshop('hotnets',       'HotNets Workshop', 'Workshop on Hot Topics in Networks', names=('HotNets',))
d.add_workshop('hotos',         'HotOS Workshop', 'Workshop on Hot Topics in Operating Systems', names=('HotOS',))
d.add_workshop('iptps',         'IPTPS Workshop', 'International Workshop on Peer-to-Peer Systems', names=('IPTPS',))
d.add_workshop('webdb',         'WebDB Workshop', 'International Workshop on the Web and Databases', names=('WebDB',))
# ACM publications
d.add_journal('acmcs',          'ACM Computing Surveys', prefixes=('journals/csur',), names=('ACM Comput. Surv.',))
d.add_journal('cacm',           'CACM', 'Communications of the ACM', names=('Commun. ACM',))
d.add_journal('jacm',           'JACM', 'Journal of the ACM', names=('J. ACM',))
d.add_journal('tissec',         'ACM TISSEC', 'ACM Transactions on Information and System Security', names=('ACM Trans. Inf. Syst. Secur.',))
d.add_journal('tocs',           'ACM ToCS', 'ACM Transactions on Computer Systems', names=('ACM Trans. Comput. Syst.',))
d.add_journal('tods',           'ACM ToDS', 'ACM Transactions on Database Systems', names=('ACM Trans. Database Syst.',))
d.add_journal('tomacs',         'ACM ToMaCS', 'ACM Transactions on Modeling and Computer Simulation', names=('ACM Trans. Model. Comput. Simul.',))
d.add_journal('ton',            'ToN', 'IEEE \\slash ACM Transactions on Networking', names=('IEEE/ACM Trans. Netw.',))
d.add_journal('toplas',         'ACM ToPLaS', 'ACM Transactions on Programming Languages and Systems', prefixes=('journals/toplas',), names=('ACM Trans. Program. Lang. Syst.',))
d.add_journal('queue',          'ACM Queue')
# SIG publications
d.add_journal('ccr',            'CCR', 'SIGCOMM Computer Communications Review', names=('Computer Communication Review',))
d.add_journal('osr',            'OSR', 'SIGOPS Operating Systems Review', prefixes=('journals/sigops',), names=('Operating Systems Review',))
# IEEE publications
d.add_journal('ieeecomputer',   'IEEE Computer', prefixes=('journals/computer',))
d.add_journal('ieeeconcurrency', 'IEEE Concurrency', prefixes=('journals/ieeecc',))
d.add_journal('ieeeis',         'IEEE IS', 'IEEE Intelligent Systems', prefixes=('journals/expert',), names=('IEEE Intelligent Systems',))
d.add_journal('ieeenetwork',    'IEEE Network Magazine', prefixes=('journals/network',), names=('IEEE Network',))
d.add_journal('ieeesac',        'IEEE Journal on Selected Areas in Communications', prefixes=('journals/jsac',))
d.add_journal('ieeesecpriv',    'IEEE Security {\&} Privacy', prefixes=('journals/ieeesp',), names=('IEEE Security & Privacy',))
d.add_journal('ieeese',         'IEEE Transactions on Software Engineering', prefixes=('journals/tse',), names=('IEEE Trans. Software Eng.',))
d.add_journal('ieeetc',         'IEEE ToC', 'IEEE Transactions on Computers', prefixes=('journals/tc',), names=('IEEE Trans.  Computers',))
d.add_journal('tpds',           'IEEE Transactions on Parallel and Distributed Systems', names=('IEEE Trans. Parallel Distrib. Syst.',))
# Miscellaneous
d.add_journal('compnet',        'Computer Networks', prefixes=('cn',))
d.add_journal('cst',            'Computer Science and Technology', prefixes=('journals/jcst',), names=('J. Comput. Sci.  Technol.',))
d.add_journal('dse',            'Distributed Systems Engineering', names=('Distributed Systems Engineering',))
d.add_journal('ibmsj',          'IBM Systems Journal')
d.add_journal('login',          ';login:', )
d.add_journal('mms',            'Multimedia Systems Journal', names=('Multimedia Syst.',))
d.add_journal('scp',            'Science of Computer Programming', names=('Sci. Comput. Program.',))
d.add_journal('pvldb',          'PVLDB', 'Proceedings of the VLDB Endowment')

d.process()
