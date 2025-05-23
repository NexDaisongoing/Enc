import traceback
import logging 

from bot import LOGS, conf, tele
from bot.fun.emojis import enmoji


def log(Exception: Exception = None, e: str = None, critical=False):
    trace = e or traceback.format_exc()
    LOGS.info(trace) if not critical else LOGS.critical(trace)


async def channel_log(Exception: Exception, e: str):
    if conf.LOG_CHANNEL and conf.LOGS_IN_CHANNEL:
        try:
            error = e or traceback.format_exc()
            msg = await tele.send_message(
                conf.LOG_CHANNEL,
                f"**#ERROR\n\n⛱️ Summary of what happened:**\n`{error}`\n\n**To restict error messages to logs set the** `conf.LOGS_IN_CHANNEL` **env var to** `False`. {enmoji()}",
            )
            return msg
        except Exception:
            LOGS.info(error)
            LOGS.info(traceback.format_exc())

async def logger(Exception: Exception = None, e: str = None, critical=False, important=False):
    # Handle log to terminal
    if critical:
        logging.critical(e or str(Exception))
    elif important:
        logging.info(f"[IMPORTANT] {e or str(Exception)}")
    else:
        logging.info(e or str(Exception))

    # Forward to your custom log handler
    await channel_log(Exception, e)