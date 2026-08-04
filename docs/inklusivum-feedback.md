# Rückfragen zum Inklusivum

Wir bauen eine Schreibhilfe, die Texte auf geschlechtergerechte Sprache prüft und Vorschläge macht. Das Inklusivum ist dort inzwischen eine der wählbaren Formen: Substantive, Artikel, Adjektive und Possessivformen werden automatisch gebildet, und Text, der bereits im Inklusivum geschrieben ist, wird als solcher erkannt und nicht mehr angemerkt.

Grundlage sind ausschließlich die Seiten des Vereins, vor allem [Gesamtsystem](https://geschlechtsneutral.net/gesamtsystem/), [Deklinationstabellen](https://geschlechtsneutral.net/deklinationstabellen/) und [Ausnahmeformen](https://geschlechtsneutral.net/ausnahmeformen/).

An einigen Stellen mussten wir Formen aus dem übrigen System ableiten, weil wir sie dort nicht gefunden haben. Diese Stellen sind unten aufgeführt. Wir haben sie im Code als Annahmen markiert und würden sie gerne durch eine Auskunft ersetzen, bevor mehr darauf aufbaut.

## Formen, die wir abgeleitet haben

### 1. Genitiv Plural der Substantive

Der Dativ Plural ist belegt (*den Schülernen*, *den Kundernen*). Für den Genitiv Plural haben wir nichts gefunden und nehmen an, dass er wie im übrigen Deutschen mit dem Nominativ Plural zusammenfällt, also *ders Schülerne*.

Ist das richtig?

### 2. Dativ von *ens* vor einem inklusivischen Substantiv

Wenn das besessene Substantiv selbst inklusivisch ist, folgt *ens* dem ein-Paradigma; belegt ist der Genitiv (*ensers jüngeren Geschwisters*, *ensers ehemaligen Nachbares*). Für den Dativ nehmen wir analog *enserm* an.

Vor einem gewöhnlichen Substantiv ist der Dativ dagegen belegt (*an ensem Geburtstag*), sodass es hier zwei verschiedene Formen gibt. Ist das so gewollt?

### 3. Reflexivpronomen

Zum Reflexivpronomen haben wir nichts gefunden. *sich* ist im Deutschen bereits geschlechtsunabhängig, deshalb nehmen wir an, dass es unverändert bleibt.

Trifft das zu, oder gibt es dazu eine Empfehlung, die wir übersehen haben?

### 4. Genitiv und Dativ der Ausnahmeformen

Die Ausnahmeseite nennt für Wörter wie *Prinze*, *Braute* oder *Hexere* Singular und Plural, wiederholt aber die allgemeinen Endungen nicht. Wir wenden sie weiterhin an, also Genitiv Singular *Prinzes* und Dativ Plural *Prinzernen*.

Gilt das, oder gibt es Ausnahmen auch bei den Kasusendungen?

### 5. Schwache Deklination (n-Deklination)

*Student* wird zu *Studente*. Wir nehmen an, dass die schwache Deklination damit vollständig entfällt, der Akkusativ also *de Studente* lautet und nicht *de Studenten*, weil auf der Seite keine Ausnahme dafür genannt wird.

Ist das so gemeint?

### 6. Vermutlicher Tippfehler bei *deselbe*

In der Aufzählung zu *derjenige*/*derselbe* steht als Grundform *deselbe*, in der Deklinationsreihe an erster Stelle aber *deselben* (*deselben/dersselben/dermselben/deselbe*). Nach dem Muster von *dejenige* und nach der Analogie zu *dieselbe/derselben/derselben/dieselbe* würden wir im Nominativ *deselbe* erwarten.

## Was die Umsetzung erleichtern würde

Diese Punkte sind Anregungen, keine Fehler. Sie kommen aus der Erfahrung, das System einmal vollständig in Code gegossen zu haben.

### Zwei Ausnahmen sind eigentlich Regeln

Auf der Ausnahmeseite stehen zwei Gruppen, die sich vollständig als Regel beschreiben lassen, und wir haben sie im Code auch so umgesetzt:

- **Romanische Lehnwörter**: die Endung wird ersetzt, nicht ergänzt (*Alumnus*/*Alumna* → *Alumne*, *Ballerino* → *Ballerine*).
- **Substantive auf *-erer***: das *-in* ersetzt das zweite *-er*, deshalb ist der gemeinsame Stamm kürzer (*Wanderer*/*Wanderin* → *Wandere*).

Als Regel formuliert decken sie auch Wörter ab, die auf der Seite nicht stehen, etwa *Latino*, *Guerillero*, *Libero* oder *Filipino*. Vielleicht wäre es für Lesende hilfreich, diese beiden Gruppen ausdrücklich als Regel zu benennen.

### Formulierungen, bei denen sich der Satzbau ändert

An mehreren Stellen ersetzt das Inklusivum nicht ein Wort durch ein anderes, sondern fasst zwei Formen zu einer zusammen:

- *Liebe Kollegin, lieber Kollege* wird zu einer einzigen Anrede.
- *Kolleginnen und Kollegen* wird zu *Kollegerne*, die Aufzählung entfällt also.
- *Sehr geehrte Damen und Herren* wird zu *Sehr geehrtes Team von …*.

Für ein Werkzeug ist das ein anderer Fall als eine Wortersetzung, weil ein Teil des Satzes wegfällt und die Ersetzung sich nicht mehr einer einzelnen Textstelle zuordnen lässt. Wir zeigen solche Vorschläge derzeit nicht an, weil wir sie nicht verlässlich abgrenzen können.

Gibt es dazu eine Empfehlung, etwa eine Liste der häufigen Paarformeln mit ihrer inklusivischen Entsprechung? Das wäre für uns der direkteste Weg, diese Fälle sauber abzudecken, und vermutlich auch für Menschen hilfreich, die die Formeln im Alltag ersetzen wollen.

### Anredeformen als Liste

Verwandt damit: Für *Herr* und *Frau* empfiehlt die Seite *Person [Nachname]* oder den vollständigen Namen. Eine zusammenhängende Liste der Anredeformen mit ihren Entsprechungen, einschließlich *Sehr geehrte…*, *Liebe*/*Lieber* und der Formeln für unbekannte Empfangende, würde die Umsetzung erheblich vereinfachen.

### Maschinenlesbare Tabellen

Die Deklinationstabellen und die Listen der bereits geschlechtsneutralen Personenwörter und der Ausnahmeformen mussten wir aus dem HTML herauslösen. Eine zusätzliche Fassung als CSV oder JSON, auch ohne Stabilitätsgarantie, würde solche Übernahmen deutlich verlässlicher machen und Übertragungsfehler vermeiden.

### Empfohlen oder gleichwertig

An mehreren Stellen werden zwei Formen genannt, teils gleichwertig (*Wanderne* und *Wandererne*), teils mit einer Empfehlung (*Torererne* oder *Torerne*). Für ein Werkzeug, das genau einen Vorschlag anzeigt, ist der Unterschied wichtig. Es wäre hilfreich, wenn erkennbar wäre, welche Form die empfohlene ist.

### Änderungen nachvollziehbar machen

Da sich Empfehlungen aus guten Gründen weiterentwickeln, wäre ein Hinweis auf Änderungen hilfreich, etwa ein Datum pro Abschnitt oder eine kurze Liste der letzten Anpassungen. So könnten wir gezielt nachziehen, statt regelmäßig alles neu zu vergleichen.

### Bereits geschlechtsneutrale Personenwörter

Wir führen dazu eine eigene Liste, weil unser Wörterbuch für einige dieser Wörter eine feminine Form kennt (*Gästin* zu *Gast*) und sie sonst gebeugt würden. Die Liste auf der Vereinsseite ist ausdrücklich nicht abschließend („u. a.“). Falls es dazu eine vollständigere Sammlung gibt, wäre sie für uns sehr nützlich.

## Rückmeldung

Wenn eine der obigen Annahmen falsch ist, korrigieren wir das gerne. Es geht uns darum, dass die Vorschläge dem entsprechen, was der Verein tatsächlich empfiehlt, und nicht dem, was wir daraus geschlossen haben.
