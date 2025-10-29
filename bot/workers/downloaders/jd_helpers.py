import json
import uuid
from pathlib import Path

from bot import asyncio, os, time
from bot.config import conf
from bot.utils.bot_utils import Qbit_c, sync_to_async
from bot.utils.log_utils import log, logger

try:
    import myjdapi
except ImportError:
    myjdapi = None
    log("myjdapi not installed. Install with: pip install myjdapi")


class JDClient:
    """JDownloader API Client Wrapper"""
    
    def __init__(self):
        self.jd = None
        self.device = None
        self.is_connected = False
        
    async def connect(self):
        """Connect to JDownloader"""
        if not myjdapi:
            return False
            
        try:
            self.jd = myjdapi.Myjdapi()
            self.jd.set_app_key("ENCODER_BOT")
            
            # Connect to My.JDownloader
            await sync_to_async(
                self.jd.connect,
                conf.JD_EMAIL,
                conf.JD_PASSWORD
            )
            
            # Get device
            await sync_to_async(self.jd.update_devices)
            devices = self.jd.list_devices()
            
            if not devices:
                log("No JDownloader devices found!")
                return False
                
            self.device = self.jd.get_device(devices[0]["id"])
            self.is_connected = True
            log(f"Connected to JDownloader device: {devices[0]['name']}")
            return True
            
        except Exception as e:
            log(f"Failed to connect to JDownloader: {e}")
            await logger(Exception)
            return False
    
    async def disconnect(self):
        """Disconnect from JDownloader"""
        try:
            if self.jd:
                await sync_to_async(self.jd.disconnect)
                self.is_connected = False
        except Exception:
            log(Exception)


# Global JD client instance
_jd_client = None


async def get_jd_client():
    """Get or create JDownloader client"""
    global _jd_client
    
    if not myjdapi:
        return None
        
    if _jd_client is None:
        _jd_client = JDClient()
        
    if not _jd_client.is_connected:
        success = await _jd_client.connect()
        if not success:
            return None
            
    return _jd_client


async def jd_add_links(url, download_path=None):
    """
    Add links to JDownloader
    
    Args:
        url: Download URL
        download_path: Custom download path
        
    Returns:
        dict with link info or error
    """
    client = await get_jd_client()
    if not client:
        return {"error": "JDownloader not available"}
        
    try:
        # Set download directory if specified
        if download_path:
            download_path = os.path.abspath(download_path)
        else:
            download_path = os.path.join(os.getcwd(), "downloads")
            
        # Add link
        await sync_to_async(
            client.device.linkgrabber.add_links,
            [{"autostart": True, "links": url, "destinationFolder": download_path}]
        )
        
        # Wait a bit for link to be added
        await asyncio.sleep(2)
        
        return {"success": True, "path": download_path}
        
    except Exception as e:
        await logger(Exception)
        return {"error": str(e)}


async def get_jd_link_info(url):
    """
    Get information about a link from JDownloader
    
    Args:
        url: Download URL
        
    Returns:
        Qbit_c object with file info
    """
    jd_info = Qbit_c()
    client = await get_jd_client()
    
    if not client:
        jd_info.error = "JDownloader not available"
        return jd_info
        
    try:
        # Add link to linkgrabber
        tag = str(uuid.uuid4())
        temp_path = os.path.join(os.getcwd(), "temp", tag)
        
        await sync_to_async(
            client.device.linkgrabber.add_links,
            [{"autostart": False, "links": url, "destinationFolder": temp_path}]
        )
        
        # Wait for link analysis
        start_time = time.time()
        timeout = 60
        
        while True:
            if time.time() - start_time > timeout:
                jd_info.error = "Timeout waiting for link analysis"
                break
                
            # Query linkgrabber
            query_result = await sync_to_async(
                client.device.linkgrabber.query_links,
                [{"bytesTotal": True, "enabled": True, "packageUUIDs": True}]
            )
            
            if query_result:
                # Get the latest added link
                for link in query_result:
                    if link.get("url") == url or url in link.get("url", ""):
                        jd_info.name = link.get("name", "Unknown")
                        jd_info.count = 1
                        jd_info.file_list = [jd_info.name]
                        
                        # Clean up - remove from linkgrabber
                        link_ids = [link.get("uuid")]
                        await sync_to_async(
                            client.device.linkgrabber.remove_links,
                            link_ids,
                            link_ids
                        )
                        
                        return jd_info
                        
            await asyncio.sleep(2)
            
        # Cleanup on timeout
        await sync_to_async(client.device.linkgrabber.cleanup, "DELETE_ALL", "SELECTED", "NONE")
        
    except Exception as e:
        jd_info.error = str(e)
        await logger(Exception)
        
    return jd_info


async def jd_download(url, download_path, tag=None):
    """
    Download file using JDownloader
    
    Args:
        url: Download URL
        download_path: Path where to save the file
        tag: Unique identifier for this download
        
    Returns:
        dict with download status
    """
    client = await get_jd_client()
    if not client:
        return {"error": "JDownloader not available"}
        
    try:
        tag = tag or str(uuid.uuid4())
        download_path = os.path.abspath(download_path)
        
        # Add link and start download
        await sync_to_async(
            client.device.linkgrabber.add_links,
            [{"autostart": True, "links": url, "destinationFolder": download_path}]
        )
        
        # Wait a bit for download to start
        await asyncio.sleep(3)
        
        return {
            "success": True,
            "tag": tag,
            "path": download_path
        }
        
    except Exception as e:
        await logger(Exception)
        return {"error": str(e)}


async def get_jd_download_progress(url=None):
    """
    Get download progress from JDownloader
    
    Args:
        url: Optional URL to filter downloads
        
    Returns:
        dict with progress information
    """
    client = await get_jd_client()
    if not client:
        return None
        
    try:
        # Query downloads
        downloads = await sync_to_async(
            client.device.downloads.query_links,
            [{"bytesLoaded": True, "bytesTotal": True, "speed": True, 
              "eta": True, "status": True, "enabled": True, "running": True}]
        )
        
        if not downloads:
            return None
            
        # Filter by URL if provided
        if url:
            downloads = [d for d in downloads if url in d.get("url", "")]
            
        if not downloads:
            return None
            
        # Return info for first matching download
        dl = downloads[0]
        return {
            "name": dl.get("name", "Unknown"),
            "bytes_loaded": dl.get("bytesLoaded", 0),
            "bytes_total": dl.get("bytesTotal", 0),
            "speed": dl.get("speed", 0),
            "eta": dl.get("eta", 0),
            "status": dl.get("status", "Unknown"),
            "running": dl.get("running", False)
        }
        
    except Exception as e:
        await logger(Exception)
        return None


async def jd_cancel_download(url=None, package_id=None):
    """
    Cancel JDownloader download
    
    Args:
        url: URL of download to cancel
        package_id: Package ID to cancel
    """
    client = await get_jd_client()
    if not client:
        return False
        
    try:
        # Get downloads
        downloads = await sync_to_async(
            client.device.downloads.query_links,
            [{"bytesLoaded": True, "packageUUIDs": True}]
        )
        
        if not downloads:
            return False
            
        # Filter downloads
        to_remove = []
        packages = []
        
        for dl in downloads:
            if url and url in dl.get("url", ""):
                to_remove.append(dl.get("uuid"))
                packages.append(dl.get("packageUUID"))
            elif package_id and dl.get("packageUUID") == package_id:
                to_remove.append(dl.get("uuid"))
                packages.append(dl.get("packageUUID"))
                
        if to_remove:
            # Remove downloads
            await sync_to_async(
                client.device.downloads.remove_links,
                to_remove,
                packages
            )
            return True
            
        return False
        
    except Exception as e:
        await logger(Exception)
        return False


async def jd_cleanup():
    """Cleanup finished/failed downloads in JDownloader"""
    client = await get_jd_client()
    if not client:
        return
        
    try:
        await sync_to_async(
            client.device.downloads.cleanup,
            "DELETE_ALL", "FINISHED", "NONE"
        )
        await sync_to_async(
            client.device.downloads.cleanup,
            "DELETE_ALL", "FAILED", "NONE"
        )
    except Exception:
        log(Exception)


async def check_jd_available():
    """Check if JDownloader is available and connected"""
    if not myjdapi:
        return False
        
    client = await get_jd_client()
    return client is not None and client.is_connected


async def rm_jd_download(url):
    """Remove JDownloader download and files"""
    try:
        await jd_cancel_download(url=url)
        await jd_cleanup()
    except Exception:
        log(Exception)