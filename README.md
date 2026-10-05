# SSH UI

Jednostavan lokalni panel za SSH naloge na macOS-u i Windows-u. Prikazuje
servere i korisnike, pravi SSH ključeve, prikazuje i kopira javni ključ, učitava
ključ u `ssh-agent` i omogućava potvrđeno brisanje pristupa.

## Pokretanje

- macOS: dvoklik na `SSH UI - Mac.app`
- Windows: dvoklik na `SSH UI - Windows.vbs`

Ovi pokretači ne otvaraju terminal. macOS aplikaciju možeš premestiti u
Applications ili dodati u Dock. Za Windows zadrži celu strukturu projekta
i napravi prečicu na radnoj površini do `SSH UI - Windows.vbs`. Interfejs se
otvara u pregledaču. U glavnom folderu su dva pokretača sa jasno označenim sistemom,
a pomoćne skripte su u `launcher`.

Potrebni su Python 3 i OpenSSH Client. Pokretač otvara panel na lokalnoj adresi
sa portom koji se automatski bira pri pokretanju; lokalni server radi samo na
ovom računaru.
Server radi samo dok koristiš panel. Kada zatvoriš poslednji tab ili prozor
sa stranicom aplikacije, server se automatski gasi nakon oko 5 sekundi.
Ostali tabovi pregledača ne utiču na to. Osvežavanje stranice ne gasi server.
Ako pregledač ne prijavi zatvaranje (npr. nasilno gašenje), server se gasi
nakon isteka provere prisutnosti taba, najkasnije za oko 5 minuta i 5 sekundi.
Pri pokretanju čeka do 30 sekundi da se prvi tab otvori.

## Lokalni podaci

Serveri, korisnička imena i hosting panel linkovi čuvaju se van ovog Git
repozitorijuma:

- macOS: `~/Library/Application Support/SSH UI/serveri/`
- Windows: `%LOCALAPPDATA%\SSH UI\serveri\`
- Linux: `~/.local/share/ssh-ui/serveri/`

Serveri dodati kroz aplikaciju, linkovi panela i korisnici čuvaju se trajno u
`podaci.json` u istom lokalnom folderu `SSH UI` (na Linux-u `ssh-ui`).
Čuvanje ne zavisi od porta ili pregledača. Čuvaju se i serveri bez korisnika
i korisnici bez ključa. Status ključa se pri pokretanju proverava na disku i u
`ssh-agent`.

Pri dodavanju servera unose se samo IP adresa (IPv4 ili IPv6) i SSH port.
SSH port podrazumevano je 22. U prikazu servera port se uvek ispisuje,
na primer `203.0.113.10:22` ili `[2001:db8::1]:22`.
Korisnici se dodaju kasnije dugmetom „Dodaj korisnika“.

Stari podaci iz pregledača prenose se ako aplikaciju otvoriš na istoj lokalnoj
adresi i portu na kojima su ranije sačuvani, pre prvog čuvanja novih podataka.
Privatni ključevi se ovim prenosom ne menjaju. Ako stari zapis više nije
dostupan u pregledaču, dodavanje istog IP-a, porta i korisničkog imena
prepoznaje postojeći lokalni ključ bez pravljenja novog.

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

Posle izmena koda ponovo napravi macOS aplikaciju:

```sh
python3 launcher/napravi-mac.py
```

Aplikacija sadrži kopiju panela, ali i dalje zahteva instaliran Python 3.10 ili
noviji i OpenSSH. Ne sadrži korisničke podatke ili ključeve.


Pokretanje servera iz terminala:

```sh
python3 prototip/server.py
```

Podaci specifični za korisnika ne pripadaju ovom repozitorijumu. Ne dodavati
server config, privatne ključeve, passphrase ili pristupne tokene u Git.

Provere čuvanja i formulara (koriste privremene podatke):

```sh
python3 -m unittest discover -s prototip/tests -v
node prototip/tests/test_forms.cjs
```
