import logging
import os
import tempfile
from datetime import datetime

import requests
from instaloader import Instaloader, Profile
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def build_ig_loader() -> Instaloader:
    loader = Instaloader(
        download_comments=False,
        download_geotags=False,
        download_video_thumbnails=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )

    ig_sessionid = os.getenv("IG_SESSIONID")
    if ig_sessionid:
        try:
            loader.context._session.cookies.set("sessionid", ig_sessionid, domain=".instagram.com")
            # Validate cookie session quickly.
            loader.test_login()
            logger.info("Instagram sessionid cookie loaded successfully.")
        except Exception as exc:
            logger.warning("Instagram sessionid cookie failed: %s", exc)

    return loader


IG_LOADER = build_ig_loader()


def profile_caption(profile: Profile) -> str:
    bio = profile.biography if profile.biography else "No bio"
    # Telegram caption safe limit is 1024 chars.
    if len(bio) > 250:
        bio = bio[:247] + "..."

    lines = [
        "✅ <b>Instagram Profile Found</b>",
        "",
        f"👤 <b>Name:</b> {profile.full_name or 'N/A'}",
        f"🆔 <b>Username:</b> @{profile.username}",
        f"📌 <b>User ID:</b> <code>{profile.userid}</code>",
        f"🔒 <b>Private:</b> {'Yes' if profile.is_private else 'No'}",
        f"✔️ <b>Verified:</b> {'Yes' if profile.is_verified else 'No'}",
        f"📝 <b>Bio:</b> {bio}",
        f"📷 <b>Posts:</b> {profile.mediacount:,}",
        f"👥 <b>Followers:</b> {profile.followers:,}",
        f"➡️ <b>Following:</b> {profile.followees:,}",
        "",
        f"🔗 <a href='https://instagram.com/{profile.username}'>Open on Instagram</a>",
        f"⏰ <i>Fetched at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>",
    ]
    return "\n".join(lines)


def download_profile_picture(url: str) -> str:
    response = requests.get(url, timeout=20)
    response.raise_for_status()

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    tmp.write(response.content)
    tmp.flush()
    tmp.close()
    return tmp.name


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 <b>Welcome!</b>\n\n"
        "Send me an Instagram username (without @), and I will fetch profile details.\n\n"
        "Example: <code>instagram</code>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def fetch_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    raw_text = update.message.text.strip()
    username = raw_text.replace("@", "").split()[0].strip().lower()

    if not username:
        await update.message.reply_text("⚠️ Please send a valid Instagram username.")
        return

    wait_msg = await update.message.reply_text("⏳ Fetching profile... please wait.")

    try:
        profile = Profile.from_username(IG_LOADER.context, username)
        caption = profile_caption(profile)
        photo_path = download_profile_picture(profile.profile_pic_url)

        with open(photo_path, "rb") as photo_file:
            await update.message.reply_photo(
                photo=photo_file,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
        try:
            os.remove(photo_path)
        except OSError:
            pass

    except Exception as exc:
        logger.exception("Failed to fetch profile for %s", username)
        await update.message.reply_text(
            "❌ Could not fetch this profile.\n"
            "Possible reasons:\n"
            "• Username does not exist\n"
            "• Instagram rate-limit / temporary block\n"
            "• Private/restricted profile data",
        )
        logger.debug("Error details: %s", exc)
    finally:
        await wait_msg.delete()


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN environment variable first.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fetch_profile))

    logger.info("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
