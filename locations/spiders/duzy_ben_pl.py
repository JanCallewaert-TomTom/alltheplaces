from typing import Any, AsyncIterator

from scrapy import Spider
from scrapy.http import JsonRequest, Response

from locations.categories import Categories, apply_category
from locations.geo import country_iseadgg_centroids
from locations.hours import OpeningHours
from locations.items import Feature

GRAPHQL_QUERY = """query {
    pickupPoints(
        courierId: 100105
        location: { latitude: %s, longitude: %s }
    ) {
        pickupPoints {
            codeExternal
            id
            name
            coordinates { latitude longitude }
            openingDays {
                monday { open allDay from till }
                tuesday { open allDay from till }
                wednesday { open allDay from till }
                thursday { open allDay from till }
                friday { open allDay from till }
                saturday { open allDay from till }
                sunday { open allDay from till }
            }
            address { city postcode street }
        }
    }
}"""

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class DuzyBenPLSpider(Spider):
    name = "duzy_ben_pl"
    item_attributes = {"brand": "Duży Ben", "brand_wikidata": "Q110428071"}
    async def start(self) -> AsyncIterator[JsonRequest]:
        for lat, lon in country_iseadgg_centroids("PL", 48):
            yield JsonRequest(
                url="https://duzyben.pl/graphql/v1/",
                data={"query": GRAPHQL_QUERY % (lat, lon)},
            )

    def parse(self, response: Response, **kwargs: Any) -> Any:
        data = response.json()
        points = data["data"]["pickupPoints"]["pickupPoints"]

        if points:
            self.crawler.stats.inc_value("atp/geo_search/hits")
        else:
            self.crawler.stats.inc_value("atp/geo_search/misses")
        self.crawler.stats.max_value("atp/geo_search/max_features_returned", len(points))

        for point in points:
            address = point["address"]
            item = Feature()
            item["ref"] = point["codeExternal"]
            item["lat"] = point["coordinates"]["latitude"]
            item["lon"] = point["coordinates"]["longitude"]
            item["street_address"] = address.get("street")
            item["city"] = address.get("city")
            item["postcode"] = address.get("postcode")

            item["opening_hours"] = OpeningHours()
            for day in DAYS:
                day_data = point["openingDays"].get(day, {})
                if day_data.get("open"):
                    if day_data.get("allDay"):
                        item["opening_hours"].add_range(day, "00:00", "24:00")
                    elif day_data.get("from") and day_data.get("till"):
                        item["opening_hours"].add_range(day, day_data["from"], day_data["till"])

            apply_category(Categories.SHOP_ALCOHOL, item)

            yield item
