from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time

# Setup
options = Options()
options.add_argument("--start-maximized")
prefs = {"download.prompt_for_download": False}
options.add_experimental_option("prefs", prefs)

driver = webdriver.Chrome(options=options)

# 1. Gehe zur Uber Eats Login Seite
driver.get("https://www.ubereats.com/")

# 2. Manuell einloggen (alternativ: cookies automatisieren)
input("Bitte logge dich manuell ein und drücke ENTER, wenn du fertig bist...")

# 3. Navigiere zur Bestellhistorie
driver.get("https://www.ubereats.com/orders")

# 4. Warte auf die Seite und lade alle Bestellungen
time.sleep(5)

# 5. Hol dir alle Bestellungen
orders = driver.find_elements(By.XPATH, "//a[contains(@href, '/order/')]")
order_links = [o.get_attribute("href") for o in orders]

print(f"{len(order_links)} Bestellungen gefunden")

# 6. Gehe jede Bestellung durch und lade die Rechnung
for link in order_links:
    driver.get(link)
    time.sleep(5)

    try:
        button = driver.find_element(By.XPATH, "//button[contains(text(),'Rechnung herunterladen')]")
        button.click()
        print(f"Rechnung heruntergeladen von: {link}")
        time.sleep(3)  # gib dem Download Zeit
    except Exception as e:
        print(f"Fehler bei {link}: {e}")

driver.quit()