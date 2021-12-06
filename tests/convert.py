import json

list = [
    {
        "text": "Manager",
        "context": "",
        "category": "gendered",
        "subcategory": "function",
        "start": 17,
        "end": 24,
        "alternatives": ["Management", "Manager:in"],
        "label": "Geschlechtsspezifisch: Spezielle Funktionen",
        "reason": "Aus wirtschaftlich-historischen Gründen wird unbewusst ein Bild eines Mannes vor dem inneren Auge hervorgerufen. Das weibliche Geschlecht oder andere Geschlechtsidentitäten werden nicht sichtbar. Und sie fühlen sich nicht zugehörig.",
        "solution": "Umgehen Sie mit anderen Worten das unbewusst hervorgerufene Bild. Nutzen Sie eher das Nomen, das die Tätigkeit bezeichnet, um das unbewusste Bild zu umgehen. Oder verwenden Sie eine geschlechtsneutrale Bezeichnung.",
    },
    {
        "text": "der",
        "context": "",
        "category": "gendered",
        "subcategory": "function",
        "start": 13,
        "end": 16,
        "alternatives": ["der:die"],
        "label": "Geschlechtsspezifisch: Spezielle Funktionen",
        "reason": "Aus wirtschaftlich-historischen Gründen wird unbewusst ein Bild eines Mannes vor dem inneren Auge hervorgerufen. Das weibliche Geschlecht oder andere Geschlechtsidentitäten werden nicht sichtbar. Und sie fühlen sich nicht zugehörig.",
        "solution": "Umgehen Sie mit anderen Worten das unbewusst hervorgerufene Bild. Nutzen Sie eher das Nomen, das die Tätigkeit bezeichnet, um das unbewusste Bild zu umgehen. Oder verwenden Sie eine geschlechtsneutrale Bezeichnung.",
    },
    {
        "text": "Boss",
        "context": "",
        "category": "gendered",
        "subcategory": "leadership",
        "start": 34,
        "end": 38,
        "alternatives": [
            "Leitende Kraft",
            "Leitungsperson",
            "Leitung",
            "Vorgesetzte:r",
            "Leitende Kräfte",
            "Leitungskräfte",
            "Leitungspersonen",
            "Vorgesetzte",
            "Entscheidungsbefugte Person",
            "Verantwortliche Person",
        ],
        "label": "Geschlechtsspezifisch: Führungsstereotyp",
        "reason": "Besetzt das Thema der Führung stereotyp männlich und traditionell hierarchisch.",
        "solution": "Verwenden Sie Begriffe, die von einer unterstützenden Vorstellung der Führung ausgeht und verschiedene Geschlechter meinen kann.",
    },
]

conv = json.dumps(list)

print(conv)
