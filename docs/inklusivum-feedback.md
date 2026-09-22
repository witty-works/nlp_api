# Rückfragen zum Inklusivum

Wir bauen eine Schreibhilfe, die Texte auf geschlechtergerechte Sprache prüft und Vorschläge macht. Das Inklusivum ist dort inzwischen eine der wählbaren Formen: Substantive, Artikel, Adjektive und Possessivformen werden automatisch gebildet, und Text, der bereits im Inklusivum geschrieben ist, wird als solcher erkannt und nicht mehr angemerkt.

Grundlage waren zunächst ausschließlich die Seiten des Vereins, vor allem [Gesamtsystem](https://geschlechtsneutral.net/gesamtsystem/), [Deklinationstabellen](https://geschlechtsneutral.net/deklinationstabellen/) und [Ausnahmeformen](https://geschlechtsneutral.net/ausnahmeformen/). An einigen Stellen mussten wir Formen ableiten, weil wir sie dort nicht gefunden haben.

Inzwischen haben wir diese Stellen mit dem [Inklusivomaten](https://automat.geschlechtsneutral.net/) und seinem [Quellcode](https://github.com/LinusWemmer/gn_tool) abgeglichen. Alle unsere Annahmen haben sich dort bestätigt. Die Liste steht unten trotzdem, weil der Quellcode zeigt, was gebaut wurde, und nicht unbedingt, was der Verein empfiehlt — und weil die betreffenden Formen auf den Seiten weiterhin fehlen.

## Abgeleitete Formen, die sich im Inklusivomaten bestätigt haben

Für uns sind diese Punkte damit geklärt. Wir nennen sie hier vor allem, falls die Seiten ergänzt werden sollen.

1. **Genitiv Plural der Substantive.** Fällt mit dem Nominativ Plural zusammen (*der Schülerne*). Auf den Seiten ist nur der Dativ Plural belegt (*den Schülernen*).
2. **Artikel im Plural.** Bleiben unverändert, auch im Genitiv: also *der Schülerne* und nicht *ders Schülerne*. Das ergibt sich aus dem Grundsatz, dass der Plural bereits geschlechtsneutral ist, steht aber an keiner Stelle ausdrücklich für den Genitiv.
3. **Dativ von *ens* vor einem inklusivischen Substantiv.** *enserm*, nach dem ein-Paradigma. Vor einem gewöhnlichen Substantiv bleibt dagegen *ensem* (*an ensem Geburtstag*). Dass es hier zwei Formen gibt, ist also so gewollt.
4. **Reflexivpronomen.** Bleibt *sich*.
5. **Genitiv und Dativ der Ausnahmeformen.** Folgen der allgemeinen Regel, also Genitiv Singular *Prinzes*, Dativ Plural *Prinzernen*.
6. **Schwache Deklination.** Entfällt vollständig: *den Studenten* wird zu *de Studente*.
7. **Genitiv des alleinstehenden Artikelpronomens.** *einers*. Die leere Zelle in den Deklinationstabellen ist eine Lücke in der Tabelle, keine fehlende Form.

## Zwei Stellen, die sich widersprechen

### *deselben* statt *deselbe*

In der Aufzählung zu *derjenige*/*derselbe* steht als Grundform *deselbe*, in der Deklinationsreihe an erster Stelle aber *deselben* (*deselben/dersselben/dermselben/deselbe*). Der Inklusivomat bildet im Nominativ *deselbe*. Das sieht nach einem Tippfehler auf der Seite aus.

### *Sehr geehrte Damen und Herren*

Die Seiten empfehlen *Sehr geehrtes Team von [Organisation]*. Der Inklusivomat schreibt *Sehr geehrte Leute*. Welche Form ist die empfohlene? Für ein Werkzeug, das genau einen Vorschlag anzeigt, ist das ein Unterschied.

## Was die Umsetzung erleichtern würde

Diese Punkte sind Anregungen, keine Fehler. Sie kommen aus der Erfahrung, das System einmal vollständig in Code gegossen zu haben.

### Zwei Ausnahmen sind eigentlich Regeln

Auf der Ausnahmeseite stehen zwei Gruppen, die sich vollständig als Regel beschreiben lassen, und wir haben sie im Code auch so umgesetzt:

- **Romanische Lehnwörter**: die Endung wird ersetzt, nicht ergänzt (*Alumnus*/*Alumna* → *Alumne*, *Ballerino* → *Ballerine*).
- **Substantive auf *-erer***: das *-in* ersetzt das zweite *-er*, deshalb ist der gemeinsame Stamm kürzer (*Wanderer*/*Wanderin* → *Wandere*).

Als Regel formuliert decken sie auch Wörter ab, die auf der Seite nicht stehen. Der Inklusivomat führt die romanischen Lehnwörter als feste Liste (*Alumn-*, *Ballerin-*, *Emerit-*, *Filipin-*, *Gueriller-*, *Latin-*, *Liber-*, *Mafios-*, *Torer-*); als Regel gilt dasselbe Muster auch für Wörter außerhalb dieser Liste. Vielleicht wäre es für Lesende hilfreich, die beiden Gruppen ausdrücklich als Regel zu benennen.

### Formulierungen, bei denen sich der Satzbau ändert

An mehreren Stellen ersetzt das Inklusivum nicht ein Wort durch ein anderes, sondern fasst zwei Formen zu einer zusammen:

- *Liebe Kollegin, lieber Kollege* wird zu einer einzigen Anrede.
- *Kolleginnen und Kollegen* wird zu *Kollegerne*, die Aufzählung entfällt also.
- *Sehr geehrte Damen und Herren* wird zu einer einzigen Formel.

Für ein Werkzeug ist das ein anderer Fall als eine Wortersetzung, weil ein Teil des Satzes wegfällt und die Ersetzung sich nicht mehr einer einzelnen Textstelle zuordnen lässt. Der Inklusivomat löst das, indem er den ganzen Text umschreibt; wir zeigen einzelne Vorschläge an und müssen die Fundstelle deshalb über beide Glieder und die Konjunktion legen.

Gibt es dazu eine Empfehlung, etwa eine Liste der häufigen Paarformeln mit ihrer inklusivischen Entsprechung? Das wäre für uns der direkteste Weg, diese Fälle sauber abzudecken, und vermutlich auch für Menschen hilfreich, die die Formeln im Alltag ersetzen wollen.

### Anredeformen als Liste

Verwandt damit: Für *Herr* und *Frau* empfiehlt die Seite *Person [Nachname]* oder den vollständigen Namen. Eine zusammenhängende Liste der Anredeformen mit ihren Entsprechungen, einschließlich *Sehr geehrte…*, *Liebe*/*Lieber* und der Formeln für unbekannte Empfangende, würde die Umsetzung erheblich vereinfachen.

### Maschinenlesbare Tabellen

Die Deklinationstabellen und die Listen der bereits geschlechtsneutralen Personenwörter und der Ausnahmeformen mussten wir aus dem HTML herauslösen. Im Inklusivomaten liegen dieselben Daten als Python-Listen vor. Eine zusätzliche Fassung als CSV oder JSON, auch ohne Stabilitätsgarantie, würde solche Übernahmen deutlich verlässlicher machen und Übertragungsfehler vermeiden.

### Empfohlen oder gleichwertig

An mehreren Stellen werden zwei Formen genannt, teils gleichwertig (*Wanderne* und *Wandererne*), teils mit einer Empfehlung (*Torererne* oder *Torerne*). Für ein Werkzeug, das genau einen Vorschlag anzeigt, ist der Unterschied wichtig. Es wäre hilfreich, wenn erkennbar wäre, welche Form die empfohlene ist.

### Änderungen nachvollziehbar machen

Da sich Empfehlungen aus guten Gründen weiterentwickeln, wäre ein Hinweis auf Änderungen hilfreich, etwa ein Datum pro Abschnitt oder eine kurze Liste der letzten Anpassungen. So könnten wir gezielt nachziehen, statt regelmäßig alles neu zu vergleichen.

### Bereits geschlechtsneutrale Personenwörter

Wir führen dazu eine eigene Liste, weil unser Wörterbuch für einige dieser Wörter eine feminine Form kennt (*Gästin* zu *Gast*) und sie sonst gebeugt würden. Die Liste auf der Vereinsseite ist ausdrücklich nicht abschließend („u. a."). Falls es dazu eine vollständigere Sammlung gibt, wäre sie für uns sehr nützlich.

## Rückmeldung

Wenn eine der obigen Annahmen falsch ist, korrigieren wir das gerne. Es geht uns darum, dass die Vorschläge dem entsprechen, was der Verein tatsächlich empfiehlt, und nicht dem, was wir daraus geschlossen haben.
