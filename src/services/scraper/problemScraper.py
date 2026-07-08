import requests
from bs4 import BeautifulSoup

def scrapeProblemPage(contest_id: int, index: str) -> BeautifulSoup | None:
    url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}"
    print(f"Scraping: {url}")
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return BeautifulSoup(response.text, 'html.parser')
        else:
            print(f"Failed to fetch {url}. Status code: {response.status_code}")
            return None
    except Exception as e:
        print(f"Network error while fetching {url}: {e}")
        return None