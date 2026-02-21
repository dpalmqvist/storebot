import json
import logging
import re
from enum import StrEnum

import requests

from storebot.retry import retry_on_transient

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.blocket.se/recommerce/forsale/search/api/search/SEARCH_ID_BAP_COMMON"
AD_HTML_URL = "https://www.blocket.se/recommerce/forsale/item/{ad_id}"

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

_HYDRATION_RE = re.compile(
    r'window\.__staticRouterHydrationData\s*=\s*JSON\.parse\("((?:[^"\\]|\\.)*)"\)',
)


class SortOrder(StrEnum):
    RELEVANCE = "RELEVANCE"
    PRICE_DESC = "PRICE_DESC"
    PRICE_ASC = "PRICE_ASC"
    PUBLISHED_DESC = "PUBLISHED_DESC"
    PUBLISHED_ASC = "PUBLISHED_ASC"


class Category(StrEnum):
    AFFARSVERKSAMHET = "0.91"
    DJUR_OCH_TILLBEHOR = "0.77"
    ELEKTRONIK_OCH_VITVAROR = "0.93"
    FORDONSTILLBEHOR = "0.90"
    FRITID_HOBBY_OCH_UNDERHALLNING = "0.86"
    FORALDRAR_OCH_BARN = "0.68"
    KLADER_KOSMETIKA_OCH_ACCESSOARER = "0.71"
    KONST_OCH_ANTIKT = "0.76"
    MOBLER_OCH_INREDNING = "0.78"
    SPORT_OCH_FRITID = "0.69"
    TRADGARD_OCH_RENOVERING = "0.67"


class SubCategory(StrEnum):
    BUTIK_OCH_DETALJHANDEL = "1.91.3108"
    CONTAINRAR_OCH_BARACKER = "1.91.3111"
    DOMANER_OCH_SAJTER = "1.91.3106"
    HALSA_OCH_FORSTA_HJALPEN = "1.91.8343"
    JORDBRUK = "1.91.3114"
    KONTORSUTRUSTNING_OCH_INREDNING = "1.91.3105"
    LAST_OCH_TRANSPORT = "1.91.3113"
    MASKINUTRUSTNING_OCH_RESERVDELAR = "1.91.3112"
    SCEN = "1.91.3110"
    STORKOK_OCH_RESTAURANG = "1.91.3103"
    VERKSTAD_BYGG_OCH_KONSTRUKTION = "1.91.3102"
    BILDELAR_OCH_TILLBEHOR = "1.90.82"
    HUSVAGNS_OCH_HUSBILSDELAR = "1.90.70"
    SLAP_OCH_TRAILER = "1.90.80"
    BATDELAR_OCH_TILLBEHOR = "1.90.30"
    AKVARIUM = "1.77.3976"
    BURAR = "1.77.3977"
    FISKAR = "1.77.5206"
    FODER_DJURVARD_KENNLAR_OCH_STALL = "1.77.5186"
    FAGLAR = "1.77.5205"
    GNAGARE_OCH_KANINER = "1.77.5207"
    HUNDAR = "1.77.5192"
    HUNDTILLBEHOR = "1.77.5193"
    HAST_OCH_RIDUTRUSTNING = "1.77.5195"
    HASTAR = "1.77.5190"
    KATTER = "1.77.5191"
    KATTILLBEHOR = "1.77.5194"
    LANTBRUKSDJUR = "1.77.9439"
    REPTILER = "1.77.5210"
    SPINDLAR_OCH_INSEKTER = "1.77.5208"
    OVRIGA_DJUR = "1.77.5183"
    OVRIGA_DJURTILLBEHOR = "1.77.5185"
    DATORER = "1.93.3215"
    FOTO_OCH_VIDEO = "1.93.3904"
    HUSHALLSAPPARATER = "1.93.3216"
    LJUD_OCH_BILD = "1.93.3906"
    PERSONVARD = "1.93.9809"
    TELEFONER_OCH_TILLBEHOR = "1.93.3217"
    TV_SPEL_OCH_SPELKONSOLER = "1.93.3905"
    VITVAROR = "1.93.3907"
    ATV_RESERVDELAR = "1.90.3975"
    MC_UTRUSTNING_OCH_RESERVDELAR = "1.90.20"
    BILJETTER_OCH_RESOR = "1.86.7735"
    BOCKER_OCH_TIDNINGAR = "1.86.5209"
    HANTVERK = "1.86.7734"
    MAT_OCH_DRYCK = "1.86.3972"
    MODELLER_OCH_BYGGSATSER = "1.86.7732"
    MUSIK_OCH_FILM = "1.86.3922"
    MUSIKINSTRUMENT = "1.86.92"
    RADIOSTYRDA_ENHETER = "1.86.7733"
    SAMLAROBJEKT = "1.86.285"
    SALLSKAPS_OCH_BRADSPEL = "1.86.5203"
    BARNBOCKER = "1.68.8369"
    BARNKLADER = "1.68.3913"
    BARNMOBLER = "1.68.3916"
    BARNSKOR = "1.68.3915"
    BARNTILLBEHOR_OCH_SAKERHET = "1.68.3918"
    BARNVAGNAR = "1.68.3914"
    BILBARNSTOLAR_OCH_BABYSKYDD = "1.68.3911"
    GRAVIDKLADER = "1.68.3948"
    INREDNING_TILL_BARNRUM = "1.68.9445"
    LEKSAKER = "1.68.3912"
    ACCESSOARER = "1.71.9481"
    DAMKLADER = "1.71.3941"
    GLASOGON_OCH_SOLGLASOGON = "1.71.8344"
    HERRKLADER = "1.71.3950"
    HUD_HAR_OCH_KROPPSVARD = "1.71.8280"
    KLOCKOR_OCH_ARMBANDSUR = "1.71.3945"
    KOSMETIK = "1.71.8282"
    MASKERADKLADER = "1.71.8349"
    SKOR = "1.71.3949"
    SMYCKEN_OCH_SMYCKESFORVARING = "1.71.7748"
    VASKOR_OCH_PLANBOCKER = "1.71.3946"
    ANTIKA_MOBLER = "1.76.5178"
    KERAMIK_PORSLIN_OCH_GLAS = "1.76.5176"
    KONST = "1.76.5177"
    SILVERFOREMAL_OCH_SILVERBESTICK = "1.76.5179"
    OVRIGA_ANTIKVITETER = "1.76.5175"
    BORD_OCH_STOLAR = "1.78.5196"
    DEKORATION_OCH_PRYDNADER = "1.78.5222"
    GARDEROBER_OCH_FORVARING = "1.78.5198"
    HYLLOR_OCH_BYRAER = "1.78.8345"
    KOKSUTRUSTNING_OCH_PORSLIN = "1.78.5223"
    LAMPOR = "1.78.5181"
    MATTOR_OCH_TEXTILIER = "1.78.5180"
    PYNT_TILL_HOGTIDER_OCH_FEST = "1.78.9760"
    SOFFOR_OCH_FATOLJER = "1.78.7756"
    SANGAR_OCH_MADRASSER = "1.78.5197"
    OVRIGA_MOBLER_OCH_INREDNING = "1.78.3971"
    BOLLSPORTER = "1.69.3961"
    CYKEL = "1.69.3963"
    EXTREMSPORT = "1.69.3938"
    GOLF = "1.69.5164"
    JAKT_FISKE_OCH_CAMPING = "1.69.3964"
    KOSTTILLSKOTT = "1.69.8281"
    RULLSKRIDSKOR_ISHOCKEY_OCH_KONSTAKNING = "1.69.8346"
    SKYTTE = "1.69.3965"
    SUPPORTERPRODUKTER = "1.69.3937"
    TRANINGSKLOCKOR_OCH_AKTIVITETSARMBAND = "1.69.3967"
    TRANINGSKLADER_OCH_SKOR = "1.69.3940"
    TRANINGSUTRUSTNING = "1.69.5166"
    VATTENSPORT = "1.69.7738"
    VINTERSPORT = "1.69.3962"
    OVRIGA_SPORTER = "1.69.3966"
    BADRUM_OCH_BASTU = "1.67.7749"
    BYGGMATERIAL_OCH_RENOVERING = "1.67.3899"
    GARAGEDELAR_OCH_TILLBEHOR = "1.67.8348"
    KOKSINREDNING_OCH_KOKSSTOMMAR = "1.67.3900"
    LARM_OCH_SAKERHET = "1.67.8347"
    TRADGARD_OCH_UTEMILJO = "1.67.3901"
    UTRUSTNING_FOR_FRITIDSHUS = "1.67.3968"
    VERKTYG = "1.67.5219"
    VARME_OCH_VENTILATION = "1.67.5218"
    OVRIGT = "1.67.3969"


class Location(StrEnum):
    BLEKINGE = "0.300010"
    DALARNA = "0.300020"
    GOTLAND = "0.300009"
    GAVLEBORG = "0.300021"
    HALLAND = "0.300013"
    JAMTLAND = "0.300023"
    JONKOPING = "0.300006"
    KALMAR = "0.300008"
    KRONOBERG = "0.300007"
    NORRBOTTEN = "0.300025"
    SKANE = "0.300012"
    STOCKHOLM = "0.300001"
    SODERMANLAND = "0.300004"
    UPPSALA = "0.300003"
    VARMLAND = "0.300017"
    VASTERBOTTEN = "0.300024"
    VASTERNORRLAND = "0.300022"
    VASTMANLAND = "0.300019"
    VASTRA_GOTALAND = "0.300014"
    OREBRO = "0.300018"
    OSTERGOTLAND = "0.300005"


def _extract_hydration_data(html: str) -> dict | None:
    """Extract item data from the __staticRouterHydrationData JSON blob."""
    match = _HYDRATION_RE.search(html)
    if not match:
        return None
    try:
        raw = match.group(1)
        decoded = raw.encode("utf-8").decode("unicode_escape")
        data = json.loads(decoded.encode("latin1").decode("utf-8"))
        return data["loaderData"]["item-recommerce"]["itemData"]
    except Exception:
        logger.debug("Failed to parse hydration data", exc_info=True)
        return None


def _parse_hydration_item(data: dict, ad_id: str) -> dict:
    """Map hydration itemData fields to our standard ad detail format."""
    meta = data.get("meta") or {}
    images = data.get("images") or []
    location = data.get("location") or {}
    category = data.get("category") or {}
    extras = data.get("extras") or []

    return {
        "id": str(meta.get("adId", ad_id)),
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "price": data.get("price", 0),
        "currency": "SEK",
        "url": AD_HTML_URL.format(ad_id=meta.get("adId", ad_id)),
        "images": [img.get("uri", "") for img in images if img.get("uri")],
        "location": location.get("postalName", ""),
        "category": category.get("value", ""),
        "seller": {"name": "", "id": ""},
        "parameters": {e.get("label", ""): e.get("value", "") for e in extras if e.get("label")},
        "published": meta.get("edited"),
    }


class BlocketClient:
    """Client for Blocket's unofficial REST API.

    Read-only — useful for price research and sourcing.
    No authentication required.
    """

    @staticmethod
    def _headers() -> dict:
        return {"User-Agent": USER_AGENT}

    @retry_on_transient()
    def _get(self, url: str, headers: dict, params: dict | None = None) -> requests.Response:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code >= 500:
            raise requests.HTTPError(response=resp)
        return resp

    @staticmethod
    def _parse_item(doc: dict) -> dict:
        price_obj = doc.get("price") or {}
        image_obj = doc.get("image") or {}
        return {
            "id": str(doc.get("ad_id", doc.get("id", ""))),
            "title": doc.get("heading", ""),
            "price": price_obj.get("amount", 0),
            "currency": price_obj.get("currency_code", "SEK"),
            "url": doc.get("canonical_url", ""),
            "image_url": image_obj.get("url", ""),
            "location": doc.get("location", ""),
            "published": doc.get("timestamp"),
            "trade_type": doc.get("trade_type", ""),
        }

    def search(
        self,
        query: str,
        category: str | None = None,
        region: str | None = None,
        page: int = 1,
        sort: str = "PUBLISHED_DESC",
        price_from: int | None = None,
        price_to: int | None = None,
    ) -> dict:
        try:
            params: dict = {"q": query, "page": page, "sort": sort}
            if category:
                params["category"] = category
            if region:
                params["location"] = region
            if price_from is not None:
                params["price_from"] = price_from
            if price_to is not None:
                params["price_to"] = price_to

            resp = self._get(SEARCH_URL, self._headers(), params=params)
            resp.raise_for_status()
            data = resp.json()

            metadata = data.get("metadata") or {}
            result_size = metadata.get("result_size") or {}
            total = result_size.get("match_count", 0)
            paging = metadata.get("paging") or {}

            docs = data.get("docs") or []

            return {
                "total": total,
                "page": paging.get("current", page),
                "total_pages": paging.get("last", 1),
                "items": [self._parse_item(doc) for doc in docs],
            }

        except Exception as e:
            logger.exception("Blocket search failed")
            return {"error": str(e), "total": 0, "items": []}

    def get_ad(self, ad_id: str) -> dict:
        """Fetch full details for a single Blocket ad via HTML scraping."""
        try:
            resp = self._get(AD_HTML_URL.format(ad_id=ad_id), self._headers())

            if resp.status_code == 404:
                return {"error": f"Ad {ad_id} not found (404)"}

            resp.raise_for_status()

            item_data = _extract_hydration_data(resp.text)
            if item_data is None:
                return {"error": f"Could not extract data from ad {ad_id} page"}

            return _parse_hydration_item(item_data, ad_id)

        except Exception as e:
            logger.exception("Blocket get_ad failed for %s", ad_id)
            return {"error": str(e)}
