import httpx
import xml.etree.ElementTree as ET
def get_cbr_rates():
    try:
        response = httpx.get(
            "https://www.cbr.ru/"
            "scripts/XML_daily.asp",
            timeout=5,
            follow_redirects=True
        )

        response.raise_for_status()

        root = ET.fromstring(
            response.content
        )

        rates = {}

        for valute in root.findall(
            "Valute"
        ):
            code = valute.findtext(
                "CharCode"
            )

            if code not in {
                "USD",
                "EUR"
            }:
                continue

            nominal = float(
                valute.findtext(
                    "Nominal"
                ).replace(",", ".")
            )

            value = float(
                valute.findtext(
                    "Value"
                ).replace(",", ".")
            )

            rates[code] = (
                value / nominal
            )

        return rates

    except Exception as exc:
        print(
            "CBR error:",
            exc
        )

        try:
            response = httpx.get('https://www.cbr-xml-daily.ru/daily_json.js',timeout=10)
            response.raise_for_status()
            data = response.json()['Valute']
            return {code: float(data[code]['Value'])/float(data[code]['Nominal']) for code in ('USD','EUR')}
        except Exception as fallback:
            print('CBR mirror unavailable:',type(fallback).__name__)
            return {}


def get_crypto_rates():
    try:
        response = httpx.get(
            (
                "https://api.coingecko.com/"
                "api/v3/simple/price"
            ),
            params={
                "ids": "bitcoin,ethereum",
                "vs_currencies": "usd",
            },
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        return {
            "BTC": (
                data
                .get("bitcoin", {})
                .get("usd")
            ),
            "ETH": (
                data
                .get("ethereum", {})
                .get("usd")
            ),
        }

    except Exception as exc:
        print(
            "Crypto error:",
            exc
        )

        return {}


def format_money(value):
    if value is None:
        return None

    return (
        f"{value:,.0f}"
        .replace(",", " ")
    )


