# Inklusivum: Annahmen aus dem direkten Austausch

Die Umsetzung des Inklusivums (`"german_gender_ending": "de-e"`, siehe [inklusivum.md](./inklusivum.md)) folgt den Seiten auf [geschlechtsneutral.net](https://geschlechtsneutral.net/). Einige Punkte stehen dort nicht; wir haben sie aus dem direkten Austausch mit dem Verein übernommen oder so verstanden. Dieses Dokument hält sie fest, damit sie nachprüfbar bleiben, bis sie veröffentlicht sind.

## Übernommen

1. **Kasusendungen der Ausnahmeformen.** Die allgemeinen Endungen gelten auch für die Formen der [Ausnahmeformen](https://geschlechtsneutral.net/ausnahmeformen/)-Seite: Genitiv Singular *ders Prinzes*, Dativ Plural *den Prinzernen*. Auf der Seite kommt der Genitiv nicht vor.
2. **Welche von mehreren Formen empfohlen ist.** Nennt eine Seite mehrere Formen ohne ausdrückliche Empfehlung, gilt die zuerst genannte (*Freunde* vor *Freundere*, *Enkele* vor *Enkle*). Eine ausdrückliche Empfehlung geht der Reihenfolge vor (*Torererne* vor *Torerne*).
3. **Anrede für *Sehr geehrte Damen und Herren*.** Für ein Werkzeug mit einem einzigen Vorschlag ist *Guten Tag!* die empfohlene Form. Die [Anredeformen](https://geschlechtsneutral.net/geschlechtsneutrale-anredeformen/)-Seite nennt *Sehr geehrtes Team von [Organisationsname]* zuerst und widerspricht damit Punkt 2.
4. **Bereits geschlechtsneutrale Personenwörter.** Der Inklusivomat verwendet eine vollständigere Liste als die Seite „Bereits geschlechtsneutrale Personenwörter“. Sie umfasst nur Substantive, die einen inklusivischen Artikel bekommen, also keine Neutra wie *Kind*. Bis auf die Wörter in Punkt 6 ist sie in [inklusivum_neutral_nouns.csv](../training_data/de/inklusivum_neutral_nouns.csv) übernommen.

## Offen

5. **Plural der Doppelformen im Maskulinum.** Die Ausnahmeformen-Seite gibt *de Ahne*, Plural *Ahnerne*, aber *de Nachfahre*, Plural *Nachfahrne*. Das sind zwei verschiedene Muster für gleich gebaute Wörter. Wir übernehmen beide so, wie sie dastehen ([inklusivum_nouns.csv](../training_data/de/inklusivum_nouns.csv)); ob der Unterschied gewollt ist, ist nicht geklärt.
6. ***Elfe*, *Geselle*, *Titane*.** In der Liste aus Punkt 4 als bereits geschlechtsneutral geführt, mit Verweis auf die Doppelformen; ihr Plural ist aber nirgends genannt. Bis das geklärt ist, stehen sie in keiner unserer Listen.
