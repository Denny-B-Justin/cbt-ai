"""Keyword lists behind the keyword check (the Rio and EU Taxonomy vocabularies)."""

# Rio Markers ---------------------------------------------------------------
RIO_MITIGATION = [
    "renewable", "solar", "wind", "hydro", "energy efficiency", "low carbon", "electric vehicle", "ev charging",
    "charging infrastructure", "emission reduction", "decarbonization", "decarbonisation", "green hydrogen",
    "battery storage", "carbon capture", "clean energy", "renewable energy", "carbon offset", "carbon neutral",
    "net zero", "bioenergy", "geothermal", "biomass", "energy transition", "energy retrofits", "insulation",
    "heat pump", "smart grid", "energy storage",
]

RIO_ADAPTATION = [
    "flood", "flood control", "flood protection", "flood defense", "flood wall", "levee", "drought",
    "climate resilient", "resilience", "resilient", "climate resilience", "climate proof", "storm water",
    "coastal protection", "coastline protection", "sea level rise", "coastal erosion", "early warning system",
    "early warning", "heatwave", "heat wave", "heat stress", "disaster risk reduction", "disaster prevention",
    "climate adaptation", "adaptation measure", "water management", "irrigation", "water conservation",
    "agricultural resilience", "ecosystem restoration", "reforestation", "afforestation", "mangrove restoration",
]

RIO_EXPLICIT = [
    "climate change", "global warming", "mitigation", "adaptation", "paris agreement", "ndc",
    "nationally determined contribution", "climate action", "climate policy", "climate finance", "climate fund",
    "greenhouse gas", "ghg", "co2", "carbon emission", "climate target",
]

EXCLUSION = [
    "general administration", "office equipment", "office supplies", "salary", "pension", "personnel costs",
    "debt service", "interest payment", "legal services", "audit services", "routine maintenance",
    "general operations", "administrative overhead",
]

# EU Taxonomy ---------------------------------------------------------------
EU_KEYWORDS = {
    "mitigation": [
        "renewable energy", "solar", "wind", "hydroelectric", "geothermal", "biomass", "energy efficiency",
        "insulation", "led lighting", "smart grid", "electric vehicle", "ev charging", "public transport",
        "railway", "metro", "tram", "bicycle", "cycling", "carbon capture", "afforestation", "reforestation",
        "low carbon", "decarbonization", "methane reduction", "green hydrogen",
    ],
    "adaptation": [
        "climate resilience", "climate adaptation", "flood defense", "flood protection", "sea wall", "storm surge",
        "early warning system", "drought resilience", "water conservation", "irrigation efficiency",
        "crop diversification", "heatwave management", "urban cooling", "green roof", "permeable pavement",
        "disaster risk reduction", "resilient infrastructure", "coastal protection",
    ],
    "water": [
        "water treatment", "wastewater", "sewage", "water quality", "desalination", "marine protection",
        "ocean conservation", "aquatic ecosystem", "river restoration", "wetland", "water efficiency",
        "leak detection", "sustainable fishing", "aquaculture", "coastal management", "groundwater",
    ],
    "circular_economy": [
        "circular economy", "recycling", "waste management", "waste reduction", "composting", "refurbishment",
        "remanufacturing", "resource efficiency", "upcycling", "extended producer responsibility", "zero waste",
        "bio-based materials", "sustainable packaging", "product longevity", "shared economy",
    ],
    "pollution": [
        "pollution control", "air quality", "emissions reduction", "noise reduction", "decontamination",
        "soil remediation", "hazardous waste", "industrial emissions", "chemical safety", "plastic pollution",
        "pesticide reduction", "clean air", "smog", "particulate matter", "voc reduction",
    ],
    "biodiversity": [
        "biodiversity", "ecosystem restoration", "nature reserve", "national park", "wildlife conservation",
        "habitat protection", "forest management", "tree planting", "pollinator", "invasive species",
        "protected area", "ecological corridor", "soils health", "organic farming", "permaculture",
        "natural capital",
    ],
}

EU_BROWN = [
    "fossil fuel", "coal", "oil extraction", "natural gas", "crude oil", "thermal power", "gasoline", "diesel",
    "aviation fuel", "heavy industry", "deforestation", "mining", "quarrying", "plastic production",
    "cement production", "petrochemical", "incineration", "landfill", "industrial pollution",
]
