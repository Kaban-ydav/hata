import requests
from curl_cffi import requests as cffi_requests

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

print("=== ТЕСТ 1: ОБЫЧНЫЙ БОТ (requests) ===")
# Бьем в Daft
res1 = requests.get("https://www.daft.ie/property-for-rent/ireland", headers=headers)
print(f"Daft.ie ответил кодом: {res1.status_code}")

# Бьем в Rent
res2 = requests.get("https://www.rent.ie/houses-to-let/renting_ireland/", headers=headers)
print(f"Rent.ie ответил кодом: {res2.status_code}")


print("\n=== ТЕСТ 2: УМНЫЙ ОБХОД (curl_cffi chrome120) ===")
res3 = cffi_requests.get("https://www.daft.ie/property-for-rent/ireland", headers=headers, impersonate="chrome120")
print(f"Daft.ie (CFFI) ответил кодом: {res3.status_code}")

res4 = cffi_requests.get("https://www.rent.ie/houses-to-let/renting_ireland/", headers=headers, impersonate="chrome120")
print(f"Rent.ie (CFFI) ответил кодом: {res4.status_code}")