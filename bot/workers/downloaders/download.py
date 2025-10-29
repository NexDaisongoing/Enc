from bot import *
from bot.config import _bot, conf
from bot.fun.emojis import enhearts, enmoji, enmoji2
from bot.utils.bot_utils import (
    code,
    decode,
    get_aria2,
    hbs,
    replace_proxy,
    sync_to_async,
    time_formatter,
    value_check,
)
from bot.utils.log_utils import log, logger
from bot.utils.os_utils import parse_dl, s_remove

from .dl_helpers import (
    get_files_from_torrent,
    get_qbclient,
    rm_leech_file,
    rm_torrent_file,
    rm_torrent_tag,
)


class Downloader:
    def __init__(
        self,
        sender=123456,
        lc=None,
        _id=None,
        uri=False,
        dl_info=False,
        folder="downloads/",
        qbit=None,
    ):
        self.sender = int(sender)
        self.callback_data = "cancel_download"
        self.is_cancelled = False
        self.canceller = None
        self.dl_info = dl_info
        self.download_error = None
        self.file_name = None
        self.message = None
        self.dl_folder = folder
        self.id = _id
        self.uri = replace_proxy(uri)
        self.uri_gid = None
        self.lc = lc
        self.lm = None
        self.log_id = None
        self._sender = None
        self.time = None
        self.aria2 = get_aria2()
        self.path = None
        self.qb = None
        self.qbit = qbit
        self.jd_uuid = None
        self.use_jdownloader = False
        self.unfin_str = conf.UN_FINISHED_PROGRESS_STR
        self.display_dl_info = _bot.display_additional_dl_info
        self.pause_on_dl_info = bool(conf.PAUSE_ON_DL_INFO)
        if self.dl_info:
            self.callback_data_i = "dl_info"
            self.callback_data_b = "back"

    def __str__(self):
        return "#wip"

    def gen_buttons(self):
        cancel_button = InlineKeyboardButton(
            text=f"{enmoji()} Cancel Download", callback_data=self.callback_data
        )
        if self.dl_info:
            info_button = InlineKeyboardButton(text="ℹ️", callback_data=self.callback_data_i)
            more_button = InlineKeyboardButton(text="More…", callback_data="more 0")
            back_button = InlineKeyboardButton(text="↩️", callback_data=self.callback_data_b)
        else:
            info_button = more_button = back_button = None
        return info_button, more_button, back_button, cancel_button

    async def log_download(self):
        if self.lc:
            try:
                cancel_button = InlineKeyboardButton(
                    text=f"{enmoji()} CANCEL DOWNLOAD", callback_data=self.callback_data
                )
                more_button = InlineKeyboardButton(text="ℹ️", callback_data="more 1")
                reply_markup = InlineKeyboardMarkup([[more_button], [cancel_button]])
                dl_info = await parse_dl(self.file_name)
                msg = "Currently downloading a video"
                if self.uri:
                    msg += " from a link"
                message = await pyro.get_messages(self.lc.chat_id, self.lc.id)
                self._sender = self._sender or await pyro.get_users(self.sender)
                await message.edit(
                    f"`{msg} sent by` {self._sender.mention(style='md')}\n" + dl_info,
                    reply_markup=reply_markup,
                )
                self.lm = message
            except Exception:
                await logger(Exception)

    async def start(self, dl, file, message="", e="", select=None):
        try:
            self.file_name = dl
            self.register()

            if self.qbit:
                return await self.start3(dl, file, message, e, select)
            elif self.uri and self.use_jdownloader:
                return await self.start_jd(dl, file, message, e)
            elif self.uri:
                return await self.start2(dl, file, message, e)

            await self.log_download()
            if self.dl_folder:
                self.path = dl = self.dl_folder + dl
            if message:
                self.time = ttt = time.time()
                media_type = str(message.media)
                media_mssg = "`Downloading a file…`" if media_type == "MessageMediaType.DOCUMENT" else "`Downloading a video…`"
                download_task = await pyro.download_media(
                    message=message,
                    file_name=dl,
                    progress=self.progress_for_pyrogram,
                    progress_args=(pyro, media_mssg, e, ttt),
                )
            else:
                download_task = await pyro.download_media(message=file, file_name=dl)

            await self.wait()
            if self.is_cancelled:
                await self.clean_download()
            self.un_register()
            return download_task

        except pyro_errors.BadRequest:
            await reply.edit(f"`Failed {enmoji2()}\nRetrying in 10 seconds…`")
            await asyncio.sleep(10)
            return await self.start(dl, file, message, e)
        except pyro_errors.FloodWait as e:
            await asyncio.sleep(e.value + 10)
            return await self.start(dl, file, message, e)
        except Exception:
            self.un_register()
            await logger(Exception)
            return None

    async def progress_for_pyrogram(self, current, total, app, ud_type, message, start):
        fin_str = enhearts()
        now = time.time()
        diff = now - start
        if self.is_cancelled:
            app.stop_transmission()
        if round(diff % 10.00) == 0 or current == total:
            percentage = current * 100 / total
            elapsed_time = time_formatter(diff)
            speed = current / diff
            time_to_completion = time_formatter(int((total - current) / speed))

            progress = "```\n{0}{1}```\n<b>Progress:</b> `{2}%`\n".format(
                "".join([fin_str for _ in range(math.floor(percentage / 10))]),
                "".join(
                    [self.unfin_str for _ in range(10 - math.floor(percentage / 10))]
                ),
                round(percentage, 2),
            )

            tmp = (
                progress
                + "`{0} of {1}`\n**Speed:** `{2}/s`\n**ETA:** `{3}`\n**Elapsed:** `{4}`\n".format(
                    hbs(current),
                    hbs(total),
                    hbs(speed),
                    time_to_completion if time_to_completion else "0 s",
                    elapsed_time if elapsed_time != "" else "0 s",
                )
            )
            try:
                reply_markup = []
                dl_info = await parse_dl(self.file_name)
                (
                    info_button,
                    more_button,
                    back_button,
                    cancel_button,
                ) = self.gen_buttons()
                if not self.dl_info:
                    reply_markup.append([cancel_button])
                    dsp = "{}\n{}".format(ud_type, tmp)
                elif not self.display_dl_info:
                    reply_markup.extend(([info_button], [cancel_button]))
                    dsp = "{}\n{}".format(ud_type, tmp)
                else:
                    reply_markup.extend(([more_button], [back_button], [cancel_button]))
                    dsp = dl_info
                reply_markup = InlineKeyboardMarkup(reply_markup)
                if not message.photo:
                    self.message = await message.edit_text(
                        text=dsp,
                        reply_markup=reply_markup,
                    )
                else:
                    self.message = await message.edit_caption(
                        caption=dsp,
                        reply_markup=reply_markup,
                    )
            except pyro_errors.FloodWait as e:
                await asyncio.sleep(e.value)
            except BaseException:
                await logger(Exception)

    # --- JDownloader integration ---
    async def start_jd(self, dl, file, message="", e=""):
        """Start JDownloader download"""
        try:
            await self.log_download()
            self.time = ttt = time.time()
            await asyncio.sleep(3)

            from .dl_helpers import jd_add_link, jd_start_download, jd_get_download_status

            jd_info = await jd_add_link(self.uri, save_path=f"{os.getcwd()}/{self.dl_folder}")

            if jd_info.error:
                self.download_error = f"JDownloader Error: {jd_info.error}"
                raise Exception(self.download_error)

            self.jd_uuid = jd_info.uuid
            self.file_name = jd_info.name
            self.path = self.dl_folder + self.file_name

            started = await jd_start_download(jd_info.uuid, jd_info.link_ids)
            if not started:
                self.download_error = "Failed to start JDownloader download"
                raise Exception(self.download_error)

            while True:
                if message:
                    status = await jd_get_download_status(self.jd_uuid)
                    if status:
                        download = await self.progress_for_jd(status, ttt, e)
                        if not download or download.get("finished"):
                            break
                else:
                    await asyncio.sleep(10)
                    status = await jd_get_download_status(self.jd_uuid)
                    if status and status.get("finished"):
                        break

                await self.wait()

            self.un_register()
            return True

        except Exception:
            self.un_register()
            await logger(Exception)
            return None

    async def progress_for_jd(self, status, start, message):
        """Progress handler for JDownloader"""
        try:
            if self.is_cancelled:
                return None

            ud_type = f"**Downloading:**\n`{self.file_name}`\n**via:** JDownloader."

            total = status.get("bytesTotal", 0)
            current = status.get("bytesLoaded", 0)
            speed = status.get("speed", 0)
            eta = status.get("eta", 0)

            now = time.time()
            diff = now - start
            fin_str = enhearts()

            progress_pct = (current / total * 100) if total > 0 else 0

            progress = "```\n{0}{1}```\n<b>Progress:</b> `{2}%`\n".format(
                "".join([fin_str for _ in range(math.floor(progress_pct / 10))]),
                "".join([self.unfin_str for _ in range(10 - math.floor(progress_pct / 10))]),
                round(progress_pct, 2),
            )

            tmp = (
                progress
                + "`{0} of {1}`\n**Speed:** `{2}/s`\n**ETA:** `{3}`\n**Elapsed:** `{4}`\n".format(
                    value_check(hbs(current)),
                    value_check(hbs(total)),
                    value_check(hbs(speed)),
                    time_formatter(eta) if eta else "0 s",
                    time_formatter(diff),
                )
            )

            try:
                reply_markup = []
                dl_info = await parse_dl(self.file_name)
                info_button, more_button, back_button, cancel_button = self.gen_buttons()

                if not self.dl_info:
                    reply_markup.append([cancel_button])
                    dsp = f"{ud_type}\n{tmp}"
                elif not self.display_dl_info:
                    reply_markup.extend(([info_button], [cancel_button]))
                    dsp = f"{ud_type}\n{tmp}"
                else:
                    reply_markup.extend(([more_button], [back_button], [cancel_button]))
                    dsp = dl_info

                reply_markup = InlineKeyboardMarkup(reply_markup)
            except BaseException:
                await logger(BaseException)

            if not message.photo:
                self.message = await message.edit_text(text=dsp, reply_markup=reply_markup)
            else:
                self.message = await message.edit_caption(caption=dsp, reply_markup=reply_markup)

            await asyncio.sleep(10)

        except Exception as e:
            self.download_error = str(e)
            await logger(Exception)
            return None

        return status

    async def clean_download(self):
        try:
            if self.qbit:
                await rm_torrent_file(self.uri_gid, qb=self.qb)
                await rm_torrent_tag(self.id, qb=self.qb)
            elif self.use_jdownloader and self.jd_uuid:
                from .dl_helpers import rm_jd_download
                await sync_to_async(rm_jd_download, self.jd_uuid)
            elif self.uri:
                await sync_to_async(rm_leech_file, self.uri_gid)
            else:
                await sync_to_async(s_remove, self.path)
        except Exception:
            log(Exception)

    async def download_timeout(self):
        try:
            self.download_error = (
                "E28: Download took longer than the specified time limit and has therefore been cancelled!"
            )
            await self.clean_download()
        except Exception:
            log(Exception)

    async def wait(self):
        if (
            self.message
            and self.display_dl_info
            and self.pause_on_dl_info
            and self.dl_info
        ):
            msg = "been completed." if not self.is_cancelled else "been cancelled!"
            msg = "ran into errors!" if self.download_error else msg
            (
                info_button,
                more_button,
                back_button,
                cancel_button,
            ) = self.gen_buttons()
            reply_markup = InlineKeyboardMarkup([[more_button], [back_button]])
            await self.message.edit(
                self.message.text.markdown + f"\n\n`Download has {msg}\nTo continue click back.`",
                reply_markup=reply_markup,
            )
        while self.dl_info and self.display_dl_info and self.pause_on_dl_info:
            await asyncio.sleep(5)