"""
Paxta monitoringi anomaliyalarni aniqlash dasturi (CLI)
Ishga tushirish:
    python3 main.py
    python3 main.py --token <BEARER_TOKEN>
    python3 main.py --export
    python3 main.py --live 60
"""
import sys
import os
import argparse
import time
from pathlib import Path
from datetime import date, datetime, timedelta

from config import DEFAULT_TOKEN, DEFAULT_YEAR, PPTX_TEMPLATE_PATH, RULE2_MAX_MINUTES
from api_client import HosilApiClient
from analyzer import CottonAnomalyAnalyzer
from report_generator import ReportGenerator, BOLD, GREEN, RED, YELLOW, CYAN, MAGENTA, RESET

def main():
    parser = argparse.ArgumentParser(description="Paxta monitoringi - Aylantirish va anomaliyalarni aniqlash dasturi")
    parser.add_argument("--token", "-t", default=DEFAULT_TOKEN, help="OneID orqali olingan Bearer token")
    parser.add_argument("--year", "-y", type=int, default=DEFAULT_YEAR, help="Mavsum yili (standart: 2026)")
    parser.add_argument("--export", "-e", action="store_true", default=True, help="CSV va HTML hisobotlarni avtomatik saqlash")
    parser.add_argument("--outdir", "-o", default="hisobotlar", help="Hisobotlar saqlanadigan papka")
    parser.add_argument("--live", "-l", type=int, default=0, help="Jonli monitoring rejimi (har N soniyada qayta tekshiradi)")
    parser.add_argument(
        "--clean-reports",
        action="store_true",
        help="Hisobotlar papkasidagi yaratilgan CSV, HTML va PPTX fayllarni o'chiradi",
    )
    parser.add_argument(
        "--qoida1",
        action="store_true",
        help="Eski parametr; PPTX yaratish vaqtincha o'chirilgan",
    )
    parser.add_argument(
        "--qoida2",
        action="store_true",
        help="Eski parametr; PPTX yaratish vaqtincha o'chirilgan",
    )
    parser.add_argument(
        "--qoida4",
        action="store_true",
        help="Eski parametr; PPTX yaratish vaqtincha o'chirilgan",
    )
    parser.add_argument(
        "--qoida5",
        action="store_true",
        help="5-qoida bo'yicha berilgan shablon asosida PPTX hisobot yaratadi",
    )
    parser.add_argument(
        "--only_monitoring",
        action="store_true",
        help="Faqat CSV va HTML monitoring hisobotlarini yaratadi",
    )
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument(
        "--yesterday",
        action="store_true",
        help="Hisobot sanasini kechagi kunga belgilaydi",
    )
    date_group.add_argument(
        "--report-date",
        metavar="YYYY-MM-DD",
        help="Hisobot sanasi (masalan: 2026-09-14)",
    )
    args = parser.parse_args()

    if args.clean_reports:
        report_dir = Path(args.outdir)
        patterns = (
            "hisobot_*.csv",
            "monitoring_dashboard.html",
            "*. hisobot_*.pptx",
            "*. hisobot_1qoida_*.pptx",
            "aylantirish_*.pptx",
        )
        removed = []
        if report_dir.exists():
            for pattern in patterns:
                for path in report_dir.glob(pattern):
                    if path.is_file():
                        path.unlink()
                        removed.append(path)
        print(f"{GREEN}Hisobotlar tozalandi: {len(removed)} ta fayl o'chirildi.{RESET}")
        if removed:
            for path in removed:
                print(f"  - {path}")
        return

    if args.report_date:
        try:
            report_date = datetime.strptime(args.report_date, "%Y-%m-%d").date()
        except ValueError:
            parser.error("--report-date YYYY-MM-DD formatida bo'lishi kerak")
    elif args.yesterday:
        report_date = date.today() - timedelta(days=1)
    else:
        report_date = date.today()

    token = args.token
    if not token:
        print(f"{RED}Xatolik: Token ko'rsatilmadi! --token orqali yoki HOSIL_TOKEN muhit o'zgaruvchisida bering.{RESET}")
        sys.exit(1)

    print(f"{BOLD}{GREEN}🌿 Paxta monitoring tizimiga ulanilmoqda...{RESET}")
    client = HosilApiClient(token=token)

    try:
        user_info = client.get_user_info()
        u = user_info.get("user_info", {})
        f_name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
        region_name = u.get("region_name") or "Barcha viloyatlar"
        region_id = u.get("region_id") or "fb36b2fb-9cea-45d2-8db6-98729ce76672"
        print(f"{GREEN}Muvaffaqiyatli ulandi:{RESET} Foydalanuvchi: {BOLD}{f_name}{RESET} | Hudud: {BOLD}{region_name}{RESET}")
    except Exception as e:
        print(f"{RED}Tizimga ulanishda xatolik yuz berdi: {e}{RESET}")
        sys.exit(1)

    def run_check():
        print(f"\n{CYAN}Viloyatdagi barcha tumanlar va maskanlar bo'yicha yuklar olinmoqda...{RESET}")

        def progress(event, data):
            if event == "district_start":
                print(f"  [{data['index']}/{data['total']}] {data['district']} tekshirilmoqda...", end="\r")
            elif event == "complete":
                print(f"\n{GREEN}Barcha ma'lumotlar yuklandi! Jami yuklar soni: {data['total_loads']}{RESET}")

        loads = client.get_all_region_loads(region_id, year=args.year, progress_callback=progress)
        
        analyzer = CottonAnomalyAnalyzer(loads, rule2_max_minutes=RULE2_MAX_MINUTES)
        result = analyzer.run_all()

        reporter = ReportGenerator(result)
        reporter.print_console_summary()

        if args.export:
            os.makedirs(args.outdir, exist_ok=True)
            reporter.export_csv(args.outdir)
            reporter.export_html(
                os.path.join(args.outdir, "monitoring_dashboard.html"),
                report_date=report_date,
            )
            if args.qoida5 and not args.only_monitoring:
                reporter.export_pptx_rule5_reports(
                    args.outdir,
                    template_path=PPTX_TEMPLATE_PATH,
                    report_date=report_date,
                    image_headers=client.headers,
                )
            elif not args.only_monitoring:
                print(f"{YELLOW}PPTX prezentatsiya yaratish vaqtincha o'chirilgan.{RESET}")

    # Jonli monitoring rejimi yoki bir martalik tekshiruv
    if args.live > 0:
        print(f"\n{BOLD}{MAGENTA}Jonli monitoring rejimi yoqildi (Har {args.live} soniyada yangilanadi)...{RESET}")
        try:
            while True:
                run_check()
                print(f"\n{CYAN}Navbatdagi tekshiruvgacha {args.live} soniya kutilmoqda... (To'xtatish uchun Ctrl+C){RESET}")
                time.sleep(args.live)
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Monitoring to'xtatildi.{RESET}")
    else:
        run_check()

if __name__ == "__main__":
    main()
