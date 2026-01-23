import scrapy

from locations.categories import (
    Access,
    Categories,
    Extras,
    Fuel,
    FuelCards,
    PaymentMethods,
    apply_category,
    apply_yes_no,
    map_payment,
)
from locations.dict_parser import DictParser
from locations.hours import OpeningHours

AVIA_SHARED_ATTRIBUTES = {
    "brand": "Avia",
    "brand_wikidata": "Q300147",
}

FUEL_TYPES_MAPPING = {
    "AdBlue (Gebinde)": Fuel.ADBLUE,
    "AdBlue Säule (LKW)": Fuel.ADBLUE,
    "AdBlue Säule (PKW)": Fuel.ADBLUE,
    "Blue Diesel": Fuel.DIESEL,
    "CNG/Erdgas": Fuel.CNG,
    "Diesel": Fuel.DIESEL,
    "LKW-Diesel": Fuel.HGV_DIESEL,
    "LPG/Autogas": Fuel.LPG,
    "Stromladesäule": Fuel.ELECTRIC,
    "Super E10": Fuel.E10,
    "Super E5": Fuel.E5,
    "Super Plus": Fuel.OCTANE_98,
}

SERVICES_MAPPING = {
    "Anhängervermietung": None,
    "Backshop": None,
    "Bistro": Extras.FAST_FOOD,
    "Dusche": Extras.SHOWERS,
    "Erdgas": None,
    "Geldautomat": Extras.ATM,
    "Getränkemarkt": None,
    "LKW-Hochleistungssäule": Access.HGV,
    "LOTTO": None,
    "Portalwaschanlage": Extras.CAR_WASH,
    "Prima Bistro": Extras.FAST_FOOD,
    "Reinigungsannahme": None,
    "SB-Sauger": Extras.VACUUM_CLEANER,
    "SB-Waschbox": None,
    "SB-Öltheke": None,
    "Segafredo Kaffee": None,
    "Shop": "shop",
    "Stromladesäule": Fuel.ELECTRIC,
    "Tankautomat": "automated",
    "TÜV / AU": None,
    "Unbemannte Automatenstation": None,
    "Waschstrasse": Extras.CAR_WASH,
    "Werkstatt": None,
}


class AviaDESpider(scrapy.Spider):
    name = "avia_de"
    allowed_domains = ["www.avia.de"]
    start_urls = ["https://www.avia.de/index.php?eID=tsfindergetdata&datatype=allstations"]
    BRANDS_MAPPING = {
        "AVIA Automatentankstelle": AVIA_SHARED_ATTRIBUTES,
        "AVIA Tankstelle": AVIA_SHARED_ATTRIBUTES,
        "AVIA Truck": AVIA_SHARED_ATTRIBUTES,
        "AVIA XPress": AVIA_SHARED_ATTRIBUTES,
        "tankpoint Tankstelle": {"brand": "tankpoint"},
    }

    def parse(self, response):
        def extract_labels(d):
            return [v.get("label") for v in d.values()] if d else []

        for poi in response.json().values():
            poi.update(poi.pop("addressData"))
            poi.update(poi.pop("contactData"))
            poi.update(poi.pop("geoData"))
            item = DictParser.parse(poi)
            item.update(self.BRANDS_MAPPING.get(poi.get("facilityTitle"), {}))

            payments = extract_labels(poi.get("optionalData", {}).get("paymentMethods"))
            fuel_cards = extract_labels(poi.get("optionalData", {}).get("fuelCards", {}))
            gas_types = extract_labels(poi.get("optionalData", {}).get("gasTypes", {}))
            services = extract_labels(poi.get("optionalData", {}).get("services", {}))

            for payment in payments:
                if not map_payment(item, payment, PaymentMethods):
                    self.crawler.stats.inc_value(f"atp/avia_de/payment/fail/{payment}")

            for fuel_card in fuel_cards:
                if not map_payment(item, fuel_card, FuelCards):
                    self.crawler.stats.inc_value(f"atp/avia_de/fuelCard/fail/{fuel_card}")

            self.parse_attribute(item, gas_types, "gasTypes", FUEL_TYPES_MAPPING)
            self.parse_attribute(item, services, "services", SERVICES_MAPPING)

            apply_category(Categories.FUEL_STATION, item)

            item["opening_hours"] = self.parse_opening_hours(poi)

            yield item

    def parse_attribute(self, item, values: list, attribute_name, mapping: dict):
        for value in values:
            if tag := mapping.get(value):
                apply_yes_no(tag, item, True)
            else:
                self.crawler.stats.inc_value(f"atp/avia_de/{attribute_name}/fail/{value}")

    def parse_opening_hours(self, poi: dict) -> OpeningHours | None:
        try:
            detail = poi["optionalData"]["openingHours"]["tanken"]["oeffnungszeit"]["detail"]
            oh = OpeningHours()
            for day, info in detail.items():
                oh.add_range(day, info["detail"]["from"], info["detail"]["to"])
            return oh
        except (KeyError, TypeError, AttributeError):
            return None
