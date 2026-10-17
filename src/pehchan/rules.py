"""Explicit keyword rules for narrative frames, topics and entities.

Shared by collection annotation and by investigation-time tagging of submitted claims, so both
sides of a graph-widening match use the same reviewable patterns. Matches are inferences, not
publisher markup, entity disambiguation or evidence of coordination.
"""

import re

from .records import normalize_text

I = re.IGNORECASE
FIVE_G = re.compile(r"5G", I)
COVID = re.compile(
    r"covid|corona|sars-cov|virus|vírus|コロナ|کرونا|pandemi|epidemi|महामारी|marburg|wuhan|వుహన్", I
)
CHIP = re.compile(r"micro[- ]?chip|\bchips?\b", I)
VACCINE = re.compile(r"vacc|vacun|vacin|vaksin|impf|cjepiv|ワクチン", I)
CLIMATE = re.compile(r"climate|global warming", I)
MOON = re.compile(r"moon landing", I)
DENIAL = re.compile(
    r"hoax|scam|fake|swindle|not real|not happening|no climate|not based on real science|"
    r"no long-term|no loss|does not cause harm|no impact|bull-",
    I,
)
NATURAL = re.compile(
    r"magnetic pole|pole shift|milankovitch|solar|orbit|sahara|is natural|little effect|not causing|not caused by humans",
    I,
)
MANIPULATION = re.compile(
    r"geoengineering|chem ?trails|weather modification|arson|sets their own forest fires", I
)
ELITE_PRETEXT = re.compile(
    r"slaughter|faeces|reduce population|euthaniz|mass vaccination|flight bans|destroy 75 million|"
    r"bad idea to have kids|not to have children|red meat",
    I,
)
HEALTH_HARM = re.compile(
    r"radiation|radiación|straling|strahlung|रेडिएशन|రేడియేషన్|schad|harmful|perjudicial|gesundheit|"
    r"birds?\b|vögel|vogels|pájaros|estorninos|பறவைகள்|murciélagos|hayvan|radioactiv|lethal|"
    r"kalcij|health|directed energy",
    I,
)
DESTRUCTION = re.compile(
    r"burn|brand|fire to|destroy|détruit|vernietig|vernielde|ontmanteling|verwijder|desmontan|"
    r"tumbar|tearing down|bans 5G|interdit|verbiedt|stopped the rollout",
    I,
)

FRAMES = (
    ("5G as a cause of coronavirus illness", lambda t: FIVE_G.search(t) and COVID.search(t)),
    ("Vaccination as microchip implantation", lambda t: CHIP.search(t) and VACCINE.search(t)),
    (
        "Biomedical technology as covert control",
        lambda t: (
            (CHIP.search(t) and not VACCINE.search(t))
            or re.search(r"brainwash|remotely control|tracked in real time|spied on", t, I)
        ),
    ),
    (
        "Moon landing as a staged event",
        lambda t: MOON.search(t) and re.search(r"hoax|fake|didn.t happen|filmed|cut scenes", t, I),
    ),
    ("Climate change as a fabricated deception", lambda t: CLIMATE.search(t) and DENIAL.search(t)),
    (
        "Climate change attributed to natural cycles",
        lambda t: CLIMATE.search(t) and NATURAL.search(t),
    ),
    (
        "Climate change attributed to deliberate manipulation",
        lambda t: CLIMATE.search(t) and MANIPULATION.search(t),
    ),
    (
        "Climate policy as a pretext for elite control",
        lambda t: CLIMATE.search(t) and ELITE_PRETEXT.search(t),
    ),
    ("5G infrastructure as a health hazard", lambda t: FIVE_G.search(t) and HEALTH_HARM.search(t)),
    (
        "Destruction or banning of 5G infrastructure",
        lambda t: FIVE_G.search(t) and DESTRUCTION.search(t),
    ),
)

TOPICS = (
    ("Vaccines", VACCINE),
    ("5G", FIVE_G),
    ("Space", re.compile(r"moon|nasa|astronaut", I)),
    ("Climate", CLIMATE),
)

# (name, type, pattern). Case-sensitive patterns avoid matching common words such as "who".
ENTITIES = (
    ("5G", "Technology", FIVE_G),
    ("Microchip", "Technology", re.compile(r"micro[- ]?chip|\bchips?\b", I)),
    ("COVID-19", "Disease", re.compile(r"covid|coronavirus|corona|sars-cov-2|コロナ|کرونا", I)),
    ("Marburg virus", "Disease", re.compile(r"marburg", I)),
    ("Moon landing", "Event", MOON),
    (
        "Geoengineering",
        "Concept",
        re.compile(r"geoengineering|chem ?trails|weather modification", I),
    ),
    ("Milankovitch cycles", "Concept", re.compile(r"milankovitch", I)),
    ("Magnetic pole shift", "Concept", re.compile(r"magnetic poles?|pole shift", I)),
    ("Wildfire", "Event", re.compile(r"wildfires?|forest fires", I)),
    ("CBDC", "Technology", re.compile(r"cbdc|digital currency", I)),
    ("Birds", "Animal", re.compile(r"\bbirds?\b|vögel|vogels|pájaros|estorninos|பறவைகள்", I)),
    ("Bill Gates", "Person", re.compile(r"bill gates", I)),
    ("Gates Foundation", "Organization", re.compile(r"gates foundation", I)),
    ("World Economic Forum", "Organization", re.compile(r"world economic forum|\bWEF\b")),
    ("Klaus Schwab", "Person", re.compile(r"klaus schwab", I)),
    ("Yuval Noah Harari", "Person", re.compile(r"harari", I)),
    ("Ursula von der Leyen", "Person", re.compile(r"von der leyen", I)),
    ("World Health Organization", "Organization", re.compile(r"world health organization|\bOMS\b")),
    ("United Nations", "Organization", re.compile(r"united nations|\bUN\b")),
    ("NASA", "Organization", re.compile(r"\bNASA\b")),
    ("Buzz Aldrin", "Person", re.compile(r"buzz aldrin", I)),
    ("Richard Nixon", "Person", re.compile(r"nixon", I)),
    ("WikiLeaks", "Organization", re.compile(r"wikileaks", I)),
    ("Vladimir Putin", "Person", re.compile(r"putin|poutine|poetin", I)),
    ("Reliance Jio", "Organization", re.compile(r"\bjio\b", I)),
    ("Vodafone", "Organization", re.compile(r"vodafone", I)),
    ("Huawei", "Organization", re.compile(r"huawei", I)),
    ("Airtel", "Organization", re.compile(r"airtel", I)),
    ("Samsung", "Organization", re.compile(r"samsung", I)),
    ("Pfizer", "Organization", re.compile(r"pfizer", I)),
    ("AstraZeneca", "Organization", re.compile(r"astrazeneca", I)),
    ("Microsoft", "Organization", re.compile(r"microsoft", I)),
    ("Rockefeller", "Person", re.compile(r"rockefeller", I)),
    ("Kamala Harris", "Person", re.compile(r"kamala harris", I)),
    ("Joe Biden", "Person", re.compile(r"\bbiden\b", I)),
    ("Donald Trump", "Person", re.compile(r"\btrump\b", I)),
    ("JD Vance", "Person", re.compile(r"\bvance\b", I)),
    ("Ted Cruz", "Person", re.compile(r"ted cruz", I)),
    ("Greta Thunberg", "Person", re.compile(r"greta thunberg", I)),
    ("Hillary Clinton", "Person", re.compile(r"hillary clinton", I)),
    ("Pope Francis", "Person", re.compile(r"pope francis", I)),
    ("Judith Curry", "Person", re.compile(r"judith curry", I)),
    ("Ron Johnson", "Person", re.compile(r"ron johnson", I)),
    ("Nancy Mace", "Person", re.compile(r"nancy mace", I)),
    ("India", "Place", re.compile(r"\bindia\b|indian|gujarat|hindistan", I)),
    ("China", "Place", re.compile(r"\bchina\b|chinese|chinesa|\bçin\b|wuhan", I)),
    ("Peru", "Place", re.compile(r"\bper[uú]\b|peruaanse", I)),
    ("Croatia", "Place", re.compile(r"croatia|kroatien|kroatië|croacia", I)),
    ("Netherlands", "Place", re.compile(r"netherlands|\bNL\b")),
    ("Russia", "Place", re.compile(r"russia|russie|rusland", I)),
    ("Greenland", "Place", re.compile(r"greenland", I)),
    ("Canada", "Place", re.compile(r"canada", I)),
    ("Italy", "Place", re.compile(r"\bital(y|ia)\b", I)),
)


def tag(text: str) -> dict:
    """Return rule-matched frames, topics and entities (with spans copied from the text)."""
    normalized = normalize_text(text)
    entities = []
    for name, kind, pattern in ENTITIES:
        match = pattern.search(text)
        if match and normalize_text(match.group(0)) in normalized:
            entities.append({"name": name, "type": kind, "evidence_span": match.group(0)})
    return {
        "frames": [name for name, rule in FRAMES if rule(text)],
        "topics": [name for name, pattern in TOPICS if pattern.search(text)],
        "entities": entities,
    }
