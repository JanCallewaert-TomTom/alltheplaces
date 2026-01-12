from typing import Any, AsyncIterator, Iterable

from scrapy import Request, Spider
from scrapy.http import FormRequest, JsonRequest, Response

from locations.categories import Categories, Extras, apply_category, apply_yes_no
from locations.dict_parser import DictParser
from locations.hours import DAYS, OpeningHours
from locations.items import Feature
from locations.user_agents import BROWSER_DEFAULT


class IntermarcheSpider(Spider):
    name = "intermarche"
    allowed_domains = ["intermarche.com"]
    INTERMARCHE = {
        "brand": "Intermarché",
        "brand_wikidata": "Q3153200",
    }
    INTERMARCHE_SUPER = {
        "brand": "Intermarché Super",
        "brand_wikidata": "Q98278038",
    }
    INTERMARCHE_CONTACT = {
        "brand": "Intermarché Contact",
        "brand_wikidata": "Q98278049",
    }
    INTERMARCHE_EXPRESS = {
        "brand": "Intermarché Express",
        "brand_wikidata": "Q98278043",
    }
    INTERMARCHE_HYPER = {
        "brand": "Intermarché Hyper",
        "brand_wikidata": "Q98278022",
    }
    LA_POSTE_RELAIS = {
        "brand": "Pickup Station",
        "brand_wikidata": "Q110748562",
        "operator": "La Poste",
        "operator_wikidata": "Q373724",
    }

    item_attributes = {"country": "FR"}
    custom_settings = {"ROBOTSTXT_OBEY": False, "DOWNLOAD_TIMEOUT": 180, "USER_AGENT": BROWSER_DEFAULT}

    async def start(self) -> AsyncIterator[FormRequest]:
        # Fetch cookies to get rid of DataDome captcha blockage
        yield FormRequest(
            url="https://dt.intermarche.com/js/",
            headers={
                "referer": "https://www.intermarche.com/",
            },
            formdata={"ddk": "0571CF21385A163DDC74F0BEFBBAA0"},
        )

    def parse(self, response: Response, **kwargs: Any) -> Any:
        yield JsonRequest(
            url="https://www.intermarche.com/api/service/pdvs/v4/pdvs/zone?min=20000",
            headers={
                "referer": "https://www.intermarche.com/",
                "x-red-device": "red_fo_desktop",
                "x-red-version": "3",
                "x-service-name": "pdvs",
            },
            cookies={"cookie": response.json()["cookie"]},
            callback=self.parse_locations,
        )

    def parse_locations(self, response: Response, **kwargs: Any) -> Any:
        for place in response.json()["resultats"]:
            place["ref"] = place["entityCode"]

            if len(place.get("addresses", [])) > 0:
                place["address"] = place["addresses"][0]
                place["address"]["street_address"] = place["address"].pop("address")
                place["address"]["city"] = place["address"].pop("townLabel")
                if place["address"].get("latitude") and place["address"].get("longitude"):
                    place["longitude"] = place["address"].pop("longitude")
                    place["latitude"] = place["address"].pop("latitude")

            for contact in place.get("contacts", []):
                if contact.get("contactCode") == "telephone":
                    place["phone"] = contact.get("contactValue")
                    break

            item = DictParser.parse(place)

            slug = f'{item["ref"]}/{item["city"].replace(" ", "-")}-{item["postcode"]}/infos-pratiques'
            item["website"] = f"https://www.intermarche.com/magasins/{slug}"

            oh = OpeningHours()
            for rules in place["calendar"]["openingHours"]:
                if rules.get("startHours") and rules.get("endHours"):
                    for i, d in enumerate(rules["days"]):
                        if d == "1":
                            oh.add_range(DAYS[i], rules["startHours"], rules["endHours"])
            item["opening_hours"] = oh.as_opening_hours()

            apply_yes_no(Extras.ATM, item, any(s["code"] == "dis" for s in place["ecommerce"]["services"]), False)

            if place.get("modelLabel") in [
                "SUPER ALIMENTAIRE",
                "SUPER GENERALISTE",
            ]:
                item.update(self.INTERMARCHE_SUPER)
            elif place.get("modelLabel") == "CONTACT":
                item.update(self.INTERMARCHE_CONTACT)
            elif place.get("modelLabel") == "EXPRESS" or place.get("modelLabel") == "Intermarché Express":
                item.update(self.INTERMARCHE_EXPRESS)
            elif place.get("modelLabel") == "HYPER":
                item.update(self.INTERMARCHE_HYPER)
            elif place.get("modelLabel") == "Réservé Soignants":
                continue  # Drive through stores reserved for medical workers
            elif place.get("modelLabel") == "Retrait La Poste":
                item.update(self.LA_POSTE_RELAIS)
                apply_category(Categories.PARCEL_LOCKER, item)
                item["located_in"], item["located_in_wikidata"] = self.INTERMARCHE.values()
            elif place.get("modelLabel") == "Pro & Assos":
                # independent vape shop located in intermarche
                apply_category(Categories.SHOP_E_CIGARETTE, item)
                item["located_in"], item["located_in_wikidata"] = self.INTERMARCHE.values()

            # Handle fuel stations separately
            if any(s["code"] == "ess" for s in place["ecommerce"]["services"]):
                slug = f'{item["ref"]}/{item["city"].replace(" ", "-")}-{item["postcode"]}/infos-pratiques'
                detail_url = f"https://www.intermarche.com/magasins/{slug}"

                yield Request(
                    url=detail_url,
                    callback=self.parse_fuel_station,
                    cb_kwargs={"item": item}
                )

            # Other accessory units
            yield from self.parse_accessory_units(place, item)

            yield item

    def parse_accessory_units(self, place: dict, item: Feature) -> Iterable[Feature]:
        if any(s["code"] == "lav" for s in place["ecommerce"]["services"]):
            car_wash = item.deepcopy()
            car_wash["ref"] += "_carwash"
            car_wash.update(self.INTERMARCHE)

            apply_category(Categories.CAR_WASH, car_wash)

            yield car_wash

    def parse_fuel_station(self, response: Response, **kwargs) -> Iterable[Feature]:
        import json
        import re

        item = kwargs.get("item")
        self.logger.info(f"parse_fuel_station called for {item['ref']} from {response.url} (status: {response.status})")

        # Extract Next.js data from HTML
        match = re.search(r'"gasStationInformation":\{[^}]*"address":\{[^}]+\}', response.text)
        if match:
            self.logger.info(f"Found gasStationInformation for {item['ref']}")

            # Extract the full gasStationInformation object
            json_text = "{" + match.group() + "}"
            # Find the end of the object by counting braces
            brace_count = 0
            end_pos = 0
            for i, char in enumerate(json_text):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = i + 1
                        break

            json_text = json_text[:end_pos]
            data = json.loads(json_text)

            fuel = item.deepcopy()
            fuel["opening_hours"] = None
            fuel["ref"] += "_fuel"
            fuel.update(self.INTERMARCHE)

            # Use fuel station coordinates if available
            if "gasStationInformation" in data and "address" in data["gasStationInformation"]:
                fuel_address = data["gasStationInformation"]["address"]
                if fuel_address.get("latitude") and fuel_address.get("longitude"):
                    fuel["lat"] = fuel_address["latitude"]
                    fuel["lon"] = fuel_address["longitude"]

            apply_category(Categories.FUEL_STATION, fuel)
            yield fuel
