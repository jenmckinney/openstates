import re
import datetime

from billy.scrape.bills import BillScraper, Bill
from billy.scrape.votes import Vote
from openstates.utils import LXMLMixin

import lxml.html
import scrapelib
import logging

logger = logging.getLogger('openstates')


SUB_BLACKLIST = [
    "Second Substitute",
    "Third Substitute",
    "Fourth Substitute",
    "Fifth Substitute",
    "Sixth Substitute",
    "Seventh Substitute",
    "Eighth Substitute",
    "Ninth Substitute",
    "Substitute",
]  # Pages are the same, we'll strip this from bills we catch.



class UTBillScraper(BillScraper, LXMLMixin):
    jurisdiction = 'ut'

    def accept_response(self, response):
        # check for rate limit pages
        normal = super(UTBillScraper, self).accept_response(response)
        return (normal and
                'com.microsoft.jdbc.base.BaseSQLException' not in
                    response.text and
                'java.sql.SQLException' not in
                    response.text)
        # The UT site has been throwing a lot of transiant DB errors, these
        # will backoff and retry if their site has an issue. Seems to happen
        # often enough.

    def scrape(self, session, chambers):
        self.validate_session(session)

        # Identify the index page for the given session
        sessions = self.lxmlize(
                'http://le.utah.gov:443/Documents/bills.htm')
        sessions = sessions.xpath('//p/a[contains(text(), {})]'.format(session))
        
        session_url = ''
        for elem in sessions:
            if re.sub(r'\s+', " ", elem.xpath('text()')[0]) == \
                    self.metadata['session_details'][session]['_scraped_name']:
                session_url = elem.xpath('@href')[0]
        assert session_url != ''

        # Identify all the bill lists linked from a given session's page
        bill_indices = [
                re.sub(r'^r', "", x) for x in
                self.lxmlize(session_url).xpath('//div[contains(@id, "0")]/@id')
                ]

        # Capture the bills from each of the bill lists
        for bill_index in bill_indices:
            if bill_index.startswith("H"):
                chamber = 'lower'
            elif bill_index.startswith("S"):
                chamber = 'upper'
            else:
                raise AssertionError(
                        "Unknown bill type found: {}".format(bill_index))

            bill_index = self.lxmlize(session_url + "&bills=" + bill_index)
            bills = bill_index.xpath('//a[contains(@href, "/bills/static/")]')

            for bill in bills:
                self.scrape_bill(
                        chamber=chamber,
                        session=session,
                        bill_id=bill.xpath('text()')[0],
                        url=bill.xpath('@href')[0]
                        )

    def scrape_bill(self, chamber, session, bill_id, url):
        try:
            page = self.urlopen(url)
        except scrapelib.HTTPError:
            self.warning("couldn't open %s, skipping bill" % url)
            return
        page = lxml.html.fromstring(page)
        page.make_links_absolute(url)

        header = page.xpath('//h3/br')[0].tail.replace('&nbsp;', ' ')
        title, primary_sponsor = header.split(' -- ')

        if bill_id.startswith('H.B.') or bill_id.startswith('S.B.'):
            bill_type = 'bill'
        elif bill_id.startswith('H.R.') or bill_id.startswith('S.R.'):
            bill_type = 'resolution'
        elif bill_id.startswith('H.C.R.') or bill_id.startswith('S.C.R.'):
            bill_type = 'concurrent resolution'
        elif bill_id.startswith('H.J.R.') or bill_id.startswith('S.J.R.'):
            bill_type = 'joint resolution'

        for flag in SUB_BLACKLIST:
            if flag in bill_id:
                bill_id = bill_id.replace(flag, " ")
        bill_id = re.sub("\s+", " ", bill_id).strip()

        bill = Bill(session, chamber, bill_id, title, type=bill_type)
        bill.add_sponsor('primary', primary_sponsor)
        bill.add_source(url)

        for link in page.xpath(
            '//a[contains(@href, "bills/") and text() = "HTML"]'):

            name = link.getprevious().tail.strip()
            bill.add_version(name, link.attrib['href'], mimetype="text/html")
            next = link.getnext()
            if next.text == "PDF":
                bill.add_version(name, next.attrib['href'],
                                 mimetype="application/pdf")

        for link in page.xpath(
            "//a[contains(@href, 'fnotes') and text() = 'HTML']"):

            bill.add_document("Fiscal Note", link.attrib['href'])

        subjects = []
        for link in page.xpath("//a[contains(@href, 'RelatedBill')]"):
            subjects.append(link.text.strip())
        bill['subjects'] = subjects

        status_link = page.xpath('//a[contains(@href, "billsta")]')[0]
        self.parse_status(bill, status_link.attrib['href'])

        self.save_bill(bill)

    def parse_status(self, bill, url):
        page = self.urlopen(url)
        bill.add_source(url)
        page = lxml.html.fromstring(page)
        page.make_links_absolute(url)
        uniqid = 0

        for row in page.xpath('//table/tr')[1:]:
            uniqid += 1
            date = row.xpath('string(td[1])')
            date = datetime.datetime.strptime(date, "%m/%d/%Y").date()

            action = row.xpath('string(td[2])')
            actor = bill['chamber']

            if '/' in action:
                actor = action.split('/')[0].strip()

                if actor == 'House':
                    actor = 'lower'
                elif actor == 'Senate':
                    actor = 'upper'
                elif actor == 'LFA':
                    actor = 'Office of the Legislative Fiscal Analyst'

                action = '/'.join(action.split('/')[1:]).strip()

            if action == 'Governor Signed':
                actor = 'executive'
                type = 'governor:signed'
            elif action == 'Governor Vetoed':
                actor = 'executive'
                type = 'governor:vetoed'
            elif action.startswith('1st reading'):
                type = ['bill:introduced', 'bill:reading:1']
            elif action == 'to Governor':
                type = 'governor:received'
            elif action == 'passed 3rd reading':
                type = 'bill:passed'
            elif action.startswith('passed 2nd & 3rd readings'):
                type = 'bill:passed'
            elif action == 'to standing committee':
                comm_link = row.xpath("td[3]/font/font/a")[0]
                comm = re.match(
                    r"writetxt\('(.*)'\)",
                    comm_link.attrib['onmouseover']).group(1)
                action = "to " + comm
                type = 'committee:referred'
            elif action.startswith('2nd reading'):
                type = 'bill:reading:2'
            elif action.startswith('3rd reading'):
                type = 'bill:reading:3'
            elif action == 'failed':
                type = 'bill:failed'
            elif action.startswith('2nd & 3rd readings'):
                type = ['bill:reading:2', 'bill:reading:3']
            elif action == 'passed 2nd reading':
                type = 'bill:reading:2'
            elif 'Comm - Favorable Recommendation' in action:
                type = 'committee:passed:favorable'
            elif action == 'committee report favorable':
                type = 'committee:passed:favorable'
            else:
                type = 'other'

            bill.add_action(actor, action, date, type=type,
                            _vote_id=uniqid)

            # Check if this action is a vote
            vote_links = row.xpath('./td[4]//a')
            for vote_link in vote_links:
                vote_url = vote_link.attrib['href']

                # Committee votes are of a different format that
                # we don't handle yet
                if not vote_url.endswith('txt'):
                    self.parse_html_vote(bill, actor, date, action,
                                         vote_url, uniqid)
                else:
                    self.parse_vote(bill, actor, date, action,
                                    vote_url, uniqid)

    def scrape_committee_vote(self, bill, actor, date, motion, url, uniqid):
        page = self.urlopen(url)
        page = lxml.html.fromstring(page)
        page.make_links_absolute(url)
        committee = page.xpath("//b")[0].text_content()
        votes = page.xpath("//table")[0]
        rows = votes.xpath(".//tr")[0]
        yno = rows.xpath(".//td")
        if len(yno) < 3:
            yes = yno[0]
            no, other = None, None
        else:
            yes, no, other = rows.xpath(".//td")

        def proc_block(obj):
            if obj is None:
                return {
                    "type": None,
                    "count": None,
                    "votes": []
                }

            typ = obj.xpath("./b")[0].text_content()
            count = obj.xpath(".//b")[0].tail.replace("-", "").strip()
            count = int(count)
            votes = []
            for vote in obj.xpath(".//br"):
                if vote.tail:
                    vote = vote.tail.strip()
                    if vote:
                        votes.append(vote)
            return {
                "type": typ,
                "count": count,
                "votes": votes
            }

        vote_dict = {
            "yes": proc_block(yes),
            "no": proc_block(no),
            "other": proc_block(other),
        }

        yes_count = vote_dict['yes']['count']
        no_count = vote_dict['no']['count'] or 0
        other_count = vote_dict['other']['count'] or 0

        vote = Vote(
            actor,
            date,
            motion,
            (yes_count > no_count),
            yes_count,
            no_count,
            other_count,
            _vote_id=uniqid)
        vote.add_source(url)

        for key in vote_dict:
            for voter in vote_dict[key]['votes']:
                getattr(vote, key)(voter)

        bill.add_vote(vote)

    def parse_html_vote(self, bill, actor, date, motion, url, uniqid):
        page = self.urlopen(url)
        page = lxml.html.fromstring(page)
        page.make_links_absolute(url)
        descr = page.xpath("//b")[0].text_content()

        if "on voice vote" in descr:
            return

        if "committee" in descr.lower():
            return self.scrape_committee_vote(
                bill, actor, date, motion, url, uniqid
            )

        passed = None

        if "Passed" in descr:
            passed = True
        elif "Failed" in descr:
            passed = False
        elif "UTAH STATE LEGISLATURE" in descr:
            return
        else:
            logger.warning(descr)
            raise NotImplemented("Can't see if we passed or failed")

        headings = page.xpath("//b")[1:]
        votes = page.xpath("//table")
        sets = zip(headings, votes)
        vdict = {}
        for (typ, votes) in sets:
            txt = typ.text_content()
            arr = [x.strip() for x in txt.split("-", 1)]
            if len(arr) != 2:
                continue
            v_txt, count = arr
            v_txt = v_txt.strip()
            count = int(count)
            people = [x.text_content().strip() for x in
                      votes.xpath(".//font[@face='Arial']")]

            vdict[v_txt] = {
                "count": count,
                "people": people
            }

        vote = Vote(actor, date,
                    motion,
                    passed,
                    vdict['Yeas']['count'],
                    vdict['Nays']['count'],
                    vdict['Absent or not voting']['count'],
                    _vote_id=uniqid)
        vote.add_source(url)

        for person in vdict['Yeas']['people']:
            vote.yes(person)
        for person in vdict['Nays']['people']:
            vote.no(person)
        for person in vdict['Absent or not voting']['people']:
            vote.other(person)

        logger.info(vote)
        bill.add_vote(vote)


    def parse_vote(self, bill, actor, date, motion, url, uniqid):
        page = self.urlopen(url)
        bill.add_source(url)
        vote_re = re.compile('YEAS -?\s?(\d+)(.*)NAYS -?\s?(\d+)'
                             '(.*)ABSENT( OR NOT VOTING)? -?\s?'
                             '(\d+)(.*)',
                             re.MULTILINE | re.DOTALL)
        match = vote_re.search(page)
        yes_count = int(match.group(1))
        no_count = int(match.group(3))
        other_count = int(match.group(6))

        if yes_count > no_count:
            passed = True
        else:
            passed = False

        if actor == 'upper' or actor == 'lower':
            vote_chamber = actor
            vote_location = ''
        else:
            vote_chamber = ''
            vote_location = actor

        vote = Vote(vote_chamber, date,
                    motion, passed, yes_count, no_count,
                    other_count,
                    location=vote_location,
                    _vote_id=uniqid)
        vote.add_source(url)

        yes_votes = re.split('\s{2,}', match.group(2).strip())
        no_votes = re.split('\s{2,}', match.group(4).strip())
        other_votes = re.split('\s{2,}', match.group(7).strip())

        for yes in yes_votes:
            if yes:
                vote.yes(yes)
        for no in no_votes:
            if no:
                vote.no(no)
        for other in other_votes:
            if other:
                vote.other(other)

        bill.add_vote(vote)
