import urllib.request
import json

url = "https://gist.githubusercontent.com/erichurst/7882666/raw/5bdc46db47d9515269ab12ed6fb2850377fd869e/US%2520Zip%2520Codes%2520from%25202013%2520Government%2520Data"

response = urllib.request.urlopen(url)
lines = response.read().decode('utf-8').splitlines()

zip_map = {}
for line in lines[1:]: # skip header
    parts = line.strip().split(',')
    if len(parts) >= 3:
        zipcode = parts[0].zfill(5)
        lat = float(parts[1])
        lng = float(parts[2])
        zip_map[zipcode] = {"lat": lat, "lon": lng}

with open("data/zipcodes.json", "w") as f:
    json.dump(zip_map, f)

print(f"Downloaded and parsed {len(zip_map)} zip codes.")
