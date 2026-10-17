"""Regelbasierte Einordnung (abgeleitet, nicht Teil der Polizeimeldung).

Die Kategorie wird primär aus der Überschrift bestimmt, weil die Polizei dort
den Sachverhalt selbst benennt. Nur wenn die Überschrift keinen Treffer liefert,
wird der Text herangezogen. Es gibt bewusst keine Gewichtung oder Bewertung.
"""
import re

# (Delikt, Muster) – die Reihenfolge entscheidet nur, welche Regel bei mehreren Treffern greift
RULES = [
    ("Tötungsdelikt", r"tötungsdelikt|\bmord|totschlag|mordkommission|getötet|leblos aufgefunden|tot aufgefunden"),
    ("Sexualdelikt", r"vergewaltig|sexuelle[rn]? (nötigung|übergriff|missbrauch)|missbrauch von kindern"),
    ("Raub", r"bewaffnete[rn]? raub|unter vorhalt (einer|eines) (schusswaffe|messers|waffe)|schwere[rn]? raub"),
    ("Körperverletzung", r"messerangriff|messerstich|stichverletzung|niedergestochen|schwere körperverletzung|lebensgefährlich verletzt"),
    ("Branddelikt", r"schwere brandstiftung|brandanschlag"),
    ("Staatsschutz", r"staatsschutz|extremis|volksverhetzung|verfassungsfeindlich|hakenkreuz"),
    ("Bedrohungslage", r"amok|bombendrohung|bedrohungslage|geiselnahme|schussabgabe|schüsse"),
    ("Raub", r"\braub(?!tier)|räuberisch|beraubt|entrissen|erpressung|überfall"),
    ("Bedrohung", r"bedrohung|bedroht"),
    ("Widerstand/Angriff auf Beamte", r"widerstand|tätliche[rn]? angriff|angriff auf (polizei|einsatz|rettung)"),
    ("Körperverletzung", r"körperverletzung|schlägerei|geschlagen|getreten|faustschlag|\bangriff|angegriffen"),
    ("Sexualdelikt", r"sexuelle belästigung|exhibitionist|unsittlich"),
    ("Einbruch", r"einbruch|einbrüch|eingebrochen|einbrecher|aufgehebelt|aufgebrochen"),
    ("Branddelikt", r"brandstiftung|\bbrand(?!enburg)|brandfall|feuer|flammen"),
    ("Betrug", r"callcenterbetrug|schockanruf|enkeltrick|falsche[rn]? polizist|trickbetrug|betrug|betrüger|phishing"),
    ("Vermisstenfall", r"vermisst|vermisstenfall|abgängig"),
    ("Fahndung", r"öffentlichkeitsfahndung|fahndung|haftbefehl"),
    ("Drogen", r"kokain|heroin|amphetamin|crystal|drogenhandel|rauschgift|betäubungsmittel|marihuana|cannabis"),
    ("Waffen", r"waffengesetz|schusswaffe|schreckschuss|messer"),
    ("Unfall (kein Verkehr)", r"arbeitsunfall|badeunfall|bergunfall|kletterunfall|skiunfall|freizeitunfall|badeunglück|ertrunken"),
    ("Verkehr", r"tödlicher? (verkehrs)?unfall|rettungshubschrauber|schwer verletzt"),
    ("Todesfall", r"\btot\b.*(geborgen|aufgefunden)|leichenfund|todesermittlung"),
    ("Diebstahl", r"diebstahl|gestohlen|entwendet|dieb"),
    ("Verkehr", r"verkehrsunfall|unfall|unfallflucht|fahrerflucht|trunkenheit|alkoholfahrt|kollision|zusammenstoß|verkehrskontrolle|rotlicht|straßenverkehr|fahrerlaubnis|pedelec|e-scooter|kraftrad|\bpkw\b"),
    ("Sachbeschädigung", r"sachbeschädigung|graffiti|beschmiert|beschädigt"),
    ("Versammlung", r"versammlung|demonstration|kundgebung"),
    ("Prävention/Hinweis", r"prävention|warnt|warnung|terminhinweis|mobile wache|hinweis der polizei|infoveranstaltung"),
    ("Personal/Organisation", r"amtswechsel|übernimmt .*leitung|neuer leiter|neue leiterin|verabschied"),
]
_COMPILED = [(k, re.compile(p, re.I)) for k, p in RULES]


def categorize(titel: str, text: str):
    for source in (titel or "", (text or "")[:600]):
        for kat, rx in _COMPILED:
            if rx.search(source):
                return kat
    return "Sonstiges"
