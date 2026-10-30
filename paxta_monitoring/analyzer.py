"""
O'lchovlardagi anomaliyalarni aniqlash moduli
Tekshiriladigan qoidalar:
1-Qoida: Bir maskanda traktor kirishi va chiqishi oralig'ida boshqa texnikalar kirishi (Interleaving)
2-Qoida: Bir maskanda kirishdan keyin 15 daqiqa ichida takroriy kirish o'tkazilishi
3-Qoida: ENG XAVFLI HOLAT ("AYLANTIRISH"): Ayni bir texnika raqami va 1-qoida bir vaqtda amal qilishi
4-Qoida: Brutto farqi 400 kg, tara 100 kg, netto 300 kg chegaralarida bo'lgan yukning
         oralig'ida boshqa yuk kirishi
"""
from datetime import datetime
from typing import List, Dict, Any
import re

RULE4_MAX_WEIGHT_DIFFERENCES = {
    "brutto": 400,
    "tara": 100,
    "netto": 300,
}


def parse_iso_datetime(dt_str: str):
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None

def normalize_truck_number(num: str) -> str:
    if not num:
        return ""
    return "".join(num.strip().upper().split())


def _normalized_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9а-яёўқғҳ]", "", str(value).casefold())


def is_distributed_load(load: Dict[str, Any]) -> bool:
    """Saytda ``Taqsimlangan`` deb belgilangan yuklarni aniqlaydi.

    API turli versiyalarida status nomi yoki qiymati o'zgarishi mumkin, shuning
    uchun faqat bitta maydon nomiga bog'lanmaymiz.
    """
    status_keys = (
        "taqsim", "distribution", "distributed", "allocation",
        "allocated", "split", "divided", "status", "state", "holat",
        "тақсим", "таксим", "распредел",
    )
    distributed_values = {
        "taqsimlangan", "distributed", "allocated", "split", "divided",
        "тақсимланган", "таксимланган", "распределен", "распределено",
        "true", "yes", "ha", "1",
    }

    def visit(value: Any, key: str = "") -> bool:
        normalized_key = _normalized_text(key)
        key_matches = any(token in normalized_key for token in status_keys)
        if isinstance(value, dict):
            return any(visit(child, child_key) for child_key, child in value.items())
        if isinstance(value, (list, tuple)):
            return any(visit(child, key) for child in value)
        if key_matches:
            normalized_value = _normalized_text(value)
            return normalized_value in distributed_values
        return False

    return visit(load)


class CottonAnomalyAnalyzer:
    def __init__(self, loads: List[Dict[str, Any]], rule2_max_minutes: float = 15.0):
        self.raw_loads = loads
        self.rule2_max_minutes = rule2_max_minutes
        self.processed_loads = []
        self.by_maskan = {}
        self._prepare_data()

    def _prepare_data(self):
        """Ma'lumotlarni tozalash, sanalarni o'qish va maskanlar bo'yicha guruhlash"""
        seen_loads = set()
        for l in self.raw_loads:
            if is_distributed_load(l):
                # Taqsimlangan yuk rasmiy alohida o'lchov hisoblanadi va
                # hech qaysi qoida bo'yicha juftlikka kiritilmaydi.
                continue
            in_dt = parse_iso_datetime(l.get("in_date"))
            out_dt = parse_iso_datetime(l.get("out_date"))
            maskan = (l.get("place_name") or "Noma'lum maskan").strip()
            truck_raw = (l.get("transport_number") or "Noma'lum").strip()
            truck_norm = normalize_truck_number(truck_raw)
            district = (l.get("_district_name") or "Noma'lum tuman").strip()
            load_id = l.get("id")
            if load_id:
                load_key = ("id", str(load_id))
            else:
                load_key = (
                    "fallback",
                    l.get("registration_number"),
                    l.get("in_date"),
                    l.get("out_date"),
                    maskan,
                    truck_norm,
                    l.get("_farmer_tax_number") or l.get("_farmer_name"),
                )
            if load_key in seen_loads:
                continue
            seen_loads.add(load_key)

            item = {
                "id": l.get("id"),
                "registration_number": l.get("registration_number"),
                "maskan": maskan,
                "district": district,
                "truck": truck_raw,
                "truck_norm": truck_norm,
                "in_dt": in_dt,
                "out_dt": out_dt,
                "in_str": in_dt.strftime("%d.%m.%Y %H:%M:%S") if in_dt else "-",
                "out_str": out_dt.strftime("%d.%m.%Y %H:%M:%S") if out_dt else "Chiqmagan",
                "fullweight": l.get("fullweight"),
                "taraweight": l.get("taraweight"),
                "netto": l.get("physical_net"),
                "farmer_name": l.get("_farmer_name") or l.get("farmer_name") or "-",
                "farmer_tin": l.get("_farmer_tax_number") or "-",
                "raw": l
            }
            # Parse numeric weights once to avoid repeated float() calls during comparisons
            try:
                item["fullweight_f"] = float(item["fullweight"]) if item["fullweight"] is not None else None
            except Exception:
                item["fullweight_f"] = None
            try:
                item["taraweight_f"] = float(item["taraweight"]) if item["taraweight"] is not None else None
            except Exception:
                item["taraweight_f"] = None
            try:
                item["netto_f"] = float(item["netto"]) if item["netto"] is not None else None
            except Exception:
                item["netto_f"] = None
            if in_dt:
                self.processed_loads.append(item)
                self.by_maskan.setdefault(maskan, []).append(item)

        # Har bir maskandagi yuklarni kirish vaqti bo'yicha saralash
        for maskan in self.by_maskan:
            self.by_maskan[maskan].sort(key=lambda x: x["in_dt"])

    @staticmethod
    def _same_farmer(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
        """Fermerlarni avval STIR, bo'lmasa nomi bo'yicha taqqoslaydi."""
        first_key = (first.get("farmer_tin") or first.get("farmer_name") or "").strip().upper()
        second_key = (second.get("farmer_tin") or second.get("farmer_name") or "").strip().upper()
        return bool(first_key and second_key and first_key == second_key)

    def detect_rule1_interleaving(self) -> List[Dict[str, Any]]:
        """
        1-Qoida: Traktor kirishi va chiqishi oralig'ida boshqa kirishlar paydo bo'lishi.
        Optimized with bisect to only scan loads whose in_dt fall in interval.
        """
        import bisect
        violations = []

        for maskan, items in self.by_maskan.items():
            if not items:
                continue
            in_times = [it["in_dt"] for it in items]
            for i, a in enumerate(items):
                if not a["out_dt"] or not a["in_dt"]:
                    continue

                left = bisect.bisect_right(in_times, a["in_dt"])
                right = bisect.bisect_left(in_times, a["out_dt"])  # exclusive
                if left >= right:
                    continue

                interleaved = []
                for idx in range(left, right):
                    b = items[idx]
                    if self._same_farmer(a, b):
                        interleaved.append(b)

                if interleaved:
                    violations.append({
                        "maskan": maskan,
                        "district": a["district"],
                        "main_load": a,
                        "interleaved_loads": interleaved,
                        "count": len(interleaved),
                    })

        return violations

    @staticmethod
    def _weight_difference(first: Dict[str, Any], second: Dict[str, Any]):
        """Ikki yukning brutto, tara va netto qiymatlari farqini hisoblaydi.
        Uses pre-parsed numeric fields (fullweight_f, taraweight_f, netto_f) when available.
        """
        try:
            f1 = first.get("fullweight_f")
            f2 = second.get("fullweight_f")
            t1 = first.get("taraweight_f")
            t2 = second.get("taraweight_f")
            n1 = first.get("netto_f")
            n2 = second.get("netto_f")
            if f1 is None or f2 is None or t1 is None or t2 is None or n1 is None or n2 is None:
                return None
            fullweight_diff = abs(f1 - f2)
            taraweight_diff = abs(t1 - t2)
            netto_diff = abs(n1 - n2)
        except Exception:
            return None
        return {
            "brutto": fullweight_diff,
            "tara": taraweight_diff,
            "netto": netto_diff,
        }

    def detect_rule4_weight_interleaving(self) -> List[Dict[str, Any]]:
        """
        4-Qoida: 1-yukning kirish-chiqish oralig'ida ayni maskanga kirgan
        boshqa yuk bilan brutto farqi 400 kg, tara farqi 100 kg va netto
        farqi 300 kg gacha bo'lsa.
        Optimized using bisect to only consider seconds with in_dt in the interval.
        """
        import bisect
        violations = []
        seen_first_loads = set()
        for maskan, items in self.by_maskan.items():
            if not items:
                continue
            in_times = [it["in_dt"] for it in items]
            for first in items:
                if not first["out_dt"] or not first["in_dt"]:
                    continue
                first_key = (
                    first["in_dt"],
                    first["out_dt"],
                    first.get("truck_norm"),
                    first.get("registration_number"),
                    first.get("fullweight_f"),
                    first.get("taraweight_f"),
                    first.get("netto_f"),
                )
                if (maskan, first_key) in seen_first_loads:
                    continue

                left = bisect.bisect_right(in_times, first["in_dt"])
                right = bisect.bisect_left(in_times, first["out_dt"])  # exclusive
                if left >= right:
                    continue

                for idx in range(left, right):
                    second = items[idx]
                    if first is second or (first.get("id") and first.get("id") == second.get("id")):
                        continue
                    weight_differences = self._weight_difference(first, second)
                    if weight_differences is None:
                        continue
                    if any(
                        weight_differences[key] > limit
                        for key, limit in RULE4_MAX_WEIGHT_DIFFERENCES.items()
                    ):
                        continue
                    violations.append({
                        "maskan": maskan,
                        "district": first["district"],
                        "first_load": first,
                        "second_load": second,
                        "weight_differences": {key: round(value, 1) for key, value in weight_differences.items()},
                        "weight_difference": round(max(weight_differences.values()), 1),
                        "overlap_minutes": round((first["out_dt"] - second["in_dt"]).total_seconds() / 60.0, 1),
                    })
                    seen_first_loads.add((maskan, first_key))
                    # Count only first matching second for this first load to avoid duplicates
                    break
        return violations

    def detect_rule5_single_farmer_weight_interleaving(self) -> List[Dict[str, Any]]:
        """5-qoida: bitta asosiy yuk uchun barcha mos oraliq kirishlarni jamlaydi."""
        import bisect

        violations = []
        interleaved_load_keys = set()

        def load_key(load):
            return (
                load["in_dt"],
                load["out_dt"],
                load.get("truck_norm"),
                load.get("registration_number"),
                load.get("fullweight_f"),
                load.get("taraweight_f"),
                load.get("netto_f"),
            )

        for maskan, items in self.by_maskan.items():
            if not items:
                continue
            in_times = [item["in_dt"] for item in items]
            seen_main_loads = set()
            for first in items:
                if not first["in_dt"] or not first["out_dt"]:
                    continue
                first_key = load_key(first)
                if first_key in seen_main_loads:
                    continue
                seen_main_loads.add(first_key)

                left = bisect.bisect_right(in_times, first["in_dt"])
                right = bisect.bisect_left(in_times, first["out_dt"])
                interleaved = []
                seen_interleaved_loads = set()
                for second in items[left:right]:
                    second_key = load_key(second)
                    if first_key == second_key or second_key in seen_interleaved_loads:
                        continue
                    if (
                        first.get("truck_norm")
                        and first.get("truck_norm") == second.get("truck_norm")
                    ):
                        continue
                    if not self._same_farmer(first, second):
                        continue
                    weight_differences = self._weight_difference(first, second)
                    if weight_differences is None or any(
                        weight_differences[key] > limit
                        for key, limit in RULE4_MAX_WEIGHT_DIFFERENCES.items()
                    ):
                        continue
                    seen_interleaved_loads.add(second_key)
                    interleaved.append(second)

                if interleaved:
                    interleaved_load_keys.update(
                        (maskan, load_key(load)) for load in interleaved
                    )
                    violations.append({
                        "maskan": maskan,
                        "district": first["district"],
                        "main_load": first,
                        "interleaved_loads": interleaved,
                        "count": len(interleaved),
                    })
        return [
            item
            for item in violations
            if (item["maskan"], load_key(item["main_load"])) not in interleaved_load_keys
        ]

    def detect_rule2_consecutive_entries(self) -> List[Dict[str, Any]]:
        """
        2-Qoida: Bir maskanda kirishdan keyin 15 daqiqa ichida takroriy kirish o'tkazilishi.
        """
        violations = []

        for maskan, items in self.by_maskan.items():
            for i in range(len(items) - 1):
                curr = items[i]
                next_item = items[i + 1]

                delta_sec = (next_item["in_dt"] - curr["in_dt"]).total_seconds()
                delta_min = delta_sec / 60.0

                if 0 <= delta_min <= self.rule2_max_minutes and self._same_farmer(curr, next_item):
                    is_same = (curr["truck_norm"] != "") and (curr["truck_norm"] == next_item["truck_norm"])
                    violations.append({
                        "maskan": maskan,
                        "district": curr["district"],
                        "first_load": curr,
                        "second_load": next_item,
                        "diff_minutes": round(delta_min, 1),
                        "diff_seconds": int(delta_sec),
                        "is_same_truck": is_same
                    })

        return violations

    def detect_rule3_same_truck_interleaving(self) -> List[Dict[str, Any]]:
        """
        3-Qoida: TEXNIKA RAQAMI BIR XIL + 1-QOIDA BIR VAQTDA AMAL QILISHI.
        """
        violations = []

        for maskan, items in self.by_maskan.items():
            for i, a in enumerate(items):
                if not a["out_dt"] or not a["truck_norm"]:
                    continue

                for j, b in enumerate(items):
                    if i != j and a["truck_norm"] == b["truck_norm"]:
                        # 1-qoida: A kirish < B kirish < A chiqish
                        if a["in_dt"] < b["in_dt"] < a["out_dt"]:
                            overlap_sec = (a["out_dt"] - b["in_dt"]).total_seconds()
                            violations.append({
                                "maskan": maskan,
                                "district": a["district"],
                                "district_first": a["district"],
                                "district_second": b["district"],
                                "truck": a["truck"],
                                "first_load": a,
                                "second_load": b,
                                "overlap_minutes": round(overlap_sec / 60.0, 1)
                            })

        return violations

    def run_all(self):
        """Barcha 3 ta qoida bo'yicha to'liq tahlil"""
        r1 = self.detect_rule1_interleaving()
        r2 = self.detect_rule2_consecutive_entries()
        r3 = self.detect_rule3_same_truck_interleaving()
        r4 = self.detect_rule4_weight_interleaving()
        r5 = self.detect_rule5_single_farmer_weight_interleaving()
        daily_load_counts = {}
        daily_maskans = {}
        for load in self.processed_loads:
            day = load["in_dt"].date().isoformat()
            daily_load_counts[day] = daily_load_counts.get(day, 0) + 1
            daily_maskans.setdefault(day, set()).add(load["maskan"])
        return {
            "total_loads": len(self.processed_loads),
            "total_maskans": len(self.by_maskan),
            "daily_load_counts": daily_load_counts,
            "daily_maskan_counts": {
                day: len(maskans) for day, maskans in daily_maskans.items()
            },
            "rule1_count": len(r1),
            "rule2_count": len(r2),
            "rule3_count": len(r3),
            "rule4_count": len(r4),
            "rule1_results": r1,
            "rule2_results": r2,
            "rule3_results": r3,
            "rule4_results": r4,
            "rule5_count": len(r5),
            "rule5_results": r5,
        }
