from typing import AsyncIterator, Iterable

from scrapy import Spider
from scrapy.http import JsonRequest, Response

from locations.categories import Categories, Extras, apply_category, apply_yes_no
from locations.dict_parser import DictParser
from locations.hours import DAYS_DE, OpeningHours
from locations.items import Feature


class CoopCHSpider(Spider):
    name = "coop_ch"

    COOP = {
        "brand": "Coop",
        "brand_wikidata": "Q432564",
        "category": Categories.SHOP_SUPERMARKET,
        "website": "https://www.coop.ch/de/standorte/{slug}/s/{ref}",
    }
    COOP_CITY = {
        "brand": "Coop City",
        "brand_wikidata": "Q120492050",
        "category": Categories.SHOP_DEPARTMENT_STORE,
        "website": "https://www.coop.ch/de/standorte/{slug}/s/{ref}",
    }
    INTERDISCOUNT = {
        "brand": "Interdiscount",
        "brand_wikidata": "Q1665980",
        "category": Categories.SHOP_ELECTRONICS,
        "website": "https://www.interdiscount.ch/de/storefinder/{ref_num}",
    }
    JUMBO = {
        "brand": "Jumbo",
        "brand_wikidata": "Q1713190",
        "category": Categories.SHOP_DOITYOURSELF,
        "website": "https://www.jumbo.ch/de/standorte/{slug}/s/{ref}",
    }

    BRAND_MAPPING = {
        "Coop Supermarkt": COOP,
        "Coop Supermarché": COOP,
        "Coop Supermercato": COOP,
        "Coop City": COOP_CITY,
        "Interdiscount": INTERDISCOUNT,
        "JUMBO": JUMBO,
    }

    async def start(self) -> AsyncIterator[JsonRequest]:
        yield JsonRequest(
            url="https://www.jumbo.ch/rest/v2/jumbo/stores?latitude=46.8&longitude=8.2&radius=500000&pageSize=1000&fields=stores(address(FULL),displayName,name,geoPoint,openingHours(FULL),features)",
        )

    def parse(self, response: Response) -> Iterable[Feature]:
        for store in response.json().get("stores", []):
            display_name = store.get("displayName", "")

            brand_info = None
            for prefix, info in self.BRAND_MAPPING.items():
                if display_name.startswith(prefix):
                    brand_info = info
                    break

            if not brand_info:
                continue

            store["ref"] = store.pop("name")
            store["lat"] = store.get("geoPoint", {}).get("latitude")
            store["lon"] = store.get("geoPoint", {}).get("longitude")

            if address := store.get("address"):
                address["street"] = address.pop("line1", None)
                address["house-number"] = address.pop("line2", None)
                store["country"] = address.get("country", {}).get("isocode")
                store["phone"] = address.get("phone")

            item = DictParser.parse(store)

            item["brand"] = brand_info["brand"]
            item["brand_wikidata"] = brand_info["brand_wikidata"]

            branch = display_name
            for prefix in self.BRAND_MAPPING.keys():
                if branch.startswith(prefix):
                    branch = branch.removeprefix(prefix).strip()
                    break
            item["branch"] = branch

            slug = self._slug(display_name)
            ref_num = item["ref"].removesuffix("_POS") if item["ref"] else ""
            item["website"] = brand_info["website"].format(slug=slug, ref=item["ref"], ref_num=ref_num)

            item["opening_hours"] = self.parse_hours(store.get("openingHours", {}))

            self.parse_features(item, store.get("features", {}))

            apply_category(brand_info["category"], item)

            yield item

    @staticmethod
    def parse_features(item: Feature, features: dict) -> None:
        feature_keys = {entry["key"] for entry in features.get("entry", [])}

        # Wheelchair accessibility
        wheelchair_features = {"293", "294", "295", "296", "297"}
        has_wheelchair = bool(wheelchair_features & feature_keys)
        apply_yes_no(Extras.WHEELCHAIR, item, has_wheelchair)

        # Wheelchair accessible toilets (key 297)
        apply_yes_no(Extras.TOILETS_WHEELCHAIR, item, "297" in feature_keys)

        # Self checkout (key 98)
        apply_yes_no(Extras.SELF_CHECKOUT, item, "98" in feature_keys)

        # Parcel pickup / Pick-up Station (key 153)
        apply_yes_no(Extras.PARCEL_PICKUP, item, "153" in feature_keys)

        # ATM / Bargeldbezug (key 298)
        apply_yes_no(Extras.ATM, item, "298" in feature_keys)

    @staticmethod
    def _slug(name: str) -> str:
        return (
            name.lower()
            .replace(" ", "-")
            .replace("ä", "a")
            .replace("ö", "o")
            .replace("ü", "u")
            .replace("é", "e")
            .replace("è", "e")
        )

    @staticmethod
    def parse_hours(opening_hours: dict) -> OpeningHours:
        oh = OpeningHours()
        for day_hours in opening_hours.get("weekDayOpeningList", []):
            if day_hours.get("closed"):
                continue
            day_name = day_hours.get("weekDay", "").rstrip(".")
            day = DAYS_DE.get(day_name)
            if not day:
                continue
            open_time = day_hours.get("openingTime", {}).get("formattedHour")
            close_time = day_hours.get("closingTime", {}).get("formattedHour")
            if open_time and close_time:
                oh.add_range(day, open_time, close_time)
        return oh
