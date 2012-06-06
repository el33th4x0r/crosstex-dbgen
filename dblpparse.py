import collections
import datetime
import errno
import os
import os.path
import re
import string
import sys

import lxml.etree

import latex
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
        return self._to_latex(author)

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
        return self._caps_stuff(self._to_latex(title.strip(' .')))

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
                    print 'ERROR:  key "%s" has corrupt "pages"' % citekey
        return pagesrt, pages

    def _to_latex(self, s):
        ls = ''
        for c in s:
            if ord(c) in latex.latex:
                ls += latex.latex[ord(c)]
            elif c in (string.ascii_letters + string.digits + string.punctuation + ' '):
                ls += c
            else:
                print 'WARNING:  unknown unicode character %s %i' % (repr(c), ord(c))
        return ls

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

    def __init__(self, output, slug, shortname, longname, booktitle, citetype='conference'):
        self._slug = slug
        self._shortname = shortname
        self._longname = longname
        self._booktitle = booktitle or shortname
        self._years = {}
        self._out = open(output, 'w+')
        self._citetype = citetype

    def add_proc(self, citekey, citeattrs):
        year = self._extract_year(citekey, citeattrs)
        addr = self._extract_location(citekey, citeattrs)
        mon = self._extract_month(citekey, citeattrs)
        self._years[year] = (addr, mon)

    def booktitle_matches(self, booktitle):
        return self._longname.lower() in booktitle.lower()

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
            self._out.write(bibtex)
        self._out.flush()

    def write_citation(self, fout):
        templ = '''\n@%s{%s,
  shortname = "%s",
  longname  = "%s",
%s}\n'''
        years = self._years.copy()
        years.update(overrides.CONFERENCE_LOCATIONS.get(self._slug, {}))
        yearsstr = ''
        for year, (addr, mon) in reversed(sorted(years.items())):
            if addr is None or mon is None:
                print 'WARNING:  conference "%s" missing information for year %i' % (self._slug, year)
            else:
                yearsstr += '  [year=%04i] address=%s, month=%s,\n' % (year, addr, mon)
        citation = templ % (self._citetype, self._slug, self._shortname, self._longname, yearsstr)
        fout.write(citation)

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
        possible = citeattrs.get('title', '').split(',')
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
            self._out.write(bibtex)
        self._out.flush()

    def write_citation(self, fout):
        if self._shortname == self._longname:
            templ = '''@journal{%s, name = "%s"}\n'''
            citation = templ % (self._slug, self._shortname)
        else:
            templ = '''@journal{%s, shortname = "%s", longname  = "%s"}\n'''
            citation = templ % (self._slug, self._shortname, self._longname)
        fout.write(citation)


class DBLPProcessor:

    # infilename is a pre-processed file, that may be opened and closed
    # repeatedly throughout the processing.
    def __init__(self, infilename, ppfilename, outdir):
        self._infilename = infilename
        self._ppfilename = ppfilename
        self._outdir = outdir
        self._proceedings = {}
        self._journals = {}
        self._filters = set()
        self._conference_keys = []
        self._journal_keys = []
        self._workshop_keys = []

    def add_conference(self, slug, shortname, longname, booktitle=None,
                       dblpname=None, dblpslug=None, dblpmany=None):
        longname = longname or shortname
        if not dblpname and not dblpmany:
            dblpname = shortname
        if not dblpslug and not dblpmany:
            dblpslug = slug
        out = os.path.join(self._outdir, slug + '.xtx')
        conf = Conference(out, slug, shortname, longname, booktitle)
        onekey = None
        for dname, dslug in (dblpmany or []) + [(dblpname, dblpslug)]:
            key = ('proceedings', 'conf', dname, dslug)
            assert key not in self._proceedings
            self._proceedings[key] = conf
            onekey = onekey or key
            self._filters.add(dname)
            self._filters.add(dslug)
        assert onekey
        self._conference_keys.append(onekey)
        self._filters.add(shortname)

    def add_journal(self, slug, shortname, longname=None,
                    dblpname=None, dblpslug=None, dblpmany=None):
        longname = longname or shortname
        if not dblpname and not dblpmany:
            dblpname = shortname
        if not dblpslug and not dblpmany:
            dblpslug = slug
        out = os.path.join(self._outdir, slug + '.xtx')
        jo = Journal(out, slug, shortname, longname)
        onekey = None
        for dname, dslug in (dblpmany or []) + [(dblpname, dblpslug)]:
            key = ('journal', dname, dslug)
            assert key not in self._journals
            self._journals[key] = jo
            onekey = onekey or key
            self._filters.add(dname)
            self._filters.add(dslug)
        assert onekey
        self._journal_keys.append(onekey)
        self._filters.add(slug)
        self._filters.add(shortname)

    def add_workshop(self, slug, shortname, longname, booktitle=None, dblpslug=None):
        key = ('proceedings', 'conf', booktitle or shortname, dblpslug or slug)
        out = os.path.join(self._outdir, slug + '.xtx')
        conf = Conference(out, slug, shortname, longname, booktitle, 'workshop')
        assert key not in self._proceedings
        self._workshop_keys.append(key)
        self._proceedings[key] = conf
        self._filters.add(slug)
        self._filters.add(shortname)
        self._filters.add(booktitle)
        self._filters.add(dblpslug)

    def process(self):
        self._conditional_preprocess()
        containers = {}
        for citetype, citekey, citeattrs in self._iterate():
            if citetype == 'proceedings':
                booktitle = citeattrs.get('booktitle', None)
                if booktitle is None and 'title' in citeattrs:
                    booktitle = citeattrs['title']
                    citeattrs['booktitle'] = citeattrs['title']
                venuetype, venueslug, junk = citekey.split('/', 2)
                obj = self._proceedings.get((citetype, venuetype, booktitle, venueslug), None)
                if obj is None:
                    newobj = None
                    for obj in self._proceedings.values():
                        if obj.booktitle_matches(booktitle):
                            newobj = obj
                            break
                    if not newobj:
                        continue
                    obj = newobj
                containers[citekey] = obj
                obj.add_proc(citekey, citeattrs)
        for citetype, citekey, citeattrs in self._iterate():
            crossref = citeattrs.get('crossref', None)
            # Short-circuit, easy case!
            if crossref in containers:
                containers[crossref].add_inproc(citetype, citekey, citeattrs)
            # Otherwise we need to guess
            elif citetype == 'inproceedings':
                booktitle = citeattrs.get('booktitle', None)
                venuetype, venueslug, junk = citekey.split('/', 2)
                key = ('proceedings', venuetype, booktitle, venueslug)
                if key in self._proceedings:
                    self._proceedings[key].add_inproc(citetype, citekey, citeattrs)
            elif citetype == 'article':
                journal = citeattrs.get('journal', None)
                venuetype, venueslug, junk = citekey.split('/', 2)
                key = ('journal', journal, venueslug)
                if key in self._journals:
                    self._journals[key].add_article(citetype, citekey, citeattrs)
                else:
                    print 'INFO:  key "%s" associates with no journal' % citekey

        for proceedings in self._proceedings.values():
            proceedings.post_process()
        for journal in self._journals.values():
            journal.post_process()
        with open(os.path.join(self._outdir, 'conferences-cs.xtx'), 'w') as fout:
            fout.write('@include dates\n@include locations\n')
            for key in self._conference_keys:
                self._proceedings[key].write_citation(fout)
        with open(os.path.join(self._outdir, 'workshops-cs.xtx'), 'w') as fout:
            for key in self._workshop_keys:
                self._proceedings[key].write_citation(fout)
        with open(os.path.join(self._outdir, 'journals-cs.xtx'), 'w') as fout:
            for key in self._journal_keys:
                self._journals[key].write_citation(fout)
        with open(os.path.join(self._outdir, 'TIMESTAMP'), 'w') as fout:
            fout.write(str(datetime.datetime.now()) + '\n')

    def _preprocess(self):
        with open(self._ppfilename, 'w') as fout:
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
                select = bool(set(citekey.split('/')) & self._filters)
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
                    fout.write('%s\n' % repr((citetype, citekey, citeattrs)))
                element.clear()
                while element.getprevious() is not None:
                    del element.getparent()[0]
                del element
            assert event == 'end'
            assert element.tag == 'dblp'
            del e

    def _conditional_preprocess(self):
        if os.path.exists(self._ppfilename) and \
                os.stat(self._infilename).st_ctime < os.stat(self._ppfilename).st_ctime:
            return
        self._preprocess()

    def _iterate(self):
        with open(self._ppfilename) as fin:
            for line in fin:
                yield eval(line[:-1])


d = DBLPProcessor('dblp.xml', 'dblp.xml.pp', 'xtx')
#d.add_conference('cikm',        'CIKM', 'International Conference on Information and Knowledge Management')
d.add_conference('eurosys',     'EuroSys', 'European Conference on Computer Systems')
d.add_conference('focs',        'FOCS', 'Symposium on Foundations of Computer Science')
d.add_conference('fast',        'FAST', 'Conference on File and Storage Technologies')
d.add_conference('icdcs',       'ICDCS', 'International Conference on Distributed Computing Systems')
d.add_conference('ipps',        'IPPS', 'International Parallel Processing Symposium')
d.add_conference('nsdi',        'NSDI', 'Symposium on Networked System Design and Implementation')
d.add_conference('osdi',        'OSDI', 'Symposium on Operating System Design and Implementation')
d.add_conference('pldi',        'PLDI', 'SIGPLAN Conference on Programming Language Design and Implementation')
d.add_conference('podc',        'PODC', 'ACM Symposium on Principles of Distributed Computing')
d.add_conference('pods',        'PODS', 'Symposium on Principles of Database Systems')
d.add_conference('popl',        'POPL', 'Symposium on Principles of Programming Languages')
d.add_conference('sigcomm',     'SIGCOMM', 'SIGCOMM Conference')
d.add_conference('sigmod',      'SIGMOD', 'SIGMOD International Conference on Management of Data', dblpname='SIGMOD Conference')
d.add_conference('socc',        'SoCC', 'Symposium on Cloud Computing', dblpslug='cloud')
d.add_conference('soda',        'SODA', 'Symposium on Discrete Algorithms')
d.add_conference('sosp',        'SOSP', 'Symposium on Operating Systems Principles')
d.add_conference('stoc',        'STOC', 'ACM Symposium on Theory of Computing')
d.add_conference('wwca',        'WWCA', 'Worldwide Computing and its Applications')
d.add_workshop('grid',          'GRID Workshop', 'International Workshop on Grid Computing', booktitle='GRID')
d.add_workshop('hotnets',       'HotNets Workshop', 'Workshop on Hot Topics in Networks', booktitle='HotNets')
d.add_workshop('hotos',         'HotOS Workshop', 'Workshop on Hot Topics in Operating Systems', booktitle='HotOS')
d.add_workshop('iptps',         'IPTPS Workshop', 'International Workshop on Peer-to-Peer Systems', booktitle='IPTPS')
d.add_workshop('webdb',         'WebDB Workshop', 'International Workshop on the Web and Databases', booktitle='WebDB')

# ACM publications
d.add_journal('acmcs',          'ACM Computing Surveys', dblpname='ACM Comput. Surv.', dblpslug='csur')
d.add_journal('cacm',           'CACM', 'Communications of the ACM', dblpname='Commun. ACM')
d.add_journal('jacm',           'JACM', 'Journal of the ACM', dblpname='J. ACM')
d.add_journal('tissec',         'ACM TISSEC', 'ACM Transactions on Information and System Security', dblpname='ACM Trans. Inf. Syst. Secur.')
d.add_journal('tocs',           'ACM ToCS', 'ACM Transactions on Computer Systems', dblpname='ACM Trans. Comput. Syst.')
d.add_journal('tods',           'ACM ToDS', 'ACM Transactions on Database Systems', dblpname='ACM Trans. Database Syst.')
d.add_journal('tomacs',         'ACM ToMaCS', 'ACM Transactions on Modeling and Computer Simulation', dblpname='ACM Trans. Model. Comput. Simul.')
d.add_journal('ton',            'ToN', 'IEEE \\slash ACM Transactions on Networking', dblpname='IEEE/ACM Trans. Netw.')
d.add_journal('toplas',         'ACM ToPLaS', 'ACM Transactions on Programming Languages and Systems', dblpname='ACM Trans. Program. Lang. Syst.', dblpslug='toplas')
d.add_journal('queue',          'ACM Queue')
# SIG publications
d.add_journal('ccr',            'CCR', 'SIGCOMM Computer Communications Review', dblpname='Computer Communication Review')
d.add_journal('osr',            'OSR', 'SIGOPS Operating Systems Review', dblpname='Operating Systems Review', dblpslug='sigops')
# IEEE publications
d.add_journal('ieeecomputer',   'IEEE Computer')
d.add_journal('ieeeconcurrency', 'IEEE Concurrency')
d.add_journal('ieeeis_selfstar', 'IEEE IS', 'IEEE Intelligent Systems, Special Issue on Self-Management through Self-Organization in Information Systems')
d.add_journal('ieeeis',         'IEEE IS', 'IEEE Intelligent Systems')
d.add_journal('ieeenetwork',    'IEEE Network Magazine')
d.add_journal('ieeesac',        'IEEE Journal on Selected Areas in Communications')
d.add_journal('ieeesecpriv',    'IEEE Security and Privacy')
d.add_journal('ieeese',         'IEEE Transactions on Software Engineering')
d.add_journal('ieeetc',         'IEEE ToC', 'IEEE Transactions on Computing')
d.add_journal('jtopds',         'IEEE Transactions on Parallel and Distributed Systems')
# Miscellaneous
d.add_journal('compnet',        'Computer Networks')
d.add_journal('cst',            'Computer Science and Technology')
d.add_journal('dse',            'Distributed Systems Engineering')
d.add_journal('ibmsj',          'IBM Systems Journal')
d.add_journal('login',          ';login:')
d.add_journal('mmsj',           'Multimedia Systems Journal')
d.add_journal('scp',            'Science of Computer Programming')
d.add_journal('pvldb',          'PVLDB', 'Proceedings of the VLDB Endowment')

d.process()
