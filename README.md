# SSH UI

Jednostavan lokalni panel za SSH naloge na macOS-u i Windows-u. Prikazuje
servere i korisnike, pravi SSH ključeve, prikazuje i kopira javni ključ, učitava
ključ u `ssh-agent` i omogućava potvrđeno brisanje pristupa.

## Pokretanje

- macOS: dvoklik na `SSH-UI.command`
- Windows: dvoklik na `SSH-UI.cmd`

Potrebni su Python 3 i OpenSSH Client. Pokretač otvara panel na lokalnoj adresi
sa portom koji se automatski bira pri pokretanju; lokalni server radi samo na
ovom računaru.
Server se pokreće u pozadini, a prozor pokretača se zatvara. Kada zatvoriš
poslednji tab aplikacije, server se automatski gasi nakon oko 30 sekundi.

## Lokalni podaci

Serveri, korisnička imena i hosting panel linkovi čuvaju se van ovog Git
repozitorijuma:

- macOS: `~/Library/Application Support/SSH UI/serveri/`
- Windows: `%LOCALAPPDATA%\SSH UI\serveri\`
- Linux: `~/.local/share/ssh-ui/serveri/`

Dodavanje servera kroz aplikaciju čuva njegov zapis samo u pregledaču na tom
računaru. Korisnik bez ključa je privremen i nestaje posle osvežavanja.

Privatni ključevi ostaju u lokalnom `~/.ssh/` folderu; passphrase se unosi u
panel, prosleđuje samo lokalnom serveru za konkretnu operaciju i ne čuva se.
Javni ključ možeš da kopiraš i dodaš u hosting panel. Panel ne može sam da
opozove ključ u hostingu, pa ga pri brisanju ukloni i tamo.

Aktivacija ne postavlja rok važenja: ključ ostaje učitan u `ssh-agent` dok se
agent ne zaustavi ili se ključ ne ukloni.

Brisanje korisnika traži unos korisničkog imena. Brisanje servera traži unos
adrese. Akcija uklanja lokalni ključ i njegove rezervne kopije; za servere
koji su definisani u lokalnom `serveri/` folderu uklanja i taj lokalni zapis.

## Razvoj

Pokretanje servera iz terminala:

```sh
python3 prototip/server.py
```

Podaci specifični za korisnika ne pripadaju ovom repozitorijumu. Ne dodavati
server config, privatne ključeve, passphrase ili pristupne tokene u Git.
