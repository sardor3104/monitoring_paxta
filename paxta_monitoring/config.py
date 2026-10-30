"""
Paxta monitoring tizimi konfiguratsiyasi
"""
import os

API_BASE_URL = "https://api.hosil-qabuli.uz"
DEFAULT_YEAR = 2026
PPTX_TEMPLATE_PATH = os.environ.get(
    "PPTX_TEMPLATE_PATH",
    os.path.join(os.path.dirname(__file__), "template_rule5.pptx"),
)

# Autentifikatsiya tokeni (Bearer token)
DEFAULT_TOKEN = os.environ.get("HOSIL_TOKEN", "141b2c88-59e1-4221-bd4e-65f8d58d6965")

# Qoidalar parametrlari
RULE2_MAX_MINUTES = 15.0  # Kirishdan keyin 15 daqiqa ichida qayta kirish

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.2 Safari/605.1.15",
    "Origin": "https://hosil-qabuli.uz",
    "Referer": "https://hosil-qabuli.uz/",
    "Accept": "application/json, text/plain, */*"
}
