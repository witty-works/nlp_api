from app.models import RuleLabelEnum, LangType


translations = {
    RuleLabelEnum.BE_SPECIFIC: {
        LangType.EN: "Be specific",
        LangType.DE: "Sei spezifisch",
        LangType.FR: "Soyez spécifique",
    },
    RuleLabelEnum.NOT_FOR_PEOPLE: {
        LangType.EN: "Don't use this phrase for people",
        LangType.DE: "Nicht auf Menschen beziehen",
        LangType.FR: "N'utilisez pas ce terme pour les personnes",
    },
    RuleLabelEnum.NAME_DISABILITY: {
        LangType.EN: "Name the disability or condition",
        LangType.DE: "Nenne die Behinderung oder Zustand",
        LangType.FR: "Nommez le handicap ou la condition",
    },
    RuleLabelEnum.ONLY_IF_GENDER_IDENTITY_RELEVANT: {
        LangType.EN: "Only if gender identity is relevant",
        LangType.DE: "Nur erwähnen, wenn relevant",
        LangType.FR: "Seulement si l'identité de genre est pertinente",
    },
    RuleLabelEnum.NOT_FOR_NON_COMBAT: {
        LangType.EN: "Only use in a combat context",
        LangType.DE: "Nur in einen Kampf-Kontext verwenden",
        LangType.FR: "Utilisez uniquement dans un contexte de combat",
    },
    RuleLabelEnum.ASK_FOR_PREFERENCE: {
        LangType.EN: "Only if preference explicitly stated",
        LangType.DE: "Nur wenn die Person sich so bezeichnet",
        LangType.FR: "Seulement si la préférence est explicitement exprimée",
    },
    RuleLabelEnum.ONLY_WHEN_REFERENCING_RELIGIOUS_PRACTICE: {
        LangType.EN: "Only use in reference to religious practice",
        LangType.DE: "Nur in Bezug auf die religiöse Praxis verwenden",
        LangType.FR: "Utilisez uniquement en référence à la pratique religieuse",
    },
    RuleLabelEnum.USE_IN_TECH_ONLY: {
        LangType.EN: "Use in programming only",
        LangType.DE: "Nur im Programmier-Kontext verwenden",
        LangType.FR: "Utilisez uniquement dans un contexte de programmation",
    },
    RuleLabelEnum.DONT_USE_TO_DESCRIBE_QUALITY: {
        LangType.EN: "Don't use to describe value or quality",
        LangType.DE: "Nicht zur Beschreibung von Wert oder Qualität verwenden",
        LangType.FR: "N'utilisez pas pour décrire la valeur ou la qualité",
    },
    RuleLabelEnum.DONT_USE_FOR_SUBSTANCE_USE: {
        LangType.EN: "Don't use in the context of substance use",
        LangType.DE: "Nicht im Zusammenhang mit Drogenkonsum verwenden",
        LangType.FR: "N'utilisez pas dans le cadre de la consommation de substances",
    },
    RuleLabelEnum.ASK_ABOUT_TRADITIONS: {
        LangType.EN: "Ask about their traditions",
        LangType.DE: "Frage nach ihren Traditionen",
        LangType.FR: "Demandez leurs traditions",
    },
    "ALLGENDER": {
        LangType.EN: "all gender",
        LangType.DE: "Alle Gender",
        LangType.FR: "tous les genres",
    },
    "EMOJIREPETITION": {
        LangType.EN: "Repeating emoji's may exclude screen reader users",
        LangType.DE: "Wiederholen von Emoji kann blinde Menschen ausschließen",
        LangType.FR: "La répétition des emojis peut exclure les utilisateurs·rices de lecteurs d'écran",
    },
    "EMOJISKINTONE": {
        LangType.EN: "Be mindful when using a skin tone that does not match your own",
        LangType.DE: "Vorsicht beim Verwenden von Hauttönen, die nicht den eigenen entsprechen",
        LangType.FR: "Soyez attentif à l'utilisation d'une teinte de peau qui ne correspond pas à la vôtre",
    },
    "EMOJIOVERUSE": {
        LangType.EN: "Emoji overuse may exclude screen reader users",
        LangType.DE: "Übermäßiger Gebrauch von Emoji kann blinde Menschen ausschließen",
        LangType.FR: "L'utilisation excessive d'emojis peut exclure les utilisateurs·rices de lecteurs d'écran",
    },
    "IDENTITYFIRST": {
        LangType.EN: "Identity first",
        LangType.DE: "Identität zuerst",
        LangType.FR: "L'identité d'abord",
    },
    "PERSONFIRST": {
        LangType.EN: "Person first",
        LangType.DE: "Person zuerst",
        LangType.FR: "La personne d'abord",
    },
    "IDENTITYVSPERSONURL": {
        LangType.EN: "https://www.witty.works/en/blog/person-first-vs.-identity-first-understanding-the-approaches",
        LangType.DE: "https://www.witty.works/de/blog/mensch-zuerst-vs.-identit%C3%A4t-zuerst-die-beiden-ans%C3%A4tze-verstehen",
        LangType.FR: "https://www.witty.works/fr/blog/la-personne-dabord-ou-lidentite-dabord",
    },
    "GENDERABBREVIATIONCONTEXT": {
        LangType.EN: "disabled (NA) / diverse (EU)",
        LangType.DE: "Divers (EU) / mit Behinderung (NA)",
        LangType.FR: "divers (EU) / avec handicap (NA)",
    },
    "GENDERABBREVIATIONCONTEXTREMOVE": {
        LangType.EN: "Use gender neutral job title",
        LangType.DE: "Nutze geschlechtsneutrale Job-Titel",
        LangType.FR: "Utilize des titres d'emploi non sexistes",
    },
    "GENDERABBREVIATIONEXPLANATION": {
        LangType.EN: "Put underrepresented groups first and link to your equal opportunity policy",
        LangType.DE: "Nenne unterrepräsentierte Gruppen zuerst. Verlinke auf deine Leitlinie zur Gleichstellung.",
        LangType.FR: "Mettez en avant les groupes sous-représentés et reliez-les à votre politique d'égalité des chances.",
    },
    "TOO_LONG_SENTENCE": {
        LangType.EN: "Long sentences are hard to read and comprehend. Break them into separate sentences.",
        LangType.DE: "Lange Sätze sind schwer zu lesen und zu verstehen. Trenne Nebensätze in separate Sätze.",
        LangType.FR: "Les phrases longues sont difficiles à lire et à comprendre. Divisez cette phrase en plusieurs phrases.",
    },
    "TOO_LONG_WORD": {
        LangType.EN: "Long words are hard to read and comprehend. Use a shorter word or hyphens.",
        LangType.DE: "Lange Wörter sind schwer zu lesen und zu verstehen. Verwende kürzere Wörter oder Bindestriche.",
        LangType.FR: "Les mots longs sont difficiles à lire et à comprendre. Utilisez un mot plus court ou des tirets.",
    },
    # The Inklusivum is unfamiliar enough that a suggestion on its own does not
    # tell anyone why, so these say which rule produced the form.
    "INKLUSIVUM_ARTICLE": {
        LangType.EN: "In the Inklusivum, words for people take the article ‘de’ even when the word itself does not change.",
        LangType.DE: "Im Inklusivum bekommen Personenwörter den Artikel „de“, auch wenn das Wort selbst unverändert bleibt.",
        LangType.FR: "Dans l'Inklusivum, les mots désignant des personnes prennent l'article « de », même lorsque le mot lui-même ne change pas.",
    },
    "INKLUSIVUM_ADJECTIVE": {
        LangType.EN: "In the Inklusivum, an adjective agrees with the noun: ‘-ey’ with no article, ‘-e’ or ‘-en’ after one.",
        LangType.DE: "Im Inklusivum richtet sich das Adjektiv nach dem Substantiv: ohne Artikel „-ey“, nach einem Artikel „-e“ oder „-en“.",
        LangType.FR: "Dans l'Inklusivum, l'adjectif s'accorde avec le nom : « -ey » sans article, « -e » ou « -en » après un article.",
    },
    "INKLUSIVUM_ARTICLE_LONG": {
        LangType.EN: "Words like ‘Gast’ or ‘Profi’ are masculine but already refer to anyone, so the word keeps its form and only the article changes, from ‘der’ to ‘de’.",
        LangType.DE: "Wörter wie „Gast“ oder „Profi“ sind maskulin, meinen aber bereits alle. Das Wort bleibt deshalb unverändert, nur der Artikel wird angepasst: aus „der“ wird „de“.",
        LangType.FR: "Des mots comme « Gast » ou « Profi » sont masculins mais désignent déjà tout le monde : le mot garde sa forme, seul l'article change, « der » devient « de ».",
    },
    "INKLUSIVUM_ADJECTIVE_LONG": {
        LangType.EN: "Adjectives agree with the noun. After an article they end in ‘-e’ or ‘-en’; with no article they take ‘-ey’, ‘-ers’ or ‘-erm’.",
        LangType.DE: "Adjektive richten sich nach dem Substantiv. Nach einem Artikel enden sie auf „-e“ oder „-en“, ohne Artikel auf „-ey“, „-ers“ oder „-erm“.",
        LangType.FR: "Les adjectifs s'accordent avec le nom. Après un article ils se terminent par « -e » ou « -en » ; sans article, par « -ey », « -ers » ou « -erm ».",
    },
    # Section anchors on the association's own pages, so the link lands on the
    # rule behind the suggestion rather than on the front page.
    "INKLUSIVUM_ARTICLE_URL": {
        LangType.EN: "https://geschlechtsneutral.net/bereits-geschlechtsneutrale-personenworter/#mask",
        LangType.DE: "https://geschlechtsneutral.net/bereits-geschlechtsneutrale-personenworter/#mask",
        LangType.FR: "https://geschlechtsneutral.net/bereits-geschlechtsneutrale-personenworter/#mask",
    },
    "INKLUSIVUM_ADJECTIVE_URL": {
        LangType.EN: "https://geschlechtsneutral.net/gesamtsystem/#adjektive",
        LangType.DE: "https://geschlechtsneutral.net/gesamtsystem/#adjektive",
        LangType.FR: "https://geschlechtsneutral.net/gesamtsystem/#adjektive",
    },
}
