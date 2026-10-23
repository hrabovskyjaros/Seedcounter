# HTZ stanice — návod k instalaci

Stanice = skříň s kamerou + Raspberry Pi, které samo fotí, počítá zrna a ukládá měření.
Nepotřebuje žádný cizí server ani internet (internet jen při instalaci a aktualizaci).

Obrazovka je stejná appka jako na iPadu. Na stanici navíc:
- **fotí kamera ve skříni** a **počítá Raspberry**,
- každé uložené měření jde i do souboru **`mereni.csv`** ve stanici,
- appku jde otevřít i z jiného počítače v síti.

---

## Co je potřeba

- Raspberry Pi ve skříni (Pi 3B+), kamera, monitor, klávesnice (myš se hodí)
- **prázdná USB flashka** (16 GB a víc) — nebo nová microSD karta
- síťový kabel do Raspberry
- počítač s Windows na přípravu flashky

> **Starou kartu z Raspberry nemaž.** Vyndej ji, popiš a schovej — je to záloha starého systému.

---

## 1. Soubory na GitHub

Do repozitáře **Seedcounter** nahraj (Add file → Upload files):
- `index.html` (nahradí stávající),
- **celou složku `stanice`** — přetáhni ji do okna jako složku.

Výsledek má vypadat takhle:
```
index.html
apple-touch-icon.png
icon-192.png
stanice/
    server.py
    htz_count.py
    install.sh
    aktualizovat.sh
    otevrit-appku.sh
    NAVOD.md
```

## 2. Systém na flashku (na počítači)

1. Stáhni a spusť **Raspberry Pi Imager**: https://www.raspberrypi.com/software/
2. **Zařízení:** Raspberry Pi 3
3. **Operační systém:** Raspberry Pi OS (64-bit) — *ten s plochou (desktop)*
4. **Úložiště:** tvoje USB flashka (pozor, ať nevybereš jiný disk!)
5. Na dotaz „Upravit nastavení?“ dej **Upravit** a vyplň:
   - název počítače (hostname): **`htz-stanice`**
   - uživatel: **`htz`** + heslo (zapiš si ho)
   - časové pásmo **Europe/Prague**, klávesnice **cz**
   - Wi-Fi jen pokud nepůjde kabel
   - v záložce Služby můžeš zapnout SSH (vzdálená správa, nepovinné)
6. **Zapsat** a počkat, až skončí.

## 3. Zapojení

1. Raspberry **vypni** (vytáhni napájení skříně).
2. **Vyndej starou microSD kartu** a schovej ji.
3. Flashku zastrč do **USB** v Raspberry, zapoj **síťový kabel**, monitor, klávesnici.
4. Zapni. První start trvá pár minut, objeví se plocha.

> Kdyby Raspberry z flashky nenaběhlo (černá obrazovka, duhový čtverec), zkus jinou flashku,
> nebo zapiš systém stejným postupem na novou microSD kartu.

## 4. Instalace stanice (na Raspberry)

Otevři **Terminál** (černá ikona nahoře v liště) a napiš postupně tyto tři řádky
(po každém Enter, u `sudo` se může ptát na heslo):

```bash
sudo apt install -y git
```
```bash
git clone https://github.com/hrabovskyjaros/Seedcounter
```
```bash
bash Seedcounter/stanice/install.sh
```

Instalace trvá několik minut. Na konci napíše **„Hotovo. Stanice běží.“** a adresy.
Pak restartuj:

```bash
sudo reboot
```

## 5. Používání (na počítači s Windows)

Raspberry ve skříni jen **fotí a posílá živý obraz**. Počítá a ukazuje počítač s Windows.

Na počítači otevři v **Chrome nebo Edge**: `http://seedcounter.local:8080`
(když nefunguje, IP adresu z konce instalace, např. `http://192.168.1.50:8080`).
Ulož si ji do záložek.

- **Vlevo:** plodina, pokus, kód vzorku, hmotnost, poslední měření.
- **Vpravo:** živý obraz z kamery ve skříni.

**Pokus** ⏎ **Kód vzorku** ⏎ **Hmotnost** ⏎ (vyfotí a spočítá) → ⏎ uložit → zpět živý obraz.
Když appka chce další fotku: protřes misku a dej **mezerník**.

- **Všechna měření ze stanice:** *Všechna měření* → **Stáhnout všechna měření ze stanice (CSV)**.
- Na Raspberry jsou uložená v `~/htz-data/mereni.csv`.
- Poslední fotka ve plném rozlišení: `http://seedcounter.local:8080/api/posledni.jpg`.

> Appka na iPadu (GitHub) je samostatná a stanice ji nijak neovlivňuje.

## 6. Aktualizace

Když se na GitHubu objeví nová verze appky, na Raspberry v Terminálu:

```bash
bash Seedcounter/stanice/aktualizovat.sh
```

## 7. Když něco nejde

| Problém | Co udělat |
|---|---|
| Stránka se na Windows neotevře | Zkus IP adresu místo `seedcounter.local`; na Raspberry `hostname -I` ji vypíše |
| Vpravo není živý obraz | Server neběží — na Raspberry `sudo systemctl restart htz-stanice` |
| Stanice nevyfotí | Zkontroluj kameru: `rpicam-hello --list-cameras` (musí ji vypsat) |
| Chci vidět chyby serveru | `journalctl -u htz-stanice -n 50` |

Výpis chyby pošli Claudovi — podle něj se dá poradit.
