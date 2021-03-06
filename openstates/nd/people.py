from pupa.scrape import Person, Scraper
import lxml.html
import logging
import re

logger = logging.getLogger('openstates')


class NDPersonScraper(Scraper):

    def scrape(self, chamber=None):

        # figuring out starting year from metadata
        start_year = self.jurisdiction.legislative_sessions[-1]['start_date'][:4]
        term = self.jurisdiction.legislative_sessions[-1]['identifier']
        root = "http://www.legis.nd.gov/assembly"
        main_url = "%s/%s-%s/members/members-by-district" % (
            root,
            term,
            start_year
        )

        page = self.get(main_url).text
        page = lxml.html.fromstring(page)
        page.make_links_absolute(main_url)
        for person_url in page.xpath('//div[contains(@class, "all-members")]/'
                                     'div[@class="name"]/a/@href'):
            yield from self.scrape_legislator_page(term, person_url)

    def scrape_legislator_page(self, term, url):
        page = self.get(url).text
        page = lxml.html.fromstring(page)
        page.make_links_absolute(url)
        name = page.xpath("//h1[@id='page-title']/text()")[0]
        name = re.sub(r'^(Representative|Senator)\s', '', name)
        district = page.xpath("//a[contains(@href, 'district')]/text()")[0]
        district = district.replace("District", "").strip()

        committees = page.xpath("//a[contains(@href, 'committees')]/text()")

        photo = page.xpath(
            "//div[@class='field-person-photo']/img/@src"
        )
        photo = photo[0] if len(photo) else None

        address = page.xpath("//div[@class='adr']")
        if address:
            address = address[0]
            address = re.sub("[ \t]+", " ", address.text_content()).strip()
        else:
            address = None

        item_mapping = {
            "email": "email",
            "home telephone": "home-telephone",
            "cellphone": "cellphone",
            "office telephone": "office-telephone",
            "political party": "party",
            "chamber": "chamber",
            "fax": "fax"
        }
        metainf = {}

        for block in page.xpath("//div[contains(@class, 'field-label-inline')]"):
            label, items = block.xpath("./*")
            key = label.text_content().strip().lower()
            if key.endswith(":"):
                key = key[:-1]

            metainf[item_mapping[key]] = items.text_content().strip()

        chamber = {
            "Senate": "upper",
            "House": "lower"
        }[metainf['chamber']]

        party = {"Democrat": "Democratic", "Republican": "Republican"}[metainf['party']]

        person = Person(primary_org=chamber,
                        district=district,
                        name=name,
                        party=party,
                        image=photo)
        person.add_link(url)
        for key, person_key in [('email', 'email'),
                                ('fax', 'fax'),
                                ('office-telephone', 'voice')]:
            if key in metainf:
                if metainf[key].strip():
                    person.add_contact_detail(type=person_key,
                                              value=metainf[key],
                                              note="Capitol Office")
        if address:
            person.add_contact_detail(type='address',
                                      value=address,
                                      note="District Office")
        if 'cellphone' in metainf:
            person.add_contact_detail(type='voice',
                                      value=metainf['cellphone'],
                                      note="District Office")
        if 'home-telephone' in metainf:
            person.add_contact_detail(type='voice',
                                      value=metainf['home-telephone'],
                                      note="District Office")

        for committee in committees:
            person.add_membership(name_or_org=committee, role='committee member')
        person.add_source(url)
        yield person
