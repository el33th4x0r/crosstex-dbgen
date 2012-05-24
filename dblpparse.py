import collections
import errno
import os
import os.path
import re
import string
import sys

import lxml.etree

import latex
import parentheticals
from locations import LOCATION_AMBIGUITIES
from locations import LOCATION_ALIASES
from locations import LOCATIONS


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


class Conference:

    def __init__(self, output, slug, shortname, longname, booktitle):
        self._slug = slug
        self._shortname = shortname
        self._longname = longname
        self._booktitle = booktitle or shortname
        self._year_locations = {}
        self._out = open(output, 'w+')

    def add_proc(self, citekey, citeattrs):
        year = self._extract_year(citekey, citeattrs)
        addr = self._extract_location(citekey, citeattrs)
        mon = self._extract_month(citekey, citeattrs)
        self._year_locations[year] = (addr, mon)

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
        assert citeattrs['booktitle'] == self._booktitle
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
%s  bibsource = {DBLP, http://dblp.uni-trier.de}
}\n'''
        if 'pages' in citeattrs:
            match = page_range_re.search(citeattrs['pages'])
            if match:
                start = int(match.groupdict()['start'])
                end = int(match.groupdict()['end'])
                pagesrt = (start, end)
                pages = '  pages     = {%i-%i},\n' % pagesrt
            else:
                match = page_re.search(citeattrs['pages'])
                if not match:
                    print 'ERROR:  key "%s" has corrupt "pages"' % citekey
                    return
                pagesrt = (int(match.groupdict()['page']),
                           int(match.groupdict()['page']))
                pages = '  pages     = {%i},\n' % pagesrt[0]
        else:
            pagesrt = ''
            pages = ''
        authors = ' and\n               '.join([self._normalize_author(a) for a in citeattrs['author']])
        title = self._normalize_title(citekey, citeattrs)
        bibtex = templ % (citekey, authors, title, self._slug,
                          citeattrs['year'], pages)
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

    def _extract_year(self, citekey, citeattrs):
        if 'year' in citeattrs:
            try:
                return int(citeattrs['year'])
            except ValueError as e:
                print 'WARNING:  key "%s" has non-numeric year' % citekey
        else:
            print 'WARNING:  no year for "%s"' % citekey

    def _extract_location(self, citekey, citeattrs):
        possible = citeattrs.get('title', '').split(',')
        possible = [x.replace(' ', '') for x in possible]
        for p in possible:
            if p in LOCATION_AMBIGUITIES:
                count = 0
                loc = None
                for x in possible:
                    if x in LOCATION_AMBIGUITIES[p]:
                        count += 1
                        loc = x
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
        print 'WARNING:  no month for "%s"' % citekey, citeattrs

    def _normalize_author(self, author):
        if numbered_author_re.search(author):
            author = author[:-5]
        return self._to_latex(author)

    def _normalize_title(self, citekey, citeattrs):
        title = citeattrs['title']
        stack = []
        openparen = title.find('(')
        if openparen >= 0:
            stack.append(openparen)
            ptr = openparen + 1
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
            elif openparen > closeparen:
                substr = title[stack[-1] + 1:closeparen]
                if substr.lower() in parentheticals.BLACKLIST:
                    prefix = title[:stack[-1]].strip(' ')
                    suffix = title[closeparen + 1:].strip(' ')
                    title = prefix + ' ' + suffix
                    stack.pop()
                    if stack:
                        ptr = stack[-1] + 1
                elif substr.lower() in parentheticals.WHITELIST:
                    ptr = closeparen + 1
                    stack.pop()
                elif substr in parentheticals.TRANSLATE:
                    replace = parentheticals.TRANSLATE[substr]
                    title = title[:stack[-1] + 1] + replace + title[closeparen:]
                    ptr = stack[-1] + len(replace) + 2
                    stack.pop()
                else:
                    # See if the words leading up to the parenthetical could be
                    # made into an acronym that fits the parenthetical.
                    words = title[:stack[-1]].replace('-', ' ').split(' ')
                    words = [w for w in words if w]
                    acronym = ''.join([w[0] for w in words[-len(substr):]]).lower()
                    if acronym != substr.lower():
                        print 'WARNING:  unhandled parenthetical %s in title for "%s"' % (repr(substr), citekey), citeattrs
                    ptr = closeparen + 1
                    stack.pop()
        return self._to_latex(title.strip(' .'))

    def _to_latex(self, s):
        ls = ''
        for c in s:
            if ord(c) in latex.latex:
                ls += latex.latex[ord(c)]
            elif c in (string.ascii_letters + string.digits + string.punctuation + ' '):
                ls += c
            else:
                print 'WARNING:  unknown unicode character %s' % repr(c)
        return ls


class DBLPProcessor:

    # infilename is a pre-processed file, that may be opened and closed
    # repeatedly throughout the processing.
    def __init__(self, infilename, ppfilename, outdir):
        self._infilename = infilename
        self._ppfilename = ppfilename
        self._outdir = outdir
        self._proceedings = {}
        self._filters = set()

    def add_conference(self, slug, shortname, longname, booktitle=None):
        key = ('proceedings', 'conf', booktitle or shortname)
        out = os.path.join(self._outdir, slug + '.xtx')
        conf = Conference(out, slug, shortname, longname, booktitle)
        assert slug not in self._proceedings
        self._proceedings[key] = conf
        self._filters.add(slug)
        self._filters.add(shortname)
        self._filters.add(booktitle)

    def process(self):
        self._conditional_preprocess()
        containers = {}
        for citetype, citekey, citeattrs in self._iterate():
            if citetype == 'proceedings':
                booktitle = citeattrs.get('booktitle', None)
                venuetype, junk = citekey.split('/', 1)
                obj = self._proceedings.get((citetype, venuetype, booktitle), None)
                if obj is None:
                    continue
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
                venuetype, junk = citekey.split('/', 1)
                key = ('proceedings', venuetype, booktitle)
                if key in self._proceedings:
                    self._proceedings[key].add_inproc(citetype, citekey, citeattrs)
        for proceedings in self._proceedings.values():
            proceedings.post_process()

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
                    element.clear()
                    del element
                    event, element = e.next()
                    if event == 'end' and element.tag == citetype and count == 0:
                        break
                    elif event == 'end' and element.tag == citetype:
                        count -= 1
                    elif event == 'start' and element.tag == citetype:
                        count += 1
                    elif select and (event == 'start' or event == 'end'):
                        if element.text is not None:
                            if element.tag == 'author':
                                citeattrs['author'].append(element.text)
                            elif citeattrs.get(element.tag, None) is None:
                                citeattrs[element.tag] = element.text
                if select:
                    fout.write('%s\n' % repr((citetype, citekey, citeattrs)))
                element.clear()
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
d.add_conference('nsdi', 'NSDI', 'Symposium on Networked System Design and Implementation')
d.add_conference('osdi', 'OSDI', 'Symposium on Operating System Design and Implementation')
d.add_conference('sosp', 'SOSP', 'Symposium on Operating Systems Principles')
d.process()
