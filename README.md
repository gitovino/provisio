# Provisio

Persoonlijke voorraad-app voor keuken, kasten en diepvriezers: barcode scannen, vervaldatums, boodschappenlijst, recepten en een gezondheidsscore volgens de Yuka-methode (berekend met Open Food Facts; geen officiële Yuka-score).

De app draait volledig in de browser en kan als app worden geïnstalleerd op telefoon, tablet en computer. Er staan geen persoonlijke gegevens in deze repository: de voorraad blijft op het toestel en, als je synchronisatie aanzet, in je eigen Google-account.

Productgegevens: [Open Food Facts](https://world.openfoodfacts.org) (ODbL).

## Bestanden

| Bestand | Waarvoor |
|---|---|
| `index.html` | De app zelf |
| `manifest.webmanifest` | Naam, icoon en kleuren voor de geïnstalleerde app |
| `sw.js` | Service worker: laat de app installeren en offline opstarten |
| `icons/` | App-iconen (startscherm, bureaublad, browsertabblad) |
| `.nojekyll` | Zorgt dat GitHub Pages alle bestanden ongewijzigd publiceert |

Zet alle bestanden en de map `icons` samen in de hoofdmap van de repository. Zonder `manifest.webmanifest`, `sw.js` en `icons/` werkt de app nog wel, maar dan kun je ze niet installeren.

## Installeren als app

Open `https://gitovino.github.io/provisio/` en kies **Instellingen › Algemeen › App installeren**. Daar staan de stappen voor jouw toestel en browser.

- **Android (Chrome):** knop *Installeren* in de app, of menu ⋮ › *App installeren*.
- **iPhone/iPad (Safari):** deelknop ⬆️ › *Zet op beginscherm* › *Voeg toe*.
- **Windows/Mac (Chrome of Edge):** installeericoon rechts in de adresbalk › *Installeren*.
- **Mac (Safari):** *Archief › Voeg toe aan Dock*.

Updates: zet een nieuwe `index.html` op GitHub. De geïnstalleerde app haalt bij het openen altijd eerst de nieuwste versie op; zonder internet start ze met de laatst bewaarde versie.
