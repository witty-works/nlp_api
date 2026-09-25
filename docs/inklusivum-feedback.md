# Rückfragen zum Inklusivum

Wir bauen eine Schreibhilfe, die Texte auf geschlechtergerechte Sprache prüft und Vorschläge macht. Das Inklusivum ist dort inzwischen eine der wählbaren Formen: Substantive, Artikel, Adjektive und Possessivformen werden automatisch gebildet, und Text, der bereits im Inklusivum geschrieben ist, wird als solcher erkannt und nicht mehr angemerkt.

Grundlage waren zunächst [Gesamtsystem](https://geschlechtsneutral.net/gesamtsystem/), [Deklinationstabellen](https://geschlechtsneutral.net/deklinationstabellen/) und [Ausnahmeformen](https://geschlechtsneutral.net/ausnahmeformen/). An einigen Stellen mussten wir Formen ableiten, weil wir sie dort nicht gefunden haben. Inzwischen haben wir diese Stellen mit dem [Inklusivomaten](https://automat.geschlechtsneutral.net/) und seinem [Quellcode](https://github.com/LinusWemmer/gn_tool) abgeglichen; alle unsere Annahmen bis auf eine haben sich dort bestätigt.

Dieses Dokument nennt die Stellen, an denen wir beim Umsetzen stehen geblieben sind. Es ist als Rückmeldung gedacht und nicht als Fehlerliste: das System ist ausführlich dokumentiert, und die meisten dieser Lücken fallen vermutlich nur auf, wenn man versucht, es vollständig in Code zu gießen.

## Wo die Dokumentation ergänzt werden könnte

Nach Seite geordnet. Wo wir eine Form angenommen haben, steht sie dabei, damit erkennbar ist, ob wir richtig geraten haben.

### Gesamtsystem

1. **Genitiv Plural der Substantive.** Der Abschnitt zu den regelmäßigen Substantiven nennt Singular, Genitiv Singular (*einers Schüleres*), Plural und Dativ Plural (*den Schülernen*). Der Genitiv Plural fehlt. Wir nehmen an, dass er mit dem Nominativ Plural zusammenfällt, also *der Schülerne*.
2. **Reflexivpronomen.** Kommt auf der Seite nicht vor. *sich* ist im Deutschen bereits geschlechtsunabhängig, deshalb nehmen wir an, dass es unverändert bleibt. Ein Halbsatz dazu würde die Frage erledigen.
3. **Dativ von *ens* vor einem inklusivischen Substantiv.** Belegt ist der Genitiv (*ensers jüngeren Geschwisters*). Für den Dativ nehmen wir analog *enserm* an. Vor einem gewöhnlichen Substantiv bleibt es dagegen *ensem* (*an ensem Geburtstag*), es gibt hier also zwei verschiedene Formen. Dass das so gewollt ist, steht nirgends ausdrücklich.
4. **Schwache Deklination.** *Student* → *Studente* steht als Beispiel, aber nicht, dass die n-Deklination damit vollständig entfällt. Wir nehmen an, dass der Akkusativ *de Studente* lautet und nicht *de Studenten*.

### Deklinationstabellen

5. **Keine Tabelle für Substantive.** Personalpronomen, Artikel, Adjektive und die sonstigen Pronomen haben je eine Tabelle; das Wort *Substantiv* kommt auf der Seite gar nicht vor. Die Endungen stehen stattdessen im Fließtext des Gesamtsystems. Eine Substantivtabelle an dieser Stelle würde Punkt 1 miterledigen.
6. **Kein Plural in den Tabellen.** Alle Reihen sind Singular. Gerade im Plural wäre eine Zeile hilfreich, weil dort Artikel, Adjektive und Pronomen unverändert bleiben — das ist die Information, die eine Pluralzeile auf einen Blick zeigen würde. Wir hatten zwischenzeitlich *ders Schülerne* angenommen, bis klar war, dass der Plural den gewöhnlichen Artikel behält: *der Schülerne*.
7. **Personalpronomen ohne Genitivzeile.** Die Tabelle führt Nominativ, Possessivform, Dativ und Akkusativ. Die Genitivform *enser* steht nur im Fließtext des Gesamtsystems („Wir gedenken enser."). Eine Zeile in der Tabelle wäre konsistenter.
8. **Artikelpronomen, Genitiv.** Die Zelle enthält „—", und zwar in allen vier Spalten. Wir haben das zunächst als Lücke in der Tabelle gelesen und analog zur attributiven Form *einers* angenommen. Dass der Strich bedeutet, dass die Form nicht vorgesehen ist, wurde uns erst durch den Vergleich der Spalten klar. Eine Fußnote dazu würde diesen Fehlschluss ausschließen.
9. **Vermutlicher Tippfehler.** In der Aufzählung zu *derjenige*/*derselbe* steht als Grundform *deselbe*, in der Deklinationsreihe an erster Stelle aber *deselben*. Nach dem Muster von *dejenige* und nach der Analogie zu *dieselbe* würden wir im Nominativ *deselbe* erwarten; der Inklusivomat bildet ebenfalls *deselbe*.

### Ausnahmeformen

10. **Kasusendungen.** Für Wörter wie *Prinze*, *Braute* oder *Hexere* sind Singular und Plural genannt; das Wort *Genitiv* kommt auf der Seite nicht vor. Wir wenden die allgemeinen Endungen weiter an, also Genitiv Singular *Prinzes* und Dativ Plural *Prinzernen*. Ein Satz, dass die allgemeinen Regeln auch für die Ausnahmen gelten, würde das absichern.

### Anredeformen

11. **Der Inklusivomat weicht von der Seite ab.** Die Seite empfiehlt für *Sehr geehrte Damen und Herren* die Formen *Sehr geehrtes Team von [Organisationsname]*, *Sehr geehrtes [Organisationsname]-Team* oder *Guten Tag!*. Der Inklusivomat schreibt stattdessen *Sehr geehrte Leute*. Für ein Werkzeug, das genau einen Vorschlag anzeigt, ist damit offen, welche Form die empfohlene ist.

### Seitenübergreifend

12. **Querverweise aus dem Gesamtsystem.** Wir haben lange nur mit Gesamtsystem, Deklinationstabellen und Ausnahmeformen gearbeitet und dabei übersehen, dass es eigene Seiten zu [Anredeformen](https://geschlechtsneutral.net/geschlechtsneutrale-anredeformen/) und [Neologismen](https://geschlechtsneutral.net/neologismen/) gibt — beide beantworten Fragen, die wir uns selbst gestellt hatten. Ein Verweis an der passenden Stelle im Gesamtsystem („zu Anreden siehe …") würde solchen Umwegen vorbeugen. Das ist unser Versäumnis und keines der Seite; wir erwähnen es, weil andere Umsetzungen vermutlich denselben Weg nehmen.

## Was die Umsetzung erleichtern würde

Diese Punkte sind Anregungen, keine Fehler. Sie kommen aus der Erfahrung, das System einmal vollständig in Code gegossen zu haben.

### Zwei Ausnahmen sind eigentlich Regeln

Auf der Ausnahmeseite stehen zwei Gruppen, die sich vollständig als Regel beschreiben lassen, und wir haben sie im Code auch so umgesetzt:

- **Romanische Lehnwörter**: die Endung wird ersetzt, nicht ergänzt (*Alumnus*/*Alumna* → *Alumne*, *Ballerino* → *Ballerine*).
- **Substantive auf *-erer***: das *-in* ersetzt das zweite *-er*, deshalb ist der gemeinsame Stamm kürzer (*Wanderer*/*Wanderin* → *Wandere*).

Als Regel formuliert decken sie auch Wörter ab, die auf der Seite nicht stehen. Der Inklusivomat führt die romanischen Lehnwörter als feste Liste (*Alumn-*, *Ballerin-*, *Emerit-*, *Filipin-*, *Gueriller-*, *Latin-*, *Liber-*, *Mafios-*, *Torer-*); als Regel gilt dasselbe Muster auch darüber hinaus. Vielleicht wäre es für Lesende hilfreich, die beiden Gruppen ausdrücklich als Regel zu benennen.

### Paarformeln

An mehreren Stellen ersetzt das Inklusivum nicht ein Wort durch ein anderes, sondern fasst zwei Formen zu einer zusammen: *Kolleginnen und Kollegen* wird zu *Kollegerne*, die Aufzählung entfällt also. Für ein Werkzeug ist das ein anderer Fall als eine Wortersetzung, weil ein Teil des Satzes wegfällt und sich die Ersetzung nicht mehr einer einzelnen Textstelle zuordnen lässt.

Eine Liste der häufigen Paarformeln mit ihrer inklusivischen Entsprechung wäre für uns der direkteste Weg, diese Fälle sauber abzudecken, und vermutlich auch für Menschen hilfreich, die die Formeln im Alltag ersetzen wollen. Für Anreden leistet die Anredeformen-Seite genau das bereits.

### Maschinenlesbare Tabellen

Die Deklinationstabellen und die Listen der bereits geschlechtsneutralen Personenwörter und der Ausnahmeformen mussten wir aus dem HTML herauslösen. Im Inklusivomaten liegen dieselben Daten als Python-Listen vor. Eine zusätzliche Fassung als CSV oder JSON, auch ohne Stabilitätsgarantie, würde solche Übernahmen deutlich verlässlicher machen und Übertragungsfehler vermeiden.

### Empfohlen oder gleichwertig

An mehreren Stellen werden zwei Formen genannt, teils gleichwertig (*Freunde* oder *Freundere*, *Wanderne* und *Wandererne*), teils mit einer Empfehlung (*Torererne* oder *Torerne*). Für ein Werkzeug, das genau einen Vorschlag anzeigt, ist der Unterschied wichtig. Es wäre hilfreich, wenn erkennbar wäre, welche Form die empfohlene ist.

### Änderungen nachvollziehbar machen

Da sich Empfehlungen aus guten Gründen weiterentwickeln, wäre ein Hinweis auf Änderungen hilfreich, etwa ein Datum pro Abschnitt oder eine kurze Liste der letzten Anpassungen. So könnten wir gezielt nachziehen, statt regelmäßig alles neu zu vergleichen.

### Bereits geschlechtsneutrale Personenwörter

Wir führen dazu eine eigene Liste, weil unser Wörterbuch für einige dieser Wörter eine feminine Form kennt (*Gästin* zu *Gast*) und sie sonst gebeugt würden. Die Liste auf der Vereinsseite ist ausdrücklich nicht abschließend („u. a."). Falls es dazu eine vollständigere Sammlung gibt, wäre sie für uns sehr nützlich.

## Rückmeldung

Wenn eine der obigen Annahmen falsch ist, korrigieren wir das gerne. Es geht uns darum, dass die Vorschläge dem entsprechen, was der Verein tatsächlich empfiehlt, und nicht dem, was wir daraus geschlossen haben.
