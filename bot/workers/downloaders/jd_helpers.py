import uuid
import os
from bot import asyncio, time
from bot.config import conf
from bot.utils.bot_utils import Qbit_c, sync_to_async
from bot.utils.log_utils import log, logger

# JDownloader API integration
try:
    import myjdapi
    JD_AVAILABLE = True
except ImportError:
    JD_AVAILABLE = False
    log("myjdapi not installed. Install with: pip install myjdapi")


class JDClient:
    """JDownloader client wrapper for with/without account"""
    
    def __init__(self):
        self.jd = None
        self.device = None
        self.use_account = False
        self.direct_mode = False
        
    async def connect(self):
        """Connect to JDownloader with or without MyJD account"""
        if not JD_AVAILABLE:
            raise Exception("myjdapi library not installed")
            
        try:
            # Check if JD account credentials are in config
            jd_email = getattr(conf, 'JD_EMAIL', None)
            jd_password = getattr(conf, 'JD_PASSWORD', None)
            jd_device_name = getattr(conf, 'JD_DEVICE_NAME', 'JDownloader')
            jd_direct_url = getattr(conf, 'JD_DIRECT_URL', None)  # e.g., http://localhost:3128
            
            if jd_direct_url:
                # Direct connection mode (no account needed)
                self.direct_mode = True
                self.jd = myjdapi.Myjdapi()
                self.jd.set_app_key("TelegramBot_JD")
                # For direct mode, we'll use direct API calls
                log("JDownloader: Using direct connection mode")
                return True
                
            elif jd_email and jd_password:
                # MyJDownloader account mode
                self.use_account = True
                self.jd = myjdapi.Myjdapi()
                self.jd.set_app_key("TelegramBot_JD")
                
                await sync_to_async(self.jd.connect, jd_email, jd_password)
                await sync_to_async(self.jd.update_devices)
                
                # Get device
                self.device = self.jd.get_device(jd_device_name)
                if not self.device:
                    raise Exception(f"Device '{jd_device_name}' not found")
                    
                log(f"JDownloader: Connected with account to device '{jd_device_name}'")
                return True
            else:
                # No config found - cannot connect
                raise Exception("JDownloader credentials not configured in config file")
                
        except Exception as e:
            await logger(Exception)
            raise Exception(f"Failed to connect to JDownloader: {str(e)}")
    
    async def disconnect(self):
        """Disconnect from JDownloader"""
        if self.jd and self.use_account:
            try:
                await sync_to_async(self.jd.disconnect)
            except Exception:
                pass


def get_jd_client():
    """Get or create JDownloader client"""
    if not hasattr(get_jd_client, 'client'):
        get_jd_client.client = JDClient()
    return get_jd_client.client


async def jd_add_link(url, save_path=None):
    """
    Add link to JDownloader
    Returns: dinfo object with name or error
    """
    dinfo = Qbit_c()
    jd_client = get_jd_client()
    
    try:
        # Connect to JD
        if not jd_client.device and not jd_client.direct_mode:
            await jd_client.connect()
        
        if save_path is None:
            save_path = os.getcwd() + "/downloads"
        
        # Add link to JDownloader
        if jd_client.use_account and jd_client.device:
            # Using MyJD account
            await sync_to_async(
                jd_client.device.linkgrabber.add_links,
                [{
                    "autostart": False,
                    "links": url,
                    "packageName": "TelegramBot",
                    "destinationFolder": save_path,
                    "overwritePackagizerRules": True
                }]
            )
        elif jd_client.direct_mode:
            # Direct mode - would need implementation based on direct API
            # This is a simplified version
            raise Exception("Direct mode not fully implemented yet")
        
        # Wait for link to be grabbed
        await asyncio.sleep(3)
        
        # Get link info from linkgrabber
        if jd_client.use_account and jd_client.device:
            packages = await sync_to_async(
                jd_client.device.linkgrabber.query_packages,
                [{
                    "saveTo": True,
                    "packageName": True,
                    "maxResults": 10,
                    "startAt": 0
                }]
            )
            
            # Find our package
            for package in packages:
                if package.get('saveTo') == save_path:
                    links = await sync_to_async(
                        jd_client.device.linkgrabber.query_links,
                        [{
                            "packageUUIDs": [package.get('uuid')],
                            "name": True,
                            "url": True,
                            "maxResults": 1
                        }]
                    )
                    
                    if links:
                        dinfo.name = links[0].get('name', 'unknown')
                        dinfo.uuid = package.get('uuid')
                        dinfo.link_ids = [link.get('uuid') for link in links]
                        break
        
        if not dinfo.name:
            dinfo.error = "Could not get filename from JDownloader"
            
    except Exception as e:
        dinfo.error = str(e)
        await logger(Exception)
    
    return dinfo


async def jd_start_download(package_uuid, link_uuids=None):
    """
    Start download in JDownloader
    Moves links from linkgrabber to downloads
    """
    jd_client = get_jd_client()
    
    try:
        if not jd_client.device:
            await jd_client.connect()
        
        if jd_client.use_account and jd_client.device:
            # Move to downloads
            if link_uuids:
                await sync_to_async(
                    jd_client.device.linkgrabber.move_to_downloadlist,
                    link_uuids,
                    package_uuid
                )
            else:
                # Move entire package
                await sync_to_async(
                    jd_client.device.linkgrabber.move_to_downloadlist,
                    [],
                    [package_uuid]
                )
            
            # Start downloads
            await sync_to_async(jd_client.device.downloadcontroller.start_downloads)
            
            return True
    except Exception as e:
        await logger(Exception)
        return False


async def jd_get_download_status(package_uuid):
    """Get download status from JDownloader"""
    jd_client = get_jd_client()
    
    try:
        if not jd_client.device:
            await jd_client.connect()
        
        if jd_client.use_account and jd_client.device:
            packages = await sync_to_async(
                jd_client.device.downloads.query_packages,
                [{
                    "bytesLoaded": True,
                    "bytesTotal": True,
                    "enabled": True,
                    "eta": True,
                    "finished": True,
                    "running": True,
                    "speed": True,
                    "status": True,
                    "saveTo": True,
                    "maxResults": -1
                }]
            )
            
            for package in packages:
                if package.get('uuid') == package_uuid:
                    return package
                    
    except Exception as e:
        await logger(Exception)
    
    return None


async def jd_remove_download(package_uuid=None, link_uuids=None):
    """Remove download from JDownloader"""
    jd_client = get_jd_client()
    
    try:
        if not jd_client.device:
            return
        
        if jd_client.use_account and jd_client.device:
            if link_uuids:
                await sync_to_async(
                    jd_client.device.downloads.remove_links,
                    link_uuids
                )
            if package_uuid:
                await sync_to_async(
                    jd_client.device.linkgrabber.remove_links,
                    [],
                    [package_uuid]
                )
    except Exception:
        log(Exception)


async def jd_cleanup():
    """Cleanup JDownloader connection"""
    try:
        jd_client = get_jd_client()
        await jd_client.disconnect()
    except Exception:
        pass


async def get_jd_name(url):
    """
    Get filename from JDownloader without downloading
    Similar to get_leech_name but for JDownloader
    """
    dinfo = Qbit_c()
    
    try:
        # Add link to get name
        temp_dinfo = await jd_add_link(url, save_path=os.getcwd() + "/temp")
        
        if temp_dinfo.error:
            dinfo.error = temp_dinfo.error
        else:
            dinfo.name = temp_dinfo.name
            
            # Remove from linkgrabber
            if temp_dinfo.uuid:
                await jd_remove_download(package_uuid=temp_dinfo.uuid)
        
    except Exception as e:
        dinfo.error = str(e)
        await logger(Exception)
    
    return dinfo