from app import countries


def iso3s(text):
    return [m.iso3 for m in countries.find_mentions(text)]


def test_resolve_accepts_every_identifier_the_agents_use():
    assert countries.resolve("IND") == "IND"
    assert countries.resolve("india") == "IND"
    assert countries.resolve(750) == "IND"          # Gleditsch-Ward (Policy Stance)
    assert countries.resolve("750") == "IND"
    assert countries.resolve("Russian Federation") == "RUS"  # BACI label (Trade)
    assert countries.resolve("Türkiye") == "TUR"
    assert countries.resolve("Turkiye") == "TUR"
    assert countries.resolve("TMP") == "TLS"         # CAMEO legacy code (Events)
    assert countries.resolve("nowhere") is None
    assert countries.resolve(None) is None


def test_gw_codes_follow_ucdp_not_the_mislabelled_policy_table():
    # The Policy Stance module originally labelled these codes with the wrong country.
    assert countries.GW_TO_ISO3[490] == "COD"
    assert countries.GW_TO_ISO3[501] == "KEN"
    assert countries.GW_TO_ISO3[530] == "ETH"
    assert countries.GW_TO_ISO3[712] == "MNG"
    assert countries.GW_TO_ISO3[260] == "DEU"


def test_gw_codes_are_unique():
    codes = [c.gw for c in countries.COUNTRIES.values() if c.gw is not None]
    assert len(codes) == len(set(codes))


def test_cameo_round_trip():
    assert countries.to_cameo("TLS") == "TMP"
    assert countries.to_cameo("IND") == "IND"
    assert countries.from_cameo("TMP") == "TLS"
    assert countries.from_cameo("NAN") is None       # GDELT's missing-code placeholder
    assert countries.from_cameo("EUR") is None       # CAMEO region codes are not countries


def test_longest_name_wins():
    assert iso3s("Nigeria and Niger") == ["NGA", "NER"]
    assert iso3s("South Korea trade") == ["KOR"]
    assert iso3s("North Korea sanctions") == ["PRK"]
    assert iso3s("Papua New Guinea") == ["PNG"]


def test_demonyms_and_capitals():
    assert iso3s("Chinese exports to Indian ports") == ["CHN", "IND"]
    assert iso3s("the Kremlin's view") == ["RUS"]


def test_us_is_a_country_only_in_upper_case():
    assert iso3s("tell us about Brazil") == ["BRA"]
    assert iso3s("US and China") == ["USA", "CHN"]


def test_regions_are_not_the_united_states():
    assert iso3s("Tell me about Latin America") == []
    assert iso3s("South American trade") == []
    assert iso3s("How do Americans see China?") == ["USA", "CHN"]


def test_upper_case_english_words_are_not_iso3():
    assert iso3s("CAN AND ARE") == []
    assert iso3s("Compare IND and CHN") == ["IND", "CHN"]


def test_each_country_reported_once_in_order():
    assert iso3s("India, China, then India again") == ["IND", "CHN"]
