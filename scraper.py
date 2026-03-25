from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time

url_capitulo = "https://skydemonorder.com/projects/3801994495-return-of-the-mount-hua-sect/1-what-the-hell-is-this-situation-1"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(url_capitulo)
    time.sleep(5)
    html = page.content()
    browser.close()

soup = BeautifulSoup(html, "html.parser")

# El contenido está en el div con clase "prose"
contenido = soup.find("div", class_="prose")

if contenido:
    texto = contenido.get_text(separator="\n").strip()
    print(texto[:1000])  # primeros 1000 caracteres
else:
    print("No se encontró el contenido")