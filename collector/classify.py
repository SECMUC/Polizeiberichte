"""Regelbasierte Einordnung (abgeleitet, nicht Teil der Polizeimeldung).

Die Kategorie wird primär aus der Überschrift bestimmt, weil die Polizei dort
den Sachverhalt selbst benennt. Nur wenn die Überschrift keinen Treffer liefert,
wird der Text herangezogen. Schweregrad: 3 = hoch, 2 = mittel, 1 = niedrig.
"""
import re

# (Kategorie, Schweregrad, Muster) – Reihenfolge = Priorität
RULES = [
    ("Tötungsdelikt", 3, r"tötungsdelikt|\bmord|totschlag|mordkommission|getötet|leblos aufgefunden|tot aufgefunden"),
    ("Sexualdelikt", 3, r"vergewaltig|sexuelle[rn]? (nötigung|übergriff|missbrauch)|missbrauch von kindern"),
    ("Raub", 3, r"bewaffnete[rn]? raub|unter vorhalt (einer|eines) (schusswaffe|messers|waffe)|schwere[rn]? raub"),
    ("Körperverletzung", 3, r"messerangriff|messerstich|stichverletzung|niedergestochen|schwere körperverletzung|lebensgefährlich verletzt"),
    ("Branddelikt", 3, r"schwere brandstiftung|brandanschlag"),
    ("Staatsschutz", 3, r"staatsschutz|extremis|volksverhetzung|verfassungsfeindlich|hakenkreuz"),
    ("Bedrohungslage", 3, r"amok|bombendrohung|bedrohungslage|geiselnahme|schussabgabe|schüsse"),
    ("Raub", 2, r"\braub(?!tier)|räuberisch|beraubt|entrissen|erpressung|überfall"),
    ("Bedrohung", 2, r"bedrohung|bedroht"),
    ("Widerstand/Angriff auf Beamte", 2, r"widerstand|tätliche[rn]? angriff|angriff auf (polizei|einsatz|rettung)"),
    ("Körperverletzung", 2, r"körperverletzung|schlägerei|geschlagen|getreten|faustschlag|\bangriff|angegriffen"),
    ("Sexualdelikt", 2, r"sexuelle belästigung|exhibitionist|unsittlich"),
    ("Einbruch", 2, r"einbruch|einbrüch|eingebrochen|einbrecher|aufgehebelt|aufgebrochen"),
    ("Branddelikt", 2, r"brandstiftung|\bbrand(?!enburg)|brandfall|feuer|flammen"),
    ("Betrug", 2, r"callcenterbetrug|schockanruf|enkeltrick|falsche[rn]? polizist|trickbetrug|betrug|betrüger|phishing"),
    ("Vermisstenfall", 2, r"vermisst|vermisstenfall|abgängig"),
    ("Fahndung", 2, r"öffentlichkeitsfahndung|fahndung|haftbefehl"),
    ("Drogen", 2, r"kokain|heroin|amphetamin|crystal|drogenhandel|rauschgift|betäubungsmittel|marihuana|cannabis"),
    ("Waffen", 2, r"waffengesetz|schusswaffe|schreckschuss|messer"),
    ("Unfall (kein Verkehr)", 2, r"arbeitsunfall|badeunfall|bergunfall|kletterunfall|skiunfall|freizeitunfall|badeunglück|ertrunken"),
    ("Verkehr", 2, r"tödlicher? (verkehrs)?unfall|rettungshubschrauber|schwer verletzt"),
    ("Todesfall", 2, r"\btot\b.*(geborgen|aufgefunden)|leichenfund|todesermittlung"),
    ("Diebstahl", 1, r"diebstahl|gestohlen|entwendet|dieb"),
    ("Verkehr", 1, r"verkehrsunfall|unfall|unfallflucht|fahrerflucht|trunkenheit|alkoholfahrt|kollision|zusammenstoß|verkehrskontrolle|rotlicht|straßenverkehr|fahrerlaubnis|pedelec|e-scooter|kraftrad|\bpkw\b"),
    ("Sachbeschädigung", 1, r"sachbeschädigung|graffiti|beschmiert|beschädigt"),
    ("Versammlung", 1, r"versammlung|demonstration|kundgebung"),
    ("Prävention/Hinweis", 1, r"prävention|warnt|warnung|terminhinweis|mobile wache|hinweis der polizei|infoveranstaltung"),
    ("Personal/Organisation", 1, r"amtswechsel|übernimmt .*leitung|neuer leiter|neue leiterin|verabschied"),
]
_COMPILED = [(k, s, re.compile(p, re.I)) for k, s, p in RULES]


def categorize(titel: str, text: str):
    for source in (titel or "", (text or "")[:600]):
        for kat, sev, rx in _COMPILED:
            if rx.search(source):
                return kat, sev
    return "Sonstiges", 1
