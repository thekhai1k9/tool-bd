from sheet_helper import GoogleSheetManager
from browser_helper import TikTokBrowserAutomation
from workflow import BookingWorkflow, RunSources
import diagnostics
import interaction

from config import CREDENTIALS_FILE, SPREADSHEET_URL, SEARCH_PAGE_URL, resolve_spreadsheet_url, spreadsheet_id_from_url

def main(bot=None, spreadsheet_url=None):
    reuse_browser = bot is not None
    interaction.checkpoint()
    diagnostics.set_context(shop=None, sku=None, batch=None, keyword=None, creator=None, stage="load_sources")
    print("--- [TASK 1] KHỞI ĐỘNG HỆ THỐNG TỰ ĐỘNG ---")

    try:
        sheet_url = resolve_spreadsheet_url(spreadsheet_url)
        sheet_mgr = GoogleSheetManager(CREDENTIALS_FILE, sheet_url)
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
        return False

    bot = bot if reuse_browser else TikTokBrowserAutomation()
    grand_total = 0

    try:
        diagnostics.set_context(stage="browser_start")
        interaction.checkpoint()
        if reuse_browser and bot.page is not None and not bot.page.is_closed():
            bot.page.goto(SEARCH_PAGE_URL)
        else:
            bot.start_browser()
        diagnostics.set_context(stage="login")
        bot.wait_for_user_login()
        _, current_shop_name = bot.check_current_shop()
        diagnostics.set_context(shop=current_shop_name, stage="load_invitation_templates")

        invitation_templates = sheet_mgr.load_invitation_templates()    

        if not current_shop_name: 
            print("   ❌ Không xác định được Shop đang đăng nhập. Dừng tool!")
            return False
        print(f"\n🚀 Đang chạy automation cho Shop: {current_shop_name} (Tên Shop: {current_shop_name})")

        creator_search_url = bot.page.url

        sources = RunSources(kw_lookup, en_kw_lookup, existing, invitation_templates,
                             spreadsheet_id=spreadsheet_id_from_url(sheet_url))
        workflow = BookingWorkflow(sheet_mgr, bot, current_shop_name, creator_search_url, sources)
        for sku in skus:
            interaction.checkpoint()
            grand_total = workflow.process_sku(sku, grand_total)

        print(f"\n=== [HOÀN TẤT] Tổng {grand_total} creator mới ===")
        return True

    except Exception as e:
        diagnostics.capture_error(bot.page, e)
        print(f"Đã xảy ra lỗi trong quá trình chạy: {e}")
        return False
    # finally:
    #     bot.close()


if __name__ == "__main__":
    with diagnostics.RunSession():
        main()
