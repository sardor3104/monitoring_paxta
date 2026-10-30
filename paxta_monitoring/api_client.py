"""
Hosil Qabuli API mijoz classi
"""
import urllib.request
import urllib.error
import json
import time
from config import API_BASE_URL, DEFAULT_HEADERS

class HosilApiClient:
    def __init__(self, token: str):
        self.token = token.strip()
        self.headers = dict(DEFAULT_HEADERS)
        self.headers["Authorization"] = f"Bearer {self.token}"

    def _get(self, path: str, retries: int = 3, timeout: int = 20):
        url = f"{API_BASE_URL}/{path.lstrip('/')}"
        req = urllib.request.Request(url, headers=self.headers)
        
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise PermissionError(f"Avtorizatsiya xatosi (HTTP {e.code}): Token eskirgan yoki ruxsat berilmagan.")
                if attempt == retries - 1:
                    raise e
                time.sleep(1.0 * (attempt + 1))
            except Exception as e:
                if attempt == retries - 1:
                    raise e
                time.sleep(1.0 * (attempt + 1))
        return None

    def get_user_info(self):
        """Foydalanuvchi ma'lumotlari va ruxsat berilgan hudud"""
        return self._get("/auth/user-info/")

    def get_districts(self, region_id: str, year: int = 2026):
        """Viloyatdagi barcha tumanlar ro'yxati"""
        return self._get(f"/monitoring/cotton/region/district/{region_id}/?year={year}")

    def get_farmers(self, district_id: str, year: int = 2026):
        """Tumandagi fermerlar ro'yxati"""
        return self._get(f"/monitoring/cotton/region/farmer/{district_id}/?year={year}")

    def get_farmer_loads(self, farmer_tax_number: str, district_id: str, year: int = 2026):
        """Fermerning yuklari / tarozi o'lchovlari"""
        return self._get(f"/monitoring/cotton/region/loads/{farmer_tax_number}/?year={year}&district={district_id}")

    def get_all_region_loads(self, region_id: str, year: int = 2026, progress_callback=None):
        """
        Viloyatdagi barcha tumanlar va fermerlar bo'yicha barcha yuklarni yuklab olish
        """
        districts = self.get_districts(region_id, year=year)
        all_loads = []
        total_districts = len(districts)

        for d_idx, d in enumerate(districts, start=1):
            d_id = d["id"]
            d_name = d.get("name_uz") or d.get("name_ru") or d.get("name")
            if progress_callback:
                progress_callback("district_start", {"district": d_name, "index": d_idx, "total": total_districts})

            try:
                farmers = self.get_farmers(d_id, year=year)
                if not farmers:
                    continue

                active_farmers = [
                    f for f in farmers 
                    if (f.get("physical_total_net") or 0) > 0 or (f.get("physical_system_daily_net") or 0) > 0
                ]

                for f in active_farmers:
                    tin = f.get("farmer_tax_number")
                    f_name = f.get("farmer_name")
                    try:
                        loads = self.get_farmer_loads(tin, d_id, year=year)
                        if loads:
                            for l in loads:
                                l["_region_id"] = region_id
                                l["_district_id"] = d_id
                                l["_district_name"] = d_name
                                l["_farmer_tax_number"] = tin
                                l["_farmer_name"] = f_name
                                all_loads.append(l)
                    except Exception as err:
                        if progress_callback:
                            progress_callback("load_error", {"farmer": f_name, "error": str(err)})

            except Exception as err:
                if progress_callback:
                    progress_callback("district_error", {"district": d_name, "error": str(err)})

        if progress_callback:
            progress_callback("complete", {"total_loads": len(all_loads)})

        return all_loads
