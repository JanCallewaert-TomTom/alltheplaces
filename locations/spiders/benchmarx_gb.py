import re
from typing import Any, AsyncIterator

import chompjs
from scrapy import Request, Spider
from scrapy.http import JsonRequest, Response

from locations.dict_parser import DictParser
from locations.hours import OpeningHours
from locations.pipelines.address_clean_up import merge_address_lines


class BenchmarxGBSpider(Spider):
    name = "benchmarx_gb"
    item_attributes = {"brand": "Benchmarx", "brand_wikidata": "Q102181127"}

    async def start(self) -> AsyncIterator[Any]:
        yield Request(url="https://www.benchmarxkitchens.co.uk/branches", callback=self.parse_branches_page)

    def parse_branches_page(self, response: Response, **kwargs: Any) -> Any:
        chunk_url = response.xpath('//script[contains(@src, "/branches/page-")]/@src').get()
        if chunk_url:
            yield Request(url=response.urljoin(chunk_url), callback=self.parse_chunk)

    def parse_chunk(self, response: Response, **kwargs: Any) -> Any:
        action_ids = re.findall(r'\("([a-f0-9]{40})"\)', response.text)
        if len(action_ids) >= 2:
            yield JsonRequest(
                url="https://www.benchmarxkitchens.co.uk/branches",
                body="[]",
                method="POST",
                headers={"next-action": action_ids[1]},
            )

    def parse(self, response: Response, **kwargs: Any) -> Any:
        for location in list(chompjs.parse_js_objects(response.text))[1]:
            item = DictParser.parse(location)
            item["branch"] = item.pop("name")
            item["street_address"] = merge_address_lines(
                [location["line1"], location["line2"], location["line3"], location["line4"]]
            )
            item["website"] = "https://www.benchmarxkitchens.co.uk/branches/{}".format(location["slug"])
            item["extras"]["check_date"] = location["modifiedAt"]

            item["opening_hours"] = OpeningHours()
            for day, times in location["openingHours"].items():
                item["opening_hours"].add_range(day, times["opening"], times["closing"])

            yield item
