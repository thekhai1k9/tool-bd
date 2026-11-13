from sheet_helper import GoogleSheetManager
from browser_helper import TikTokBrowserAutomation
from workflow import BookingWorkflow, RunSources
import argparse
from pathlib import Path
import re
import diagnostics

from config import CREDENTIALS_FILE, SPREADSHEET_URL

def profile_directory(profile):
    name = str(profile).strip().lower()
    reserved = {'con', 'prn', 'aux', 'nul'} | {
        f'{prefix}{number}' for prefix in ('com', 'lpt') for number in range(1, 10)
    }
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', name) or name in reserved:
        raise ValueError('Tên profile phải gồm chữ không dấu, số, dấu - hoặc _, tối đa 64 ký tự; không dùng tên thiết bị Windows.')
    return str(Path('user_data') / name)


def parse_arguments(argv=None):
    def profile_name(value):
        try:
            return Path(profile_directory(value)).name
        except ValueError as error:
            raise argparse.ArgumentTypeError(str(error)) from error

    parser = argparse.ArgumentParser(description='TikTok Shop creator automation')
    parser.add_argument('--profile', type=profile_name, default=None,
                        help='Phiên đăng nhập riêng, ví dụ rizin hoặc lunave; bỏ trống để dùng user_data hiện tại.')
    return parser.parse_args(argv)


def main(profile=None):
    profile_dir = profile_directory(profile) if profile is not None else None
    diagnostics.set_context(shop=None, sku=None, batch=None, keyword=None, creator=None, stage="load_sources")
    print("--- [TASK 1] KHỞI ĐỘNG HỆ THỐNG TỰ ĐỘNG ---")

    try:
        sheet_mgr = GoogleSheetManager(CREDENTIALS_FILE, SPREADSHEET_URL)
        skus = sheet_mgr.load_skus()
        keywords_by_product = sheet_mgr.load_keywords()
        english_keywords_by_product = sheet_mgr.load_keywords("LIST KEYWORD EN", optional=True)
        existing = sheet_mgr.load_existing_creators()
        kw_lookup = {k.strip().lower(): v for k, v in keywords_by_product.items()}
        en_kw_lookup = {k.strip().lower(): v for k, v in english_keywords_by_product.items()}
        print(f"-> {len(skus)} SKU, {len(keywords_by_product)} nhóm keyword, "
              f"{len(existing)} creator đã lưu.")
        print(f"-> LIST KEYWORD EN: {len(english_keywords_by_product)} nhóm sản phẩm.")
    except Exception as e:
        diagnostics.log_exception("Không đọc được nguồn Google Sheet", e)
        print(f"Lỗi kết nối hoặc đọc Google Sheet: {e}")
        return

    if profile_dir is not None:
        print(f'-> Profile trình duyệt: {profile_dir}')
        bot = TikTokBrowserAutomation(user_data_dir=profile_dir)
    else:
        bot = TikTokBrowserAutomation()
    grand_total = 0

    try:
        diagnostics.set_context(stage="browser_start")
        bot.start_browser()
        diagnostics.set_context(stage="login")
        bot.wait_for_user_login()
        _, current_shop_name = bot.check_current_shop()
        diagnostics.set_context(shop=current_shop_name, stage="load_invitation_templates")

        invitation_templates = sheet_mgr.load_invitation_templates()    

        if not current_shop_name: 
            print("   ❌ Không xác định được Shop đang đăng nhập. Dừng tool!")
            return
        print(f"\n🚀 Đang chạy automation cho Shop: {current_shop_name} (Tên Shop: {current_shop_name})")

        creator_search_url = bot.page.url

        sources = RunSources(kw_lookup, en_kw_lookup, existing, invitation_templates)
        workflow = BookingWorkflow(sheet_mgr, bot, current_shop_name, creator_search_url, sources)
        for sku in skus:
            grand_total = workflow.process_sku(sku, grand_total)

        print(f"\n=== [HOÀN TẤT] Tổng {grand_total} creator mới ===")

    except Exception as e:
        diagnostics.capture_error(bot.page, e)
        print(f"Đã xảy ra lỗi trong quá trình chạy: {e}")
    # finally:
    #     bot.close()


if __name__ == "__main__":
    args = parse_arguments()
    with diagnostics.RunSession():
        main(profile=args.profile)
