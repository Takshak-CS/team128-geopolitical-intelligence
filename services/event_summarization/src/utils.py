import pandas as pd

COUNTRY_MAP = {
    "USA": "United States", "IND": "India", "ISR": "Israel", "JOR": "Jordan",
    "SYR": "Syria", "CYP": "Cyprus", "AUS": "Australia", "GBR": "United Kingdom",
    "FRA": "France", "DEU": "Germany", "RUS": "Russia", "CHN": "China",
    "JPN": "Japan", "CAN": "Canada", "BRA": "Brazil", "ZAF": "South Africa",
    "ARE": "UAE", "SAU": "Saudi Arabia", "IRN": "Iran", "IRQ": "Iraq",
    "AFG": "Afghanistan", "PAK": "Pakistan", "TUR": "Turkey", "UKR": "Ukraine",
    "ITA": "Italy", "ESP": "Spain", "NGA": "Nigeria", "EGY": "Egypt",
    "MYS": "Malaysia", "IDN": "Indonesia", "KOR": "South Korea", "PRK": "North Korea",
    "MEX": "Mexico", "ARG": "Argentina", "VEN": "Venezuela", "COL": "Colombia",
    "POL": "Poland", "NLD": "Netherlands", "SWE": "Sweden", "NOR": "Norway",
    "DNK": "Denmark", "FIN": "Finland", "CHE": "Switzerland", "AUT": "Austria",
    "BEL": "Belgium", "PRT": "Portugal", "GRC": "Greece", "HUN": "Hungary",
    "CZE": "Czech Republic", "ROU": "Romania", "BGR": "Bulgaria", "HRV": "Croatia",
    "SRB": "Serbia", "UZB": "Uzbekistan", "KAZ": "Kazakhstan", "THA": "Thailand",
    "VNM": "Vietnam", "PHL": "Philippines", "BGD": "Bangladesh", "LKA": "Sri Lanka",
    "NPL": "Nepal", "MMR": "Myanmar", "KEN": "Kenya", "ETH": "Ethiopia",
    "GHA": "Ghana", "TZA": "Tanzania", "SDN": "Sudan", "LBY": "Libya",
    "MAR": "Morocco", "TUN": "Tunisia", "DZA": "Algeria", "LBN": "Lebanon",
    "YEM": "Yemen", "OMN": "Oman", "QAT": "Qatar", "KWT": "Kuwait",
    "BHR": "Bahrain", "PSE": "Palestine", "SGP": "Singapore", "TWN": "Taiwan",
    "HKG": "Hong Kong", "NZL": "New Zealand", "ZWE": "Zimbabwe", "ZMB": "Zambia",
    "UGA": "Uganda", "CMR": "Cameroon", "CIV": "Ivory Coast", "SEN": "Senegal",
    "MLI": "Mali", "BFA": "Burkina Faso", "NER": "Niger", "TCD": "Chad",
    "SOM": "Somalia", "MOZ": "Mozambique", "MDG": "Madagascar", "AGO": "Angola",
    "COD": "DR Congo", "COG": "Rep. of Congo", "GAB": "Gabon",
    "CHL": "Chile", "PER": "Peru", "ECU": "Ecuador", "BOL": "Bolivia",
    "PRY": "Paraguay", "URY": "Uruguay", "GTM": "Guatemala", "HND": "Honduras",
    "SLV": "El Salvador", "NIC": "Nicaragua", "CRI": "Costa Rica", "PAN": "Panama",
    "CUB": "Cuba", "HTI": "Haiti", "DOM": "Dominican Republic", "JAM": "Jamaica",
    "TTO": "Trinidad and Tobago", "BLR": "Belarus", "MDA": "Moldova",
    "GEO": "Georgia", "ARM": "Armenia", "AZE": "Azerbaijan",
    "LTU": "Lithuania", "LVA": "Latvia", "EST": "Estonia",
    "SVK": "Slovakia", "SVN": "Slovenia", "MKD": "North Macedonia",
    "ALB": "Albania", "BIH": "Bosnia and Herzegovina", "MNE": "Montenegro",
    "MLT": "Malta", "LUX": "Luxembourg", "ISL": "Iceland",
    "MNG": "Mongolia", "KGZ": "Kyrgyzstan", "TJK": "Tajikistan", "TKM": "Turkmenistan",
}


def get_country_name(code: str) -> str:
    return COUNTRY_MAP.get(str(code).strip().upper(), code)


def normalize_country(name: str) -> str:
    return name.strip().upper()


def get_country_display_list(date: str) -> list:
    """
    Returns sorted 'CODE (Name)' strings for countries present in the GDELT CSV.
    GDELT V1 column layout (0-indexed, tab-separated, no header):
      Col  7 = Actor1CountryCode
      Col 17 = Actor2CountryCode
    Only returns countries that exist in COUNTRY_MAP (filters noise).
    """
    file_path = f"data/{date}.export.CSV"

    df = pd.read_csv(
        file_path,
        sep="\t",
        header=None,
        low_memory=False,
        usecols=[7, 17],
        dtype=str,
    )

    all_codes = (
        pd.concat([df[7].dropna(), df[17].dropna()])
        .str.strip().str.upper()
    )
    # Country codes are exactly 3 uppercase letters
    all_codes = all_codes[all_codes.str.match(r'^[A-Z]{3}$')].unique()

    display_list = []
    for code in sorted(all_codes):
        name = COUNTRY_MAP.get(code)
        if name is None:
            continue
        display_list.append(f"{code} ({name})")

    return display_list
