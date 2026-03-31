"""
MONITORATORE PREZZI - casadelprofumo.it (solo sezione Profumi)
Invia alert su Telegram quando il prezzo scende del 70% o piu'.
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re
from datetime import datetime

# ================================================================
#  CONFIGURAZIONE
# ================================================================

import os

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "INSERISCI_QUI_IL_TOKEN_DEL_BOT")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "INSERISCI_QUI_IL_TUO_CHAT_ID")

SOGLIA_SCONTO    = 0.70          # 70% di calo per scattare l'alert
FILE_PREZZI      = "prezzi_salvati.json"
PAUSA_TRA_PAGINE = 3.0           # secondi tra una pagina e l'altra

# Solo la sezione profumi
CATEGORIE = [
    "https://www.casadelprofumo.it/profumi/",
]

# ================================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def invia_telegram(testo_html):
    if TELEGRAM_TOKEN == "INSERISCI_QUI_IL_TOKEN_DEL_BOT":
        print("[!] Telegram non configurato - alert in console:")
        print(testo_html)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": testo_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[ERRORE] Telegram: {e}")
        return False


def parse_prezzo(testo):
    if not testo:
        return None
    pulito = re.sub(r"[€EUReur\s\xa0]", "", testo)
    if re.search(r"\d\.\d{3},\d{2}", pulito):
        pulito = pulito.replace(".", "").replace(",", ".")
    else:
        pulito = pulito.replace(",", ".")
    try:
        m = re.search(r"\d+\.\d+|\d+", pulito)
        val = float(m.group()) if m else None
        return val if val and val > 0 else None
    except Exception:
        return None


def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  [WARN] Impossibile caricare {url}: {e}")
        return None


def conta_pagine(soup):
    numeri = []
    # Legge SOLO i numeri dai link href, non dal testo (evita di confondere prezzi con pagine)
    for a in soup.find_all("a", href=True):
        m = re.search(r"[?&]page=(\d+)", a.get("href", ""))
        if m:
            numeri.append(int(m.group(1)))
    return max(numeri) if numeri else 1


def estrai_prodotti_da_pagina(soup):
    prodotti = []
    visti = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"_z\d+", href):
            continue
        if href.startswith("/"):
            href = "https://www.casadelprofumo.it" + href
        if href in visti:
            continue
        visti.add(href)

        nome_el = a.find(["h3", "h2", "strong"])
        nome = nome_el.get_text(separator=" ", strip=True) if nome_el else a.get_text(separator=" ", strip=True)[:120]
        nome = re.sub(r"\s+", " ", nome).strip()
        if not nome or len(nome) < 4:
            continue

        testo_blocco = a.get_text(" ", strip=True)
        prezzi_trovati = re.findall(r"(\d+[,\.]\d{2})\s*€", testo_blocco)
        if not prezzi_trovati:
            continue

        prezzo = parse_prezzo(prezzi_trovati[0])
        prezzo_orig = parse_prezzo(prezzi_trovati[1]) if len(prezzi_trovati) > 1 else None

        if prezzo and prezzo > 0:
            prodotti.append({
                "nome": nome,
                "url": href,
                "prezzo": prezzo,
                "prezzo_originale": prezzo_orig,
            })
    return prodotti


def scarica_categoria(url_categoria):
    print(f"\n  Categoria: {url_categoria}")
    soup = get_soup(url_categoria)
    if not soup:
        return []
    n_pagine = conta_pagine(soup)
    print(f"  Pagine trovate: {n_pagine}")

    tutti = []
    visti_url = set()
    for p in range(1, n_pagine + 1):
        s = soup if p == 1 else get_soup(f"{url_categoria}?page={p}")
        if not s:
            continue
        if p > 1:
            time.sleep(PAUSA_TRA_PAGINE)
        nuovi = [pr for pr in estrai_prodotti_da_pagina(s) if pr["url"] not in visti_url]
        for pr in nuovi:
            visti_url.add(pr["url"])
        tutti.extend(nuovi)
        print(f"  Pagina {p:>3}/{n_pagine}: {len(nuovi):>4} nuovi (totale: {len(tutti)})")
    return tutti


def scarica_catalogo():
    print("\nScansione catalogo profumi...")
    catalogo = {}
    for url_cat in CATEGORIE:
        for p in scarica_categoria(url_cat):
            if p["url"] not in catalogo:
                catalogo[p["url"]] = p
    print(f"Prodotti unici trovati: {len(catalogo)}")
    return catalogo


def carica_prezzi_salvati():
    if not os.path.exists(FILE_PREZZI):
        return {}
    try:
        with open(FILE_PREZZI, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Errore lettura {FILE_PREZZI}: {e}")
        return {}


def salva_prezzi(catalogo):
    dati = {
        url: {
            "nome": p["nome"],
            "prezzo": p["prezzo"],
            "url": p["url"],
            "ultima_scansione": datetime.now().isoformat(),
        }
        for url, p in catalogo.items()
    }
    with open(FILE_PREZZI, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)
    print(f"Prezzi salvati: {len(dati)} prodotti in '{FILE_PREZZI}'")


def controlla_e_avvisa(catalogo_attuale, prezzi_salvati):
    alert_inviati = 0
    for url, prodotto in catalogo_attuale.items():
        if url not in prezzi_salvati:
            continue
        prezzo_ora   = prodotto["prezzo"]
        prezzo_prima = prezzi_salvati[url]["prezzo"]
        if prezzo_prima <= 0 or prezzo_ora <= 0:
            continue
        calo = (prezzo_prima - prezzo_ora) / prezzo_prima
        if calo >= SOGLIA_SCONTO:
            pct       = round(calo * 100, 1)
            risparmio = round(prezzo_prima - prezzo_ora, 2)
            nome      = prodotto["nome"]
            msg = (
                f"<b>CALO PREZZI -{pct}%</b>\n\n"
                f"<b>{nome}</b>\n\n"
                f"Era: <s>{prezzo_prima:.2f} EUR</s>\n"
                f"Ora: <b>{prezzo_ora:.2f} EUR</b>\n"
                f"Risparmio: <b>{risparmio:.2f} EUR</b>\n\n"
                f'<a href="{url}">Vai al prodotto</a>\n\n'
                f"{datetime.now().strftime('%d/%m/%Y %H:%M')}"
            )
            print(f"\n[ALERT] {nome}: {prezzo_prima:.2f} -> {prezzo_ora:.2f} EUR (-{pct}%)")
            if invia_telegram(msg):
                alert_inviati += 1
                print("  Telegram inviato!")
            time.sleep(1)
    return alert_inviati


def main():
    print("=" * 55)
    print("MONITORATORE PREZZI - casadelprofumo.it/profumi")
    print(f"Soglia: -{int(SOGLIA_SCONTO * 100)}%  |  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("=" * 55)

    prezzi_salvati = carica_prezzi_salvati()
    if prezzi_salvati:
        print(f"Prezzi di riferimento: {len(prezzi_salvati)} prodotti")
    else:
        print("Prima esecuzione: salvo i prezzi base, nessun alert oggi.")

    catalogo = scarica_catalogo()
    if not catalogo:
        print("[ERRORE] Nessun prodotto trovato.")
        return

    if prezzi_salvati:
        print("\nConfronto prezzi...")
        n = controlla_e_avvisa(catalogo, prezzi_salvati)
        print(f"Alert inviati: {n}" if n else "Nessun calo rilevato.")

    salva_prezzi(catalogo)
    print("=" * 55)
    print(f"Fine: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("=" * 55)


if __name__ == "__main__":
    main()
